"""
Stage helpers shared between the submit Lambda and the worker Lambda.

All the slow/expensive bits of the NLQ flow live here so both handler.py
(which used to run them synchronously) and worker.py (which runs them
async and writes progress to S3) import from the same module. No
behavioural changes vs the previous handler.py inline versions — this
file is a pure lift-and-shift plus a tiny bit of config widening now
that the worker is no longer bound to API Gateway's 29-second cap.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

# --- env ---
DATABASE = os.environ["GLUE_DATABASE"]
VIEW = os.environ["ICEBERG_VIEW"]
EMBED_MODEL = os.environ["EMBED_MODEL_ID"]
CHAT_MODEL = os.environ["CHAT_MODEL_ID"]
EMBED_DIMS = int(os.environ["EMBED_DIMENSIONS"])
VECTOR_BUCKET = os.environ["SCHEMAS_VECTOR_BUCKET"]
VECTOR_INDEX = os.environ["SCHEMAS_VECTOR_INDEX"]
ATHENA_RESULTS_BUCKET = os.environ["ATHENA_RESULTS_BUCKET"]
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "primary")

FQ_VIEW = f"{DATABASE}.{VIEW}"
ATHENA_OUTPUT = f"s3://{ATHENA_RESULTS_BUCKET}/api/"

SCHEMAS_DIR = Path(__file__).resolve().parent / "enriched_schemas"

DEFAULT_TOP_K = 5
DEFAULT_MAX_OUTPUT_TOKENS = 1000
DEFAULT_RESULT_ROW_LIMIT = 100
DEFAULT_QUESTION_MAX_CHARS = 2000

# The worker can wait longer than 22s because it isn't serving a live
# HTTP request. 60s Bedrock read, 5 min Athena budget.
WORKER_BEDROCK_READ_TIMEOUT = int(os.environ.get("WORKER_BEDROCK_READ_TIMEOUT", "60"))
WORKER_ATHENA_TIMEOUT = int(os.environ.get("WORKER_ATHENA_TIMEOUT", "300"))

_BEDROCK_CFG = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    read_timeout=WORKER_BEDROCK_READ_TIMEOUT,
    connect_timeout=5,
)
_FAST_CFG = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    read_timeout=15,
    connect_timeout=5,
)
BEDROCK = boto3.client("bedrock-runtime", config=_BEDROCK_CFG)
S3VECTORS = boto3.client("s3vectors", config=_FAST_CFG)
ATHENA = boto3.client("athena", config=_FAST_CFG)

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


def embed_question(question: str) -> list[float]:
    body = {"inputText": question, "dimensions": EMBED_DIMS, "normalize": True}
    resp = BEDROCK.invoke_model(
        modelId=EMBED_MODEL,
        body=json.dumps(body),
        contentType="application/json",
    )
    payload = json.loads(resp["body"].read())
    return payload["embedding"]


def retrieve_schemas(vector: list[float], top_k: int) -> list[dict]:
    resp = S3VECTORS.query_vectors(
        vectorBucketName=VECTOR_BUCKET,
        indexName=VECTOR_INDEX,
        topK=top_k,
        queryVector={"float32": vector},
        returnMetadata=True,
        returnDistance=True,
    )
    return resp.get("vectors") or []


def load_schema_doc(resource_type: str) -> str:
    p = SCHEMAS_DIR / f"{resource_type}.md"
    if not p.exists():
        return f"# {resource_type}\n\n_(no enriched doc bundled)_\n"
    return p.read_text()


def format_matches(matches: list[dict]) -> tuple[list[dict], str]:
    retrieved_schemas: list[dict] = []
    schema_blocks: list[str] = []
    for m in matches:
        meta = m.get("metadata") or {}
        rt = meta.get("resource_type") or m.get("key")
        retrieved_schemas.append({
            "resource_type": rt,
            "service": meta.get("service"),
            "category": meta.get("category"),
            "field_count": meta.get("field_count"),
            "distance": round(float(m.get("distance", 0)), 4),
        })
        schema_blocks.append(load_schema_doc(rt))
    return retrieved_schemas, "\n\n---\n\n".join(schema_blocks)


def build_system_prompt(schemas_text: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        view=FQ_VIEW,
        schemas=schemas_text,
        row_limit=DEFAULT_RESULT_ROW_LIMIT,
    )


def generate_sql(system_prompt: str, question: str, max_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS) -> str:
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": question}],
    }
    resp = BEDROCK.invoke_model(
        modelId=CHAT_MODEL,
        body=json.dumps(body),
        contentType="application/json",
    )
    payload = json.loads(resp["body"].read())
    return "".join(
        block["text"] for block in payload["content"] if block["type"] == "text"
    ).strip()


def extract_sql(text: str) -> str:
    m = SQL_BLOCK_RE.search(text)
    if not m:
        raise ValueError("model did not return a fenced sql block")
    return m.group(1).strip().rstrip(";")


def validate_select_only(sql: str) -> None:
    stripped = sql.strip()
    if stripped.startswith("--"):
        raise ValueError(f"model returned a comment, not SQL: {stripped}")
    if not SELECT_ONLY_RE.match(stripped):
        raise ValueError("only SELECT / WITH queries are allowed")
    if FORBIDDEN_RE.search(stripped):
        raise ValueError("SQL contains a forbidden DDL/DML keyword")


def run_athena(
    sql: str, timeout_s: int
) -> tuple[str, list[str], list[list[str]], dict[str, Any]]:
    import time
    qid = ATHENA.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
        WorkGroup=ATHENA_WORKGROUP,
    )["QueryExecutionId"]
    deadline = time.time() + timeout_s
    qe: dict[str, Any] = {}
    while time.time() < deadline:
        qe = ATHENA.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        state = qe["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(
                f"athena query {qid} {state}: "
                f"{qe['Status'].get('StateChangeReason', '<no reason>')}"
            )
        time.sleep(1.0)
    else:
        raise RuntimeError(f"athena query {qid} timed out after {timeout_s}s")

    stats_raw = qe.get("Statistics") or {}
    stats = {
        "data_scanned_bytes": stats_raw.get("DataScannedInBytes"),
        "engine_execution_ms": stats_raw.get("EngineExecutionTimeInMillis"),
        "total_execution_ms": stats_raw.get("TotalExecutionTimeInMillis"),
        "query_queue_ms": stats_raw.get("QueryQueueTimeInMillis"),
        "query_planning_ms": stats_raw.get("QueryPlanningTimeInMillis"),
    }

    headers: list[str] = []
    rows: list[list[str]] = []
    pager = ATHENA.get_paginator("get_query_results")
    for page in pager.paginate(QueryExecutionId=qid):
        for row in page["ResultSet"]["Rows"]:
            cells = [c.get("VarCharValue", "") for c in row["Data"]]
            if not headers:
                headers = cells
                continue
            rows.append(cells)
            if len(rows) >= DEFAULT_RESULT_ROW_LIMIT:
                return qid, headers, rows, stats
    return qid, headers, rows, stats
