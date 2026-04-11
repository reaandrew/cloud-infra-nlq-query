#!/usr/bin/env python3
"""
Unpacks gzipped AWS Config snapshot files from the mock bucket (hierarchical
AWSLogs/{account}/Config/{region}/{Y}/{M}/{D}/ConfigSnapshot/... layout) into
a flat layout in the operational bucket.

Each source `*.json.gz` becomes a single flat `*.json` object in the destination
bucket (the AWS Config snapshot filename already encodes account + timestamp +
UUID, so collisions are not a concern).

Defaults to "today" in UTC. Pass --date YYYY-MM-DD to override.
"""

import argparse
import gzip
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import boto3
from botocore.config import Config


def list_account_prefixes(s3, bucket):
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="AWSLogs/", Delimiter="/"):
        for cp in page.get("CommonPrefixes", []) or []:
            yield cp["Prefix"].split("/")[1]


def list_snapshot_keys(s3, bucket, account, region, y, m, d):
    prefix = f"AWSLogs/{account}/Config/{region}/{y}/{m}/{d}/ConfigSnapshot/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            if obj["Key"].endswith(".json.gz"):
                yield obj["Key"]


def unpack_and_upload(s3, src_bucket, src_key, dst_bucket):
    body = s3.get_object(Bucket=src_bucket, Key=src_key)["Body"].read()
    unpacked = gzip.decompress(body)
    basename = src_key.rsplit("/", 1)[-1]
    assert basename.endswith(".json.gz")
    dst_key = basename[:-3]  # strip .gz
    s3.put_object(
        Bucket=dst_bucket,
        Key=dst_key,
        Body=unpacked,
        ContentType="application/json",
    )
    return dst_key


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src-bucket", required=True)
    p.add_argument("--dst-bucket", required=True)
    p.add_argument("--region", default="eu-west-2",
                   help="AWS Config region path component (default: eu-west-2)")
    p.add_argument("--date",
                   help="UTC date YYYY-MM-DD to process (default: today)")
    p.add_argument("--workers", type=int, default=32)
    args = p.parse_args()

    if args.date:
        dt = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    y, m, d = dt.year, dt.month, dt.day

    s3 = boto3.client(
        "s3",
        config=Config(max_pool_connections=max(args.workers * 2, 32)),
    )

    print(f"Scanning s3://{args.src_bucket}/AWSLogs/*/Config/{args.region}/{y}/{m}/{d}/ConfigSnapshot/")
    keys = []
    for account in list_account_prefixes(s3, args.src_bucket):
        keys.extend(list_snapshot_keys(s3, args.src_bucket, account, args.region, y, m, d))

    if not keys:
        print("No snapshot files found for the target date.")
        return

    print(f"Unpacking {len(keys)} files into s3://{args.dst_bucket}/ using {args.workers} workers")
    done = 0
    errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(unpack_and_upload, s3, args.src_bucket, k, args.dst_bucket): k for k in keys}
        for fut in as_completed(futures):
            try:
                fut.result()
                done += 1
            except Exception as e:
                errors += 1
                print(f"\n  error on {futures[fut]}: {e}", file=sys.stderr)
            if done % 50 == 0 or done == len(keys):
                print(f"  [{done}/{len(keys)}] unpacked", end="\r", flush=True)

    print()
    print(f"Done. {done}/{len(keys)} unpacked to s3://{args.dst_bucket}/, {errors} errors.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
