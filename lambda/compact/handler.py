"""
Nightly compaction + TTL sweep for the cinq.operational Iceberg table.

Runs a sequence of Athena statements:
  1. MERGE INTO — dedupe to latest row per (account_id, arn)
  2. DELETE     — hard TTL, drop rows older than `TTL_HARD_DELETE_DAYS`
  3. OPTIMIZE   — compact small data files produced by the append-only extract Lambda
  4. VACUUM     — expire old Iceberg snapshots so metadata/storage stays bounded

Fails fast on any error. No partial work.
"""

from __future__ import annotations

import logging
import os
import time

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

ATHENA = boto3.client("athena")

DATABASE = os.environ["GLUE_DATABASE"]
TABLE = os.environ["ICEBERG_TABLE"]
RESULTS_BUCKET = os.environ["ATHENA_RESULTS_BUCKET"]
TTL_HARD_DELETE_DAYS = int(os.environ.get("TTL_HARD_DELETE_DAYS", "7"))

FQN = f"{DATABASE}.{TABLE}"

MERGE_SQL = f"""
MERGE INTO {FQN} AS tgt
USING (
  SELECT * FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY account_id, arn ORDER BY last_seen_at DESC) AS rn
    FROM {FQN}
  )
  WHERE rn = 1
) AS src
ON tgt.account_id = src.account_id AND tgt.arn = src.arn
WHEN MATCHED AND tgt.last_seen_at < src.last_seen_at THEN UPDATE SET
  resource_type = src.resource_type,
  resource_id = src.resource_id,
  resource_name = src.resource_name,
  aws_region = src.aws_region,
  availability_zone = src.availability_zone,
  status = src.status,
  captured_at = src.captured_at,
  created_at = src.created_at,
  state_id = src.state_id,
  state_hash = src.state_hash,
  tags = src.tags,
  relationships = src.relationships,
  configuration = src.configuration,
  supplementary_configuration = src.supplementary_configuration,
  last_seen_at = src.last_seen_at,
  source_key = src.source_key
WHEN NOT MATCHED THEN INSERT (
  account_id, arn, resource_type, resource_id, resource_name, aws_region,
  availability_zone, status, captured_at, created_at, state_id, state_hash,
  tags, relationships, configuration, supplementary_configuration,
  last_seen_at, source_key
) VALUES (
  src.account_id, src.arn, src.resource_type, src.resource_id, src.resource_name, src.aws_region,
  src.availability_zone, src.status, src.captured_at, src.created_at, src.state_id, src.state_hash,
  src.tags, src.relationships, src.configuration, src.supplementary_configuration,
  src.last_seen_at, src.source_key
)
""".strip()

DELETE_SQL = f"""
DELETE FROM {FQN}
WHERE last_seen_at < current_timestamp - interval '{TTL_HARD_DELETE_DAYS}' day
""".strip()

OPTIMIZE_SQL = f"OPTIMIZE {FQN} REWRITE DATA USING BIN_PACK"

VACUUM_SQL = f"VACUUM {FQN}"


def _run(sql: str, label: str) -> None:
    log.info("athena: starting %s", label)
    qid = ATHENA.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": f"s3://{RESULTS_BUCKET}/compact/"},
    )["QueryExecutionId"]

    deadline = time.time() + 800  # stay under 15 min Lambda timeout
    while time.time() < deadline:
        state = ATHENA.get_query_execution(QueryExecutionId=qid)["QueryExecution"][
            "Status"
        ]
        phase = state["State"]
        if phase == "SUCCEEDED":
            log.info("athena: %s (%s) SUCCEEDED", label, qid)
            return
        if phase in ("FAILED", "CANCELLED"):
            reason = state.get("StateChangeReason", "<no reason>")
            raise RuntimeError(f"athena {label} ({qid}) {phase}: {reason}")
        time.sleep(3)

    raise RuntimeError(f"athena {label} ({qid}) timed out")


def handler(event, context):
    log.info(
        "compact start: database=%s table=%s hard_ttl_days=%s",
        DATABASE,
        TABLE,
        TTL_HARD_DELETE_DAYS,
    )
    _run(MERGE_SQL, "MERGE")
    _run(DELETE_SQL, "DELETE")
    _run(OPTIMIZE_SQL, "OPTIMIZE")
    _run(VACUUM_SQL, "VACUUM")
    log.info("compact done")
    return {"status": "ok"}
