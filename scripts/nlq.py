#!/usr/bin/env python3
"""
Natural-language query CLI for cinq.operational_live.

Flow per invocation:
  1. Embed the user question with Titan Text Embeddings V2.
  2. query_vectors against the S3 Vectors index for the top-K most similar
     resource type schemas.
  3. Read those enriched markdown docs from disk (data/enriched_schemas/).
  4. Build a Claude prompt: system explains the cinq.operational_live
     columns and how to use json_extract over the opaque JSON columns;
     retrieved schemas are appended; user question goes last.
  5. Claude (Bedrock) returns a single SELECT in a fenced sql block.
  6. Validate the SQL is a single SELECT (no DDL / DML).
  7. Run via Athena, poll, fetch, print.

Reads bucket/index/database/view names from terraform outputs by default.

Usage:
  aws-vault exec ee-sandbox -- ./scripts/nlq.py "how many EC2 instances per account, top 10"
  aws-vault exec ee-sandbox -- ./scripts/nlq.py --top-k 8 --explain "find encrypted EBS volumes"
  aws-vault exec ee-sandbox -- ./scripts/nlq.py --dry-run "list S3 buckets without versioning"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path

# Suppress boto3's Python 3.9 EOL warning — unrelated to anything the user can do.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="boto3")
try:
    from boto3.compat import PythonDeprecationWarning  # type: ignore
    warnings.filterwarnings("ignore", category=PythonDeprecationWarning)
except Exception:
    pass

import boto3
from botocore.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent
ENRICHED_DIR = REPO_ROOT / "data" / "enriched_schemas"
TF_DIR = REPO_ROOT / "terraform" / "app"

DEFAULT_REGION = os.environ.get("AWS_REGION", "eu-west-2")
DEFAULT_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "primary")
DEFAULT_TOP_K = 5
DEFAULT_MAX_OUTPUT_TOKENS = 1500
DEFAULT_RESULT_PRINT_LIMIT = 100

SQL_BLOCK_RE = re.compile(r"```(?:sql)?\s*(.+?)```", re.DOTALL | re.IGNORECASE)
SELECT_ONLY_RE = re.compile(r"^\s*(WITH\s|SELECT\s)", re.IGNORECASE)
FORBIDDEN_RE = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|MERGE|ALTER|CREATE|GRANT|REVOKE|TRUNCATE|VACUUM|OPTIMIZE|CALL|REPLACE)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT_TEMPLATE = """\
You are an AWS Config natural-language query assistant. You translate user
questions about AWS resources into a single Athena SQL query that runs
against the view {view}.

That view is backed by an Iceberg table holding flattened AWS Config
ConfigurationItems. It has these flat columns (one row per resource):

  account_id (string)            -- AWS account ID, 12 digits
  arn (string)                   -- resource ARN; primary key alongside account_id
  resource_type (string)         -- e.g. 'AWS::EC2::Instance'
  resource_id (string)
  resource_name (string)
  aws_region (string)
  availability_zone (string)
  status (string)                -- AWS Config item status (OK, ResourceDiscovered, ResourceDeleted, etc.)
  captured_at (timestamp)        -- when AWS Config captured this snapshot
  created_at (timestamp)         -- when the resource itself was created
  state_id (string)
  state_hash (string)            -- MD5 of the configuration; cheap change detection
  tags (string)                  -- JSON OBJECT or array; opaque
  relationships (string)         -- JSON ARRAY; opaque
  configuration (string)         -- JSON OBJECT; varies per resource_type
  supplementary_configuration (string)  -- JSON OBJECT; varies per resource_type
  last_seen_at (timestamp)       -- ingest timestamp
  source_key (string)            -- s3 path of the originating snapshot file

The view filters out rows with last_seen_at older than 24 hours, so it
always reflects the current world.

To pull values out of the JSON columns, use Athena's JSON functions:
  json_extract_scalar(configuration, '$.path.to.field')   -- returns VARCHAR
  json_extract(configuration, '$.path.to.array')          -- returns JSON for nested objects/arrays
  cast(json_extract_scalar(...) as integer|double|boolean) for typed comparisons

Below are the relevant resource-type schemas for this question, retrieved
from a vector index. Use the field paths exactly as written. Do not
invent fields. If the question is about a specific resource type, ALWAYS
add a `resource_type = '...'` filter on the appropriate value.

----- RETRIEVED SCHEMAS BEGIN -----
{schemas}
----- RETRIEVED SCHEMAS END -----

Output requirements:
- Return EXACTLY ONE Athena SQL query.
- Wrap it in a single ```sql ... ``` fenced code block. Nothing else.
- It must be a SELECT (or WITH ... SELECT). No DDL, no DML.
- Default to LIMIT {row_limit} if you are listing rows. Do not LIMIT aggregations.
- Use case-insensitive comparisons via LOWER() where appropriate.
- Quote identifiers only if needed; the table is "{view}".
- If the question genuinely cannot be answered from the available schemas,
  return a single SQL comment in the sql block explaining why, e.g.
  ```sql
  -- cannot answer: no schema for AWS::Foo::Bar
  ```
