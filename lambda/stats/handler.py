"""
Stats Lambda — backs the unauthenticated GET /stats/* routes on the
NLQ HTTP API. Each route runs a small Athena aggregation against
`cinq.operational_live` and returns JSON.

Routes:
  GET /stats/overview     — KPI snapshot: total resources, distinct accounts/types/regions,
                            first/last seen timestamps
  GET /stats/by-type      — top resource types by count (default 25)
  GET /stats/by-account   — top accounts by total resource count (default 25)
  GET /stats/by-region    — count per AWS region

All responses cached in the warm Lambda for `CACHE_TTL_SECONDS` (default
60s) so a refresh-spam'ing dashboard doesn't stack up Athena queries.
This is fine because the underlying data refreshes ~daily anyway.

Environment variables (set by terraform):
  GLUE_DATABASE         e.g. "cinq"
  ICEBERG_VIEW          e.g. "operational_live"
  ATHENA_RESULTS_BUCKET e.g. "cloud-infra-nlq-query-athena-results"
  ATHENA_WORKGROUP      e.g. "primary"
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3
from botocore.config import Config

log = logging.getLogger()
log.setLevel(logging.INFO)

DATABASE = os.environ["GLUE_DATABASE"]
VIEW = os.environ["ICEBERG_VIEW"]
ATHENA_RESULTS_BUCKET = os.environ["ATHENA_RESULTS_BUCKET"]
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "primary")
CACHE_TTL_SECONDS = int(os.environ.get("STATS_CACHE_TTL_SECONDS", "60"))

FQ_VIEW = f"{DATABASE}.{VIEW}"
ATHENA_OUTPUT = f"s3://{ATHENA_RESULTS_BUCKET}/stats/"

ATHENA = boto3.client(
    "athena",
    config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=60),
)

# ---- in-memory cache (warm container only) ----
_CACHE: dict[str, tuple[float, dict]] = {}


def _cached(key: str):
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < CACHE_TTL_SECONDS:
        return hit[1]
    return None


def _store(key: str, value: dict) -> dict:
    _CACHE[key] = (time.time(), value)
    return value


# ---- Athena helper ----

def _run(sql: str, timeout_s: int = 30) -> tuple[str, list[str], list[list[str]]]:
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
        time.sleep(0.5)
    else:
        raise RuntimeError(f"athena query {qid} timed out after {timeout_s}s")

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
    return qid, headers, rows


def _to_int(v: str) -> int | None:
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


# ---- queries ----

def overview() -> dict:
    cached = _cached("overview")
    if cached is not None:
        return cached
    sql = f"""
        SELECT
            COUNT(*)                            AS total_resources,
            COUNT(DISTINCT account_id)          AS distinct_accounts,
            COUNT(DISTINCT resource_type)       AS distinct_resource_types,
            COUNT(DISTINCT aws_region)          AS distinct_regions,
            CAST(MIN(last_seen_at) AS VARCHAR)  AS first_seen_at,
            CAST(MAX(last_seen_at) AS VARCHAR)  AS last_seen_at
        FROM {FQ_VIEW}
    """
    qid, headers, rows = _run(sql)
    if not rows:
        return _store("overview", {
            "total_resources": 0,
            "distinct_accounts": 0,
            "distinct_resource_types": 0,
            "distinct_regions": 0,
            "first_seen_at": None,
            "last_seen_at": None,
            "athena_query_id": qid,
        })
    row = dict(zip(headers, rows[0]))
    return _store("overview", {
        "total_resources":         _to_int(row.get("total_resources", "0")) or 0,
        "distinct_accounts":       _to_int(row.get("distinct_accounts", "0")) or 0,
        "distinct_resource_types": _to_int(row.get("distinct_resource_types", "0")) or 0,
        "distinct_regions":        _to_int(row.get("distinct_regions", "0")) or 0,
        "first_seen_at":           row.get("first_seen_at") or None,
        "last_seen_at":            row.get("last_seen_at") or None,
        "athena_query_id":         qid,
    })


def by_type(limit: int) -> dict:
    cache_key = f"by_type:{limit}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    sql = f"""
        SELECT
            resource_type,
            COUNT(*) AS resource_count
        FROM {FQ_VIEW}
        GROUP BY resource_type
        ORDER BY resource_count DESC
        LIMIT {limit}
    """
    qid, headers, rows = _run(sql)
    items = [
        {
            "resource_type": dict(zip(headers, r)).get("resource_type", ""),
            "resource_count": _to_int(dict(zip(headers, r)).get("resource_count", "0")) or 0,
        }
        for r in rows
    ]
    return _store(cache_key, {"items": items, "limit": limit, "athena_query_id": qid})


def by_account(limit: int) -> dict:
    cache_key = f"by_account:{limit}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached
    sql = f"""
        SELECT
            account_id,
            COUNT(*)                          AS resource_count,
            COUNT(DISTINCT resource_type)     AS distinct_resource_types,
            COUNT(DISTINCT aws_region)        AS distinct_regions
        FROM {FQ_VIEW}
        GROUP BY account_id
        ORDER BY resource_count DESC
        LIMIT {limit}
    """
    qid, headers, rows = _run(sql)
    items = []
    for r in rows:
        d = dict(zip(headers, r))
        items.append({
            "account_id": d.get("account_id", ""),
            "resource_count":          _to_int(d.get("resource_count", "0")) or 0,
            "distinct_resource_types": _to_int(d.get("distinct_resource_types", "0")) or 0,
            "distinct_regions":        _to_int(d.get("distinct_regions", "0")) or 0,
        })
    return _store(cache_key, {"items": items, "limit": limit, "athena_query_id": qid})


def by_region() -> dict:
    cached = _cached("by_region")
    if cached is not None:
        return cached
    sql = f"""
        SELECT
            aws_region,
            COUNT(*)                       AS resource_count,
            COUNT(DISTINCT account_id)     AS distinct_accounts,
            COUNT(DISTINCT resource_type)  AS distinct_resource_types
        FROM {FQ_VIEW}
        GROUP BY aws_region
        ORDER BY resource_count DESC
    """
    qid, headers, rows = _run(sql)
    items = []
    for r in rows:
        d = dict(zip(headers, r))
        items.append({
            "aws_region":              d.get("aws_region", ""),
            "resource_count":          _to_int(d.get("resource_count", "0")) or 0,
            "distinct_accounts":       _to_int(d.get("distinct_accounts", "0")) or 0,
            "distinct_resource_types": _to_int(d.get("distinct_resource_types", "0")) or 0,
        })
    return _store("by_region", {"items": items, "athena_query_id": qid})


# ---- HTTP wrapper ----

def _resp(status: int, body: dict[str, Any]) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": f"public, max-age={CACHE_TTL_SECONDS}",
        },
        "body": json.dumps(body, default=str),
    }


def _qs_int(event: dict, name: str, default: int, lo: int, hi: int) -> int:
    qs = event.get("queryStringParameters") or {}
    raw = qs.get(name)
    if raw is None:
        return default
    try:
        n = int(raw)
    except ValueError:
        return default
    return max(lo, min(hi, n))


def handler(event, context):
    route = event.get("rawPath", "/")
    log.info("stats request: %s", route)

    try:
        if route.endswith("/stats/overview"):
            return _resp(200, overview())
        if route.endswith("/stats/by-type"):
            limit = _qs_int(event, "limit", default=25, lo=1, hi=200)
            return _resp(200, by_type(limit))
        if route.endswith("/stats/by-account"):
            limit = _qs_int(event, "limit", default=25, lo=1, hi=500)
            return _resp(200, by_account(limit))
        if route.endswith("/stats/by-region"):
            return _resp(200, by_region())
    except RuntimeError as exc:
        log.exception("athena failed for %s", route)
        return _resp(502, {"error": "athena failed", "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        log.exception("unexpected error for %s", route)
        return _resp(500, {"error": "internal error", "detail": str(exc)})

    return _resp(404, {"error": f"unknown stats route: {route}"})
