#!/usr/bin/env python3
"""
Reads gzipped AWS Config snapshot files from the mock bucket and writes them as
Parquet (partitioned by awsAccountId) into the operational bucket in one pass.

Uses DuckDB, which:
  - reads .json.gz from S3 directly (httpfs extension)
  - extracts the scalar fields of each ConfigurationItem into flat columns
  - keeps the nested `configuration` / `supplementaryConfiguration` / `relationships`
    / `tags` payloads as JSON strings (different AWS Config resource types have
    incompatible shapes, so flattening everything fights the data)
  - stamps every row with last_seen_at = current_timestamp so the downstream
    freshness-view pattern (WHERE last_seen_at > now() - interval '24' hour)
    Just Works

Runs locally — credentials picked up from the environment via the DuckDB
`credential_chain` secret provider. Use with aws-vault:

    aws-vault exec ee-sandbox -- ./scripts/export_config_to_parquet.py \\
        --src-bucket cinq-config-mock \\
        --dst-bucket cinq-config \\
        --region eu-west-2

On first run (empty destination) this does a full rebuild. On later runs it
does the same — it's idempotent because PARTITION_BY OVERWRITE_OR_IGNORE
rewrites whichever account partitions it touches.
"""

import argparse
import sys
import time

import duckdb


SQL = """
INSTALL httpfs;
LOAD httpfs;
CREATE OR REPLACE SECRET s3_creds (
    TYPE S3,
    PROVIDER credential_chain,
    REGION '{region}'
);

-- Keep long-lived HTTP connections to S3 instead of tearing them down per GET
SET http_keep_alive = true;

COPY (
    WITH files AS (
        SELECT configurationItems
        FROM read_json(
            's3://{src}/AWSLogs/*/Config/{region}/*/*/*/ConfigSnapshot/*.json.gz',
            columns = {{configurationItems: 'JSON[]'}},
            format = 'unstructured',
            records = true,
            maximum_object_size = 67108864
        )
    ),
    items AS (
        SELECT item
        FROM files, UNNEST(configurationItems) AS t(item)
    )
    SELECT
        json_extract_string(item, '$.awsAccountId')              AS account_id,
        json_extract_string(item, '$.ARN')                       AS arn,
        json_extract_string(item, '$.resourceType')              AS resource_type,
        json_extract_string(item, '$.resourceId')                AS resource_id,
        json_extract_string(item, '$.resourceName')              AS resource_name,
        json_extract_string(item, '$.awsRegion')                 AS aws_region,
        json_extract_string(item, '$.availabilityZone')          AS availability_zone,
        json_extract_string(item, '$.configurationItemStatus')   AS status,
        try_cast(json_extract_string(item, '$.configurationItemCaptureTime') AS TIMESTAMP) AS captured_at,
        try_cast(json_extract_string(item, '$.resourceCreationTime')          AS TIMESTAMP) AS created_at,
        json_extract_string(item, '$.configurationStateId')      AS state_id,
        json_extract_string(item, '$.configurationStateMd5Hash') AS state_hash,
        json_extract(item, '$.tags')::VARCHAR                    AS tags,
        json_extract(item, '$.relationships')::VARCHAR           AS relationships,
        json_extract(item, '$.configuration')::VARCHAR           AS configuration,
        json_extract(item, '$.supplementaryConfiguration')::VARCHAR AS supplementary_configuration,
        current_timestamp                                        AS last_seen_at
    FROM items
    WHERE json_extract_string(item, '$.awsAccountId') IS NOT NULL
) TO 's3://{dst}/'
  (FORMAT parquet,
   COMPRESSION zstd,
   PARTITION_BY (account_id),
   OVERWRITE_OR_IGNORE);
"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src-bucket", required=True)
    p.add_argument("--dst-bucket", required=True)
    p.add_argument("--region", default="eu-west-2")
    p.add_argument("--threads", type=int, default=64,
                   help="DuckDB threads. DuckDB's httpfs reader is I/O-bound on "
                        "small files, so oversubscribing cores is a big win: on "
                        "500 files the run drops from ~350s (6 threads) to ~5s "
                        "(64 threads). Default 64; raise carefully — 256 OOMed "
                        "on a 6-core/8GB box.")
    args = p.parse_args()

    con = duckdb.connect()
    con.execute(f"SET threads = {args.threads};")

    sql = SQL.format(src=args.src_bucket, dst=args.dst_bucket, region=args.region)
    print(f"Exporting s3://{args.src_bucket}/ → s3://{args.dst_bucket}/ (partitioned by account_id)")
    start = time.time()
    try:
        con.execute(sql)
    except duckdb.Error as e:
        print(f"DuckDB error: {e}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.time() - start

    rows = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('s3://{args.dst_bucket}/**/*.parquet')"
    ).fetchone()[0]
    print(f"Done in {elapsed:.1f}s — {rows} rows in s3://{args.dst_bucket}/")


if __name__ == "__main__":
    main()