"""


# --------------------- terraform output helper ---------------------

def tf_out(name: str) -> str:
    res = subprocess.run(
        ["terraform", f"-chdir={TF_DIR}", "output", "-raw", name],
        check=True,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip()


# --------------------- vector retrieval ---------------------

def embed_question(client, model_id: str, dims: int, question: str) -> list[float]:
    body = {"inputText": question, "dimensions": dims, "normalize": True}
    resp = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
    )
    payload = json.loads(resp["body"].read())
    return payload["embedding"]


def retrieve_schemas(s3v, bucket: str, index: str, vector: list[float], top_k: int):
    resp = s3v.query_vectors(
        vectorBucketName=bucket,
        indexName=index,
        topK=top_k,
        queryVector={"float32": vector},
        returnMetadata=True,
        returnDistance=True,
    )
    return resp.get("vectors") or []


def load_schema_doc(resource_type: str) -> str:
    p = ENRICHED_DIR / f"{resource_type}.md"
    if not p.exists():
        return f"# {resource_type}\n\n_(no enriched doc on disk)_\n"
    return p.read_text()


# --------------------- LLM SQL generation ---------------------

def generate_sql(client, model_id: str, system_prompt: str, question: str, max_tokens: int) -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": question}],
    }
    resp = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
    )
    payload = json.loads(resp["body"].read())
    text = "".join(
        block["text"] for block in payload["content"] if block["type"] == "text"
    ).strip()
    return text


def extract_sql(text: str) -> str:
    m = SQL_BLOCK_RE.search(text)
    if not m:
        raise ValueError(f"no fenced sql block in model response:\n{text}")
    return m.group(1).strip().rstrip(";")


def validate_select_only(sql: str) -> None:
    stripped = sql.strip()
    if stripped.startswith("--"):
        raise ValueError(f"model returned a comment, not SQL: {stripped}")
    if not SELECT_ONLY_RE.match(stripped):
        raise ValueError(f"refusing non-SELECT SQL: {stripped[:200]}")
    if FORBIDDEN_RE.search(stripped):
        raise ValueError(f"refusing SQL containing forbidden keyword: {stripped[:200]}")


# --------------------- Athena ---------------------

def run_athena(athena, sql: str, database: str, workgroup: str, results_bucket: str, timeout_s: int = 120):
    qid = athena.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": database},
        ResultConfiguration={"OutputLocation": f"s3://{results_bucket}/nlq/"},
        WorkGroup=workgroup,
    )["QueryExecutionId"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state = s["State"]
        if state == "SUCCEEDED":
            return qid
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"athena query {qid} {state}: {s.get('StateChangeReason', '<no reason>')}")
        time.sleep(1.5)
    raise RuntimeError(f"athena query {qid} timed out after {timeout_s}s")


def fetch_results(athena, qid: str, max_rows: int = DEFAULT_RESULT_PRINT_LIMIT):
    rows: list[list[str]] = []
    headers: list[str] | None = None
    pager = athena.get_paginator("get_query_results")
    for page in pager.paginate(QueryExecutionId=qid):
        for row in page["ResultSet"]["Rows"]:
            cells = [c.get("VarCharValue", "") for c in row["Data"]]
            if headers is None:
                headers = cells
                continue
            rows.append(cells)
            if len(rows) >= max_rows:
                return headers or [], rows
    return headers or [], rows


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not headers:
        print("(no rows)")
        return
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(str(c)))

    def fmt(row):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row))

    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print(fmt(r))
    print(f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})")


# --------------------- main ---------------------

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("question", nargs="?", help="Natural language question")
    p.add_argument("--question", "-q", dest="q_flag")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--explain", action="store_true",
                   help="Print the retrieved schemas before the SQL")
    p.add_argument("--dry-run", action="store_true",
                   help="Generate SQL but don't run it against Athena")
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--workgroup", default=DEFAULT_WORKGROUP)
    p.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    args = p.parse_args()

    question = args.question or args.q_flag
    if not question:
        print("usage: nlq.py \"<question>\"", file=sys.stderr)
        sys.exit(2)

    # Resolve infra coordinates from terraform outputs
    bucket = tf_out("schemas_vector_bucket")
    index = tf_out("schemas_vector_index")
    embed_model = tf_out("embedding_model_id")
    chat_model = tf_out("chat_model_id")
    embed_dims = int(tf_out("embedding_dimensions"))
    database = tf_out("glue_database")
    live_view = tf_out("iceberg_live_view")
    results_bucket = tf_out("athena_results_bucket")

    bedrock = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=120),
    )
    s3v = boto3.client(
        "s3vectors",
        region_name=args.region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=60),
    )
    athena = boto3.client("athena", region_name=args.region)

    # 1. embed
    qvec = embed_question(bedrock, embed_model, embed_dims, question)

    # 2. retrieve
    matches = retrieve_schemas(s3v, bucket, index, qvec, args.top_k)
    if not matches:
        print("no schema matches found in S3 Vectors index", file=sys.stderr)
        sys.exit(1)

    print("retrieved schemas:")
    for m in matches:
        meta = m.get("metadata") or {}
        dist = m.get("distance")
        rt = meta.get("resource_type") or m.get("key")
        print(f"  - {rt}  (distance={dist:.4f}, service={meta.get('service','?')}, category={meta.get('category','?')})")
    print()

    schema_blocks: list[str] = []
    for m in matches:
        rt = (m.get("metadata") or {}).get("resource_type") or m.get("key")
        schema_blocks.append(load_schema_doc(rt))
    schemas_text = "\n\n---\n\n".join(schema_blocks)

    if args.explain:
        print("===== retrieved schemas =====")
        print(schemas_text)
        print("===== end retrieved schemas =====\n")

    # 3. ask Claude
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        view=live_view,
        schemas=schemas_text,
        row_limit=DEFAULT_RESULT_PRINT_LIMIT,
    )

    raw_response = generate_sql(bedrock, chat_model, system_prompt, question, args.max_output_tokens)
    sql = extract_sql(raw_response)
    print("generated SQL:")
    print("─" * 60)
    print(sql)
    print("─" * 60)
    print()

    try:
        validate_select_only(sql)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        sys.exit(3)

    if args.dry_run:
        print("(dry-run; not executing)")
        return

    qid = run_athena(athena, sql, database, args.workgroup, results_bucket)
    headers, rows = fetch_results(athena, qid)
    print_table(headers, rows)


if __name__ == "__main__":
    main()
