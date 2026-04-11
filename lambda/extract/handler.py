"""
Extract Lambda: takes an SQS batch of S3:ObjectCreated events for AWS Config
snapshot files in cinq-config-mock, flattens each snapshot's
configurationItems into rows, and appends them to the cinq.operational
Iceberg table.

Write strategy:
  1. Flatten all SQS records in the batch into a single pyarrow Table.
  2. Write it as ONE Parquet file to s3://<operational>/_staging/<invocation>/.
  3. Register that path as an external Glue table `cinq.extract_staging_<id>`.
  4. Fire an Athena `INSERT INTO cinq.operational SELECT ... FROM
     cinq.extract_staging_<id>` and wait for it to complete.
  5. Drop the staging Glue table and delete the Parquet file.

This bypasses `wr.athena.to_iceberg`, which in awswrangler 3.14 fails against
this table with `ICEBERG_TOO_MANY_OPEN_PARTITIONS` even for tiny inputs. Doing
the same steps manually with a single known-good Parquet file keeps Athena's
Iceberg INSERT happy.

Concurrency control is upstream: SQS batches (25 files / 60s window) + reserved
Lambda concurrency (5) cap the number of simultaneous Iceberg commits so we
stay below Glue's optimistic-concurrency retry threshold.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger()
log.setLevel(logging.INFO)

S3 = boto3.client("s3")
ATHENA = boto3.client("athena")
GLUE = boto3.client("glue")

DATABASE = os.environ["GLUE_DATABASE"]
TABLE = os.environ["ICEBERG_TABLE"]
OPERATIONAL_BUCKET = os.environ["OPERATIONAL_BUCKET"]
ATHENA_RESULTS_BUCKET = os.environ["ATHENA_RESULTS_BUCKET"]

STAGING_PREFIX = "_staging"
ATHENA_OUTPUT = f"s3://{ATHENA_RESULTS_BUCKET}/extract/"

# Parquet schema matches the Iceberg table exactly. Keep these column names
# and types in lockstep with terraform/app/athena/iceberg_table.sql.
PARQUET_SCHEMA = pa.schema([
    pa.field("account_id", pa.string()),
    pa.field("arn", pa.string()),
    pa.field("resource_type", pa.string()),
    pa.field("resource_id", pa.string()),
    pa.field("resource_name", pa.string()),
    pa.field("aws_region", pa.string()),
    pa.field("availability_zone", pa.string()),
    pa.field("status", pa.string()),
    pa.field("captured_at", pa.timestamp("us", tz="UTC")),
    pa.field("created_at", pa.timestamp("us", tz="UTC")),
    pa.field("state_id", pa.string()),
    pa.field("state_hash", pa.string()),
    pa.field("tags", pa.string()),
    pa.field("relationships", pa.string()),
    pa.field("configuration", pa.string()),
    pa.field("supplementary_configuration", pa.string()),
    pa.field("last_seen_at", pa.timestamp("us", tz="UTC")),
    pa.field("source_key", pa.string()),
])

# Glue column types mirroring the Iceberg table for the staging external table
STAGING_GLUE_COLUMNS = [
    {"Name": "account_id", "Type": "string"},
    {"Name": "arn", "Type": "string"},
    {"Name": "resource_type", "Type": "string"},
    {"Name": "resource_id", "Type": "string"},
    {"Name": "resource_name", "Type": "string"},
    {"Name": "aws_region", "Type": "string"},
    {"Name": "availability_zone", "Type": "string"},
    {"Name": "status", "Type": "string"},
    {"Name": "captured_at", "Type": "timestamp"},
    {"Name": "created_at", "Type": "timestamp"},
    {"Name": "state_id", "Type": "string"},
    {"Name": "state_hash", "Type": "string"},
    {"Name": "tags", "Type": "string"},
    {"Name": "relationships", "Type": "string"},
    {"Name": "configuration", "Type": "string"},
    {"Name": "supplementary_configuration", "Type": "string"},
    {"Name": "last_seen_at", "Type": "timestamp"},
    {"Name": "source_key", "Type": "string"},
]


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, "", "null"):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _json_or_null(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), default=str)


def _download_and_decompress(bucket: str, key: str) -> bytes:
    obj = S3.get_object(Bucket=bucket, Key=key)
    return gzip.decompress(obj["Body"].read())


def _flatten_snapshot(body: bytes, source_key: str, ingest_ts: datetime) -> list[dict]:
    doc = json.loads(body)
    items = doc.get("configurationItems") or []
    rows: list[dict] = []
    for item in items:
        account_id = item.get("awsAccountId")
        arn = item.get("ARN")
        if not account_id or not arn:
            continue
        rows.append({
            "account_id": account_id,
            "arn": arn,
            "resource_type": item.get("resourceType"),
            "resource_id": item.get("resourceId"),
            "resource_name": item.get("resourceName"),
            "aws_region": item.get("awsRegion"),
            "availability_zone": item.get("availabilityZone"),
            "status": item.get("configurationItemStatus"),
            "captured_at": _parse_ts(item.get("configurationItemCaptureTime")),
            "created_at": _parse_ts(item.get("resourceCreationTime")),
            "state_id": str(item.get("configurationStateId"))
                if item.get("configurationStateId") is not None else None,
            "state_hash": item.get("configurationStateMd5Hash"),
            "tags": _json_or_null(item.get("tags")),
            "relationships": _json_or_null(item.get("relationships")),
            "configuration": _json_or_null(item.get("configuration")),
            "supplementary_configuration": _json_or_null(item.get("supplementaryConfiguration")),
            "last_seen_at": ingest_ts,
            "source_key": source_key,
        })
    return rows


def _build_arrow_table(rows: list[dict]) -> pa.Table:
    columns: dict[str, list] = {f.name: [] for f in PARQUET_SCHEMA}
    for row in rows:
        for name in columns:
            columns[name].append(row.get(name))
    return pa.table(columns, schema=PARQUET_SCHEMA)


def _write_staging_parquet(table: pa.Table, staging_key: str) -> None:
    import io
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="snappy",
        use_dictionary=True,
        write_statistics=True,
    )
    buf.seek(0)
    S3.put_object(
        Bucket=OPERATIONAL_BUCKET,
        Key=staging_key,
        Body=buf.read(),
        ContentType="application/vnd.apache.parquet",
    )


def _create_staging_table(glue_table: str, staging_prefix_uri: str) -> None:
    GLUE.create_table(
        DatabaseName=DATABASE,
        TableInput={
            "Name": glue_table,
            "TableType": "EXTERNAL_TABLE",
            "Parameters": {
                "EXTERNAL": "TRUE",
                "classification": "parquet",
            },
            "StorageDescriptor": {
                "Columns": STAGING_GLUE_COLUMNS,
                "Location": staging_prefix_uri,
                "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
                "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
                "SerdeInfo": {
                    "SerializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
                    "Parameters": {"serialization.format": "1"},
                },
                "Compressed": True,
                "StoredAsSubDirectories": False,
            },
        },
    )


def _drop_staging_table(glue_table: str) -> None:
    try:
        GLUE.delete_table(DatabaseName=DATABASE, Name=glue_table)
    except GLUE.exceptions.EntityNotFoundException:
        pass


def _delete_staging_files(staging_prefix: str) -> None:
    resp = S3.list_objects_v2(Bucket=OPERATIONAL_BUCKET, Prefix=staging_prefix)
    objs = [{"Key": o["Key"]} for o in resp.get("Contents") or []]
    if objs:
        S3.delete_objects(Bucket=OPERATIONAL_BUCKET, Delete={"Objects": objs})


def _run_athena(sql: str, label: str) -> None:
    log.info("athena: %s", label)
    qid = ATHENA.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
    )["QueryExecutionId"]
    deadline = time.time() + 240
    while time.time() < deadline:
        state = ATHENA.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        phase = state["State"]
        if phase == "SUCCEEDED":
            log.info("athena: %s (%s) ok", label, qid)
            return
        if phase in ("FAILED", "CANCELLED"):
            reason = state.get("StateChangeReason", "<no reason>")
            raise RuntimeError(f"athena {label} ({qid}) {phase}: {reason}")
        time.sleep(2)
    raise RuntimeError(f"athena {label} ({qid}) timed out")


def handler(event, context):
    records = event.get("Records") or []
    log.info("extract batch received: %d sqs messages", len(records))
    ingest_ts = datetime.now(timezone.utc)

    all_rows: list[dict] = []
    successful_message_ids: list[str] = []
    batch_item_failures: list[dict[str, str]] = []

    for record in records:
        message_id = record["messageId"]
        try:
            body = json.loads(record["body"])
            s3_records = body.get("Records") or []
            if not s3_records:
                log.warning("message %s has no S3 Records — skipping", message_id)
                successful_message_ids.append(message_id)
                continue
            for s3_evt in s3_records:
                bucket = s3_evt["s3"]["bucket"]["name"]
                key = urllib.parse.unquote_plus(s3_evt["s3"]["object"]["key"])
                if not key.endswith(".json.gz"):
                    log.info("skipping non-snapshot key %s", key)
                    continue
                raw = _download_and_decompress(bucket, key)
                rows = _flatten_snapshot(raw, f"s3://{bucket}/{key}", ingest_ts)
                log.info("flattened %d rows from %s", len(rows), key)
                all_rows.extend(rows)
            successful_message_ids.append(message_id)
        except Exception as exc:
            log.exception("failed to process message %s: %s", message_id, exc)
            batch_item_failures.append({"itemIdentifier": message_id})

    if not all_rows:
        log.info("no rows to write (batch empty after filtering)")
        return {"batchItemFailures": batch_item_failures}

    # Sort by account_id (partition column) so Athena's Iceberg writer streams
    # per-partition sequentially instead of fanning out.
    all_rows.sort(key=lambda r: (r["account_id"] or "", r["arn"] or ""))

    arrow_table = _build_arrow_table(all_rows)
    batch_uuid = uuid.uuid4().hex
    staging_dir = f"{STAGING_PREFIX}/{batch_uuid}"
    staging_key = f"{staging_dir}/data.parquet"
    staging_uri = f"s3://{OPERATIONAL_BUCKET}/{staging_dir}/"
    glue_staging_table = f"extract_staging_{batch_uuid}"

    log.info(
        "writing %d rows to %s.%s (accounts=%d, types=%d, staging=%s)",
        len(all_rows),
        DATABASE,
        TABLE,
        len({r["account_id"] for r in all_rows}),
        len({r["resource_type"] for r in all_rows}),
        staging_uri,
    )

    try:
        _write_staging_parquet(arrow_table, staging_key)
        _create_staging_table(glue_staging_table, staging_uri)
        cols = ", ".join(f'"{f.name}"' for f in PARQUET_SCHEMA)
        insert_sql = (
            f'INSERT INTO "{DATABASE}"."{TABLE}" ({cols}) '
            f'SELECT {cols} FROM "{DATABASE}"."{glue_staging_table}"'
        )
        _run_athena(insert_sql, f"insert into {TABLE}")
    except Exception:
        log.exception("iceberg append failed — marking successful messages as failed")
        batch_item_failures.extend(
            {"itemIdentifier": mid} for mid in successful_message_ids
        )
        return {"batchItemFailures": batch_item_failures}
    finally:
        _drop_staging_table(glue_staging_table)
        _delete_staging_files(staging_dir)

    log.info("append committed: %d rows landed in %s.%s", len(all_rows), DATABASE, TABLE)
    return {"batchItemFailures": batch_item_failures}
