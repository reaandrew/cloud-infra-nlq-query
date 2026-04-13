#!/usr/bin/env python3
"""
Embeds each enriched schema markdown doc with Titan Text Embeddings V2 and
upserts the resulting vectors into the S3 Vectors index.

The embedding is over the FULL enriched markdown — the Claude-generated
description, common queries, notable fields, and the raw field-path list
together. This gives the retriever both human-language signal and the
literal AWS Config field paths.

Idempotent: re-runs upsert in place. Safe to run every time you regenerate
enriched docs.

Usage:
    aws-vault exec ee-sandbox -- ./scripts/index_schemas.py
    aws-vault exec ee-sandbox -- ./scripts/index_schemas.py --only AWS::EC2::Instance
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent
ENRICHED_DIR = REPO_ROOT / "data" / "enriched_schemas"

DEFAULT_REGION = os.environ.get("AWS_REGION", "eu-west-2")
DEFAULT_EMBED_MODEL = os.environ.get("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
DEFAULT_BUCKET = os.environ.get("SCHEMAS_VECTOR_BUCKET", "cinq-schemas-vectors")
DEFAULT_INDEX = os.environ.get("SCHEMAS_VECTOR_INDEX", "cinq-schemas-index")
DEFAULT_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))
DEFAULT_WORKERS = int(os.environ.get("INDEX_WORKERS", "8"))

# put_vectors caps at 500 vectors per call (per the API). 417 schemas fit
# comfortably but the loop chunks anyway so the script scales upward.
PUT_BATCH_SIZE = 250


def list_enriched() -> list[Path]:
    return sorted(ENRICHED_DIR.glob("*.md"))


def resource_type_from_path(p: Path) -> str:
    return p.stem


def parse_metadata(md: str) -> dict[str, str | int]:
    """Extract Service / Category / Field count from the markdown header."""
    out: dict[str, str | int] = {}
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("- **Service**:"):
            out["service"] = line.split(":", 1)[1].strip()
        elif line.startswith("- **Category**:"):
            out["category"] = line.split(":", 1)[1].strip()
        elif line.startswith("- **Field count**:"):
            try:
                out["field_count"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return out


def embed(client, model_id: str, dims: int, text: str) -> list[float]:
    body = {"inputText": text, "dimensions": dims, "normalize": True}
    resp = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
    )
    payload = json.loads(resp["body"].read())
    return payload["embedding"]


def embed_one(client, model_id: str, dims: int, md_path: Path):
    resource_type = resource_type_from_path(md_path)
    text = md_path.read_text()
    meta = parse_metadata(text)
    meta["resource_type"] = resource_type
    vector = embed(client, model_id, dims, text)
    return resource_type, vector, meta


def put_batch(s3v, bucket: str, index: str, batch: list[dict]) -> None:
    s3v.put_vectors(
        vectorBucketName=bucket,
        indexName=index,
        vectors=batch,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--model", default=DEFAULT_EMBED_MODEL)
    p.add_argument("--bucket", default=DEFAULT_BUCKET)
    p.add_argument("--index", default=DEFAULT_INDEX)
    p.add_argument("--dimensions", type=int, default=DEFAULT_DIMENSIONS)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--only", help="Comma-separated list of resource types to (re)index")
    args = p.parse_args()

    md_files = list_enriched()
    if args.only:
        wanted = set(args.only.split(","))
        md_files = [m for m in md_files if resource_type_from_path(m) in wanted]
    if not md_files:
        print("no enriched schemas — run scripts/enrich_schemas.py first", file=sys.stderr)
        sys.exit(1)

    print(f"enriched schemas:   {len(md_files)}")
    print(f"embed model:        {args.model}")
    print(f"dimensions:         {args.dimensions}")
    print(f"vector bucket:      {args.bucket}")
    print(f"vector index:       {args.index}")
    print(f"workers:            {args.workers}")
    # rough cost: each doc ~1500 tokens × $0.00002/1K
    approx_tokens = len(md_files) * 1500
    approx_cost = (approx_tokens / 1000) * 0.00002
    print(f"approx Titan cost:  ~${approx_cost:.4f}")
    print()

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=60),
    )
    s3v = boto3.client(
        "s3vectors",
        region_name=args.region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=60),
    )

    started = time.time()
    pending: list[dict] = []
    embedded_ok = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(embed_one, bedrock, args.model, args.dimensions, m): m
            for m in md_files
        }
        for fut in as_completed(futures):
            md_path = futures[fut]
            try:
                resource_type, vector, meta = fut.result()
            except Exception as exc:
                print(f"  ERROR embed {md_path.name}: {exc}", file=sys.stderr)
                continue
            embedded_ok += 1
            pending.append({
                "key": resource_type,
                "data": {"float32": vector},
                "metadata": meta,
            })
            if embedded_ok % 25 == 0:
                print(f"  embedded {embedded_ok}/{len(md_files)}")

    print(f"\nembedded {embedded_ok} schemas in {time.time() - started:.1f}s")

    if not pending:
        print("nothing to upload", file=sys.stderr)
        sys.exit(1)

    started_put = time.time()
    written = 0
    for i in range(0, len(pending), PUT_BATCH_SIZE):
        batch = pending[i : i + PUT_BATCH_SIZE]
        put_batch(s3v, args.bucket, args.index, batch)
        written += len(batch)
        print(f"  put_vectors batch {i // PUT_BATCH_SIZE + 1}: {len(batch)} vectors (total {written}/{len(pending)})")
    print(f"\nput {written} vectors in {time.time() - started_put:.1f}s")


if __name__ == "__main__":
    main()
