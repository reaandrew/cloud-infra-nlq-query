"""
NLQ async worker Lambda — runs the slow stages and writes progress to S3.

Invoked via `InvocationType=Event` from the submit Lambda. Reads the
initial job doc the submitter wrote, then runs embed → retrieve →
generate → athena, overwriting the same S3 key after every stage
transition so the status Lambda (and therefore the SPA) can observe
real progress.

This Lambda has a longer timeout than the submit Lambda (300s) because
it is not bound by API Gateway's 29s integration cap.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from stages import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_TOP_K,
    WORKER_ATHENA_TIMEOUT,
    build_system_prompt,
    embed_question,
    extract_sql,
    format_matches,
    generate_sql,
    retrieve_schemas,
    run_athena,
    validate_select_only,
)

log = logging.getLogger()
log.setLevel(logging.INFO)

JOBS_BUCKET = os.environ["JOBS_BUCKET"]

_FAST_CFG = Config(
    retries={"max_attempts": 3, "mode": "standard"},
    read_timeout=10,
    connect_timeout=3,
)
S3 = boto3.client("s3", config=_FAST_CFG)

STAGE_NAMES = ("embed", "retrieve", "generate", "athena")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_key(job_id: str) -> str:
    return f"jobs/{job_id}.json"


def _load_doc(job_id: str) -> dict:
    obj = S3.get_object(Bucket=JOBS_BUCKET, Key=_job_key(job_id))
    return json.loads(obj["Body"].read())


def _save_doc(doc: dict) -> None:
    doc["updated_at"] = _now_iso()
    S3.put_object(
        Bucket=JOBS_BUCKET,
        Key=_job_key(doc["job_id"]),
        Body=json.dumps(doc, default=str).encode("utf-8"),
        ContentType="application/json",
        CacheControl="no-store",
    )


def _begin_stage(doc: dict, name: str) -> float:
    started = time.time()
    doc["status"] = "running"
    doc["stage"] = name
    doc["stages"][name] = {
        "status": "running",
        "started_at": _now_iso(),
    }
    _save_doc(doc)
    return started


def _end_stage(doc: dict, name: str, started_monotonic: float) -> None:
    ms = round((time.time() - started_monotonic) * 1000, 1)
    prev = doc["stages"].get(name, {})
    prev["status"] = "done"
    prev["ended_at"] = _now_iso()
    prev["ms"] = ms
    doc["stages"][name] = prev
    _save_doc(doc)


def _collect_timings(doc: dict) -> dict[str, float]:
    timings: dict[str, float] = {}
    total = 0.0
    for name in STAGE_NAMES:
        ms = doc["stages"].get(name, {}).get("ms")
        if ms is not None:
            timings[f"{name}_ms"] = ms
            total += float(ms)
    timings["total_ms"] = round(total, 1)
    return timings


def worker_handler(event, context):
    job_id = event["job_id"]
    question = event["question"]
    top_k = int(event.get("top_k") or DEFAULT_TOP_K)

    log.info("worker starting job_id=%s top_k=%d", job_id, top_k)

    try:
        doc = _load_doc(job_id)
    except ClientError as exc:
        log.exception("worker could not load job doc job_id=%s", job_id)
        raise

    doc["status"] = "running"
    _save_doc(doc)

    try:
        # 1. embed
        t = _begin_stage(doc, "embed")
        qvec = embed_question(question)
        _end_stage(doc, "embed", t)

        # 2. retrieve
        t = _begin_stage(doc, "retrieve")
        matches = retrieve_schemas(qvec, top_k)
        if not matches:
            raise RuntimeError("no schema matches in vector index")
        retrieved_schemas, schemas_text = format_matches(matches)
        _end_stage(doc, "retrieve", t)

        # 3. generate
        t = _begin_stage(doc, "generate")
        system_prompt = build_system_prompt(schemas_text)
        raw = generate_sql(system_prompt, question, DEFAULT_MAX_OUTPUT_TOKENS)
        sql = extract_sql(raw)
        validate_select_only(sql)
        _end_stage(doc, "generate", t)

        # 4. athena
        t = _begin_stage(doc, "athena")
        qid, headers, rows, athena_stats = run_athena(sql, WORKER_ATHENA_TIMEOUT)
        _end_stage(doc, "athena", t)

        structured_rows = [dict(zip(headers, r)) for r in rows]

        doc["status"] = "succeeded"
        doc["stage"] = None
        doc["result"] = {
            "question": question,
            "sql": sql,
            "retrieved_schemas": retrieved_schemas,
            "columns": headers,
            "rows": structured_rows,
            "row_count": len(structured_rows),
            "athena_query_id": qid,
            "athena_stats": athena_stats,
            "timings": _collect_timings(doc),
        }
        _save_doc(doc)
        log.info("worker succeeded job_id=%s rows=%d", job_id, len(structured_rows))

    except Exception as exc:
        log.exception("worker failed job_id=%s", job_id)
        failed_stage = doc.get("stage")
        if failed_stage and doc["stages"].get(failed_stage, {}).get("status") == "running":
            doc["stages"][failed_stage]["status"] = "failed"
            doc["stages"][failed_stage]["ended_at"] = _now_iso()
        doc["status"] = "failed"
        doc["error"] = {
            "error": type(exc).__name__,
            "detail": str(exc),
            "stage": failed_stage,
        }
        _save_doc(doc)
        raise
