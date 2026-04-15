"""
NLQ HTTP API Lambda — submit + status dispatch.

Two routes land on this same function via API Gateway v2:
  POST /nlq             → submit_handler
  GET  /nlq/jobs/{id}   → status_handler

Submit validates input, writes an initial progress JSON to the jobs
bucket, async-invokes the worker Lambda, and returns 202 Accepted with
a job_id. The slow work (embed → retrieve → Claude → Athena) happens
in the worker, which overwrites the same JSON doc as it progresses
through stages. The status handler is a thin S3 reader.

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
  JOBS_BUCKET           e.g. "cloud-infra-nlq-query-nlq-jobs"
  WORKER_FUNCTION_ARN   arn of the worker Lambda
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Importing stages registers the env-var-required boto3 clients on cold
# start. That cost is unavoidable for the worker; the submit path pays
# it once per warm container.
from stages import DEFAULT_QUESTION_MAX_CHARS, DEFAULT_TOP_K

log = logging.getLogger()
log.setLevel(logging.INFO)

JOBS_BUCKET = os.environ["JOBS_BUCKET"]
WORKER_FUNCTION_ARN = os.environ["WORKER_FUNCTION_ARN"]

_FAST_CFG = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    read_timeout=5,
    connect_timeout=3,
)
S3 = boto3.client("s3", config=_FAST_CFG)
LAMBDA = boto3.client("lambda", config=_FAST_CFG)

STAGE_NAMES = ("embed", "retrieve", "generate", "athena")


# --- helpers ---


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _job_key(job_id: str) -> str:
    return f"jobs/{job_id}.json"


def _put_doc(job_id: str, doc: dict) -> None:
    S3.put_object(
        Bucket=JOBS_BUCKET,
        Key=_job_key(job_id),
        Body=json.dumps(doc).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-store",
    )


def _get_doc(job_id: str) -> dict | None:
    try:
        obj = S3.get_object(Bucket=JOBS_BUCKET, Key=_job_key(job_id))
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(obj["Body"].read())


def _initial_doc(job_id: str, question: str, top_k: int) -> dict:
    now = _now_iso()
    return {
        "job_id": job_id,
        "status": "queued",
        "stage": None,
        "submitted_at": now,
        "updated_at": now,
        "question": question,
        "top_k": top_k,
        "stages": {name: {"status": "pending"} for name in STAGE_NAMES},
    }


# --- submit (POST /nlq) ---


def submit_handler(event, context) -> dict:
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

    job_id = uuid.uuid4().hex
    doc = _initial_doc(job_id, question, top_k)

    try:
        _put_doc(job_id, doc)
    except Exception as exc:
        log.exception("failed to write initial job doc")
        return _resp(502, {"error": "failed to queue job", "detail": str(exc)})

    try:
        LAMBDA.invoke(
            FunctionName=WORKER_FUNCTION_ARN,
            InvocationType="Event",
            Payload=json.dumps({
                "job_id": job_id,
                "question": question,
                "top_k": top_k,
            }).encode("utf-8"),
        )
    except Exception as exc:
        log.exception("failed to async-invoke worker")
        # Mark the doc failed so the client sees a clean error instead of
        # a job that sits in "queued" forever.
        doc["status"] = "failed"
        doc["error"] = {"error": "worker_invoke_failed", "detail": str(exc)}
        _put_doc(job_id, doc)
        return _resp(502, {"error": "failed to dispatch worker", "detail": str(exc)})

    log.info("submitted job_id=%s in %.0fms", job_id, (time.time() - t0) * 1000)
    return _resp(202, {
        "job_id": job_id,
        "status_url": f"/nlq/jobs/{job_id}",
    })


# --- status (GET /nlq/jobs/{job_id}) ---


def status_handler(event, context) -> dict:
    path_params = event.get("pathParameters") or {}
    job_id = path_params.get("job_id") or path_params.get("id")
    if not job_id:
        return _resp(400, {"error": "missing path parameter: job_id"})

    # Defensive sanity check — path parameters shouldn't contain slashes
    if "/" in job_id or ".." in job_id:
        return _resp(400, {"error": "invalid job_id"})

    try:
        doc = _get_doc(job_id)
    except Exception as exc:
        log.exception("failed to read job doc")
        return _resp(502, {"error": "failed to read job", "detail": str(exc)})

    if doc is None:
        return _resp(404, {"error": "job not found"})
    return _resp(200, doc)


# --- router ---


def handler(event, context):
    http = (event.get("requestContext") or {}).get("http") or {}
    method = http.get("method", "")
    route_key = event.get("routeKey", "")

    # Route on the normalised route key first (most explicit), falling
    # back to method + raw path.
    if route_key == "POST /nlq" or (method == "POST" and event.get("rawPath") == "/nlq"):
        return submit_handler(event, context)
    if route_key.startswith("GET /nlq/jobs/") or (
        method == "GET" and (event.get("rawPath") or "").startswith("/nlq/jobs/")
    ):
        return status_handler(event, context)
    return _resp(404, {"error": "not found", "route": route_key or method})
