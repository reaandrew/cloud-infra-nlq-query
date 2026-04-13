"""
NLQ HTTP API Lambda — backs POST /nlq on the API Gateway v2 HTTP API.

Mirrors scripts/nlq.py but takes a JSON event from API Gateway and returns
a structured JSON response. The retrieval, prompting, validation, and
Athena execution logic is intentionally kept identical to the CLI so the
two stay in sync.

Environment variables (set by terraform):
  GLUE_DATABASE         e.g. "cinq"
  ICEBERG_VIEW          e.g. "operational_live"
  EMBED_MODEL_ID        e.g. "amazon.titan-embed-text-v2:0"
  CHAT_MODEL_ID         e.g. "anthropic.claude-sonnet-4-6"
  EMBED_DIMENSIONS      e.g. "1024"
  SCHEMAS_VECTOR_BUCKET e.g. "cinq-schemas-vectors"
  SCHEMAS_VECTOR_INDEX  e.g. "cinq-schemas-index"
  ATHENA_RESULTS_BUCKET e.g. "cloud-infra-nlq-query-athena-results"
  ATHENA_WORKGROUP      e.g. "primary"

Enriched schema docs are bundled into the deployment package under
./enriched_schemas/<resource_type>.md and read from disk at request time.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config

log = logging.getLogger()
log.setLevel(logging.INFO)

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

# Enriched schemas live next to handler.py in the deployment package
SCHEMAS_DIR = Path(__file__).resolve().parent / "enriched_schemas"

DEFAULT_TOP_K = 5
DEFAULT_MAX_OUTPUT_TOKENS = 1500
DEFAULT_RESULT_ROW_LIMIT = 100
DEFAULT_ATHENA_TIMEOUT = 60  # seconds
DEFAULT_QUESTION_MAX_CHARS = 2000

# --- AWS clients (initialised once per warm Lambda) ---
_BOTO_CFG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"},
    read_timeout=60,
)
BEDROCK = boto3.client("bedrock-runtime", config=_BOTO_CFG)
S3VECTORS = boto3.client("s3vectors", config=_BOTO_CFG)
ATHENA = boto3.client("athena", config=_BOTO_CFG)

# --- regex for SQL safety ---
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


# --- core helpers ---


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


def generate_sql(system_prompt: str, question: str, max_tokens: int) -> str:
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


def run_athena(sql: str, timeout_s: int) -> tuple[str, list[str], list[list[str]]]:
    qid = ATHENA.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
        WorkGroup=ATHENA_WORKGROUP,
    )["QueryExecutionId"]
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        s = ATHENA.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        state = s["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            raise RuntimeError(
                f"athena query {qid} {state}: {s.get('StateChangeReason', '<no reason>')}"
            )
        time.sleep(1.0)
    else:
        raise RuntimeError(f"athena query {qid} timed out after {timeout_s}s")

    # Fetch all rows up to the row limit
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
                return qid, headers, rows
    return qid, headers, rows


# --- HTTP API event handling ---


def _resp(status: int, body: dict[str, Any]) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
        },
        "body": json.dumps(body, default=str),
    }


def _parse_event(event: dict) -> dict:
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    if not raw_body:
        return {}
    try:
        return json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON body: {exc}")


def handler(event, context):
    timings: dict[str, float] = {}
    t0 = time.time()

    try:
        payload = _parse_event(event)
    except ValueError as exc:
        return _resp(400, {"error": str(exc)})

    question = (payload.get("question") or "").strip()
    if not question:
        return _resp(400, {"error": "missing required field: question"})
    if len(question) > DEFAULT_QUESTION_MAX_CHARS:
        return _resp(400, {"error": f"question exceeds {DEFAULT_QUESTION_MAX_CHARS} chars"})

    top_k = int(payload.get("top_k") or DEFAULT_TOP_K)
    if top_k < 1 or top_k > 25:
        return _resp(400, {"error": "top_k must be between 1 and 25"})
    dry_run = bool(payload.get("dry_run", False))

    log.info("nlq request: chars=%d top_k=%d dry_run=%s", len(question), top_k, dry_run)

    # 1. embed
    t = time.time()
    try:
        qvec = embed_question(question)
    except Exception as exc:
        log.exception("embed failed")
        return _resp(502, {"error": "embedding failed", "detail": str(exc)})
    timings["embed_ms"] = round((time.time() - t) * 1000, 1)

    # 2. retrieve
    t = time.time()
    try:
        matches = retrieve_schemas(qvec, top_k)
    except Exception as exc:
        log.exception("vector retrieval failed")
        return _resp(502, {"error": "vector retrieval failed", "detail": str(exc)})
    timings["retrieve_ms"] = round((time.time() - t) * 1000, 1)
    if not matches:
        return _resp(404, {"error": "no schema matches in vector index"})

    retrieved_schemas = []
    schema_blocks = []
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
    schemas_text = "\n\n---\n\n".join(schema_blocks)

    # 3. Claude
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        view=FQ_VIEW,
        schemas=schemas_text,
        row_limit=DEFAULT_RESULT_ROW_LIMIT,
    )
    t = time.time()
    try:
        raw_response = generate_sql(system_prompt, question, DEFAULT_MAX_OUTPUT_TOKENS)
    except Exception as exc:
        log.exception("Claude inference failed")
        return _resp(502, {"error": "model inference failed", "detail": str(exc)})
    timings["generate_ms"] = round((time.time() - t) * 1000, 1)

    try:
        sql = extract_sql(raw_response)
    except ValueError as exc:
        return _resp(502, {
            "error": "model did not return SQL",
            "detail": str(exc),
            "raw_response": raw_response,
            "retrieved_schemas": retrieved_schemas,
            "timings": timings,
        })

    try:
        validate_select_only(sql)
    except ValueError as exc:
        return _resp(400, {
            "error": "rejected SQL",
            "detail": str(exc),
            "sql": sql,
            "retrieved_schemas": retrieved_schemas,
            "timings": timings,
        })

    if dry_run:
        timings["total_ms"] = round((time.time() - t0) * 1000, 1)
        return _resp(200, {
            "question": question,
            "sql": sql,
            "retrieved_schemas": retrieved_schemas,
            "rows": [],
            "row_count": 0,
            "athena_query_id": None,
            "dry_run": True,
            "timings": timings,
        })

    # 4. Athena
    t = time.time()
    try:
        qid, headers, rows = run_athena(sql, DEFAULT_ATHENA_TIMEOUT)
    except RuntimeError as exc:
        timings["athena_ms"] = round((time.time() - t) * 1000, 1)
        timings["total_ms"] = round((time.time() - t0) * 1000, 1)
        return _resp(502, {
            "error": "athena execution failed",
            "detail": str(exc),
            "sql": sql,
            "retrieved_schemas": retrieved_schemas,
            "timings": timings,
        })
    timings["athena_ms"] = round((time.time() - t) * 1000, 1)
    timings["total_ms"] = round((time.time() - t0) * 1000, 1)

    structured_rows = [dict(zip(headers, r)) for r in rows]

    return _resp(200, {
        "question": question,
        "sql": sql,
        "retrieved_schemas": retrieved_schemas,
        "columns": headers,
        "rows": structured_rows,
        "row_count": len(structured_rows),
        "athena_query_id": qid,
        "timings": timings,
    })
