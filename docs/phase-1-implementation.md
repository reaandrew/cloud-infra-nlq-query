# Phase 1 — Ingest pipeline: AWS Config JSON → Iceberg on S3

_Status: delivered and verified end-to-end at 500 mock accounts (2026-04-11)._

## What phase 1 delivers

An auto-triggered pipeline that takes gzipped AWS Config `ConfigSnapshot`
files landing in `cinq-config-mock` and lands the flattened
`configurationItems` as rows in an Iceberg table `cinq.operational`
(stored in `cinq-config`, registered in the AWS Glue Data Catalog,
queryable via Athena).

Downstream consumers (Athena, the future NLQ service) query a freshness
view `cinq.operational_live` that filters out rows older than 24 hours.
A nightly compaction Lambda runs `MERGE INTO` / `DELETE` / `OPTIMIZE` /
`VACUUM` against the table so the physical shape stays healthy and
deleted-in-account resources fall out within the TTL window.

**Out of scope for phase 1**: real AWS Config ingestion, Lake Formation
grants, KMS-encrypted storage, VPC-attached Lambdas, cross-account
aggregation, DLQ replay tooling, the NLQ query layer itself.

## Architecture

```
cinq-config-mock (S3)
    │  S3:ObjectCreated on *.json.gz under ConfigSnapshot/
    ▼
cinq-extract-queue (SQS, batch 25, 60s window, DLQ after 3 retries)
    │
    ▼
extract Lambda (Python 3.12 zip + AWS SDK for pandas managed layer)
    │  1. flatten configurationItems → pyarrow.Table
    │  2. write one Parquet file to s3://cinq-config/_staging/<uuid>/data.parquet
    │  3. register transient external Glue table
    │  4. Athena INSERT INTO cinq.operational SELECT *
    │  5. drop staging table + delete staging file
    ▼
cinq-config (S3) ── Iceberg table cinq.operational ── Glue Data Catalog
                                              ▲
                                              │  EventBridge daily 03:00 UTC
                                              │
                            compact Lambda (Python 3.12 zip, boto3 only)
                              MERGE INTO → DELETE → OPTIMIZE → VACUUM
                                              │
                                              ▼
                            Athena view cinq.operational_live
                                 (24h freshness filter)
                                 ↓ consumers query this
```

## Design decisions

Validated by a design review before build. The non-obvious ones:

### SQS batching between S3 and the extract Lambda

S3 → Lambda direct would fan out one Lambda invocation per snapshot file.
At 500 accounts per sync that means 500 concurrent Iceberg commits, which
will overwhelm Glue's optimistic-concurrency mechanism (practitioner
experience puts the pain point around ~50 concurrent writers). Retries
cascade into a storm that gets worse the bigger the metadata file grows.

Fix: insert SQS between S3 and the extract Lambda. Event source mapping
batches **up to 25 records per invocation with a 60s window**, and the
Lambda's **reserved concurrency is capped at 5**. This converts "500 tiny
commits" into "~20 fat commits with ≤5 in flight" and caps the worst case
at 5 concurrent writers against Glue. Each extract invocation does
**one** Iceberg commit for the whole batch. Trade-off: +60s worst-case
latency from upload to queryable.

### Zip-packaged Lambda + AWS SDK for pandas managed layer

ECR isn't usable in this account, so container-image Lambdas are off the
table. pyarrow + pandas + boto3 + awswrangler collectively weigh ~250MB,
which doesn't fit in a single zip layer. The cleanest path: reference
AWS's publicly-maintained layer
`arn:aws:lambda:eu-west-2:336392948345:layer:AWSSDKPandas-Python312:20`,
which bundles all of the above. No custom layer to build or maintain.

### Manual staging-table write pattern, not `wr.athena.to_iceberg`

`wr.athena.to_iceberg` would have been the obvious one-liner, but in
awswrangler 3.14 it triggers Athena's
`ICEBERG_TOO_MANY_OPEN_PARTITIONS` error against this table even with
54 rows (see Issue 5 below). Replacing it with a hand-rolled version of
the same pattern (write one Parquet file with pyarrow → transient
external Glue table → `INSERT INTO … SELECT …` → drop staging) avoids
whatever awswrangler does internally that trips the Athena writer.

### Append-only extracts + nightly MERGE compaction

Running `MERGE INTO` from the extract Lambda would have given immediate
consistency, but every Lambda would round-trip through Athena and incur
commit contention on the Iceberg table. Instead:

- **extract Lambda** is append-only. Duplicates and stale rows are
  tolerated physically; the read-time view filters them out.
- **compact Lambda** runs `MERGE INTO` nightly to collapse the table to
  one row per `(account_id, arn)`, then `DELETE` for hard TTL, then
  `OPTIMIZE` to compact small files, then `VACUUM` to expire old
  snapshots. This is the standard Iceberg streaming-ingestion pattern.

The freshness view `cinq.operational_live` is a trivial
`WHERE last_seen_at > current_timestamp - interval '24' hour` — no
`ROW_NUMBER()` deduplication needed because the physical table is
already deduped after each compaction.

### Opaque JSON columns for nested AWS Config payloads

AWS Config has ~400 resource types with incompatible nested shapes for
`configuration` / `supplementaryConfiguration` / `relationships` / `tags`.
Trying to flatten these fights the data: union-based schemas explode in
size, type inference is unstable, and every new resource type forces
schema evolution. We store them as `VARCHAR` columns holding JSON
strings — downstream queries can still use Athena's `json_extract_scalar`
and friends when needed.

### Asymmetric S3 lifecycle rules

- `cinq-config-mock` — 14-day current / 1-day noncurrent lifecycle rule.
  Source data, safe to age out.
- `cinq-config` — **no lifecycle rule**. This bucket holds the Iceberg
  table's data files and metadata (JSON + Avro manifests). File cleanup
  is Iceberg's job, performed by the compact Lambda via `VACUUM` /
  `expire_snapshots`. A blanket lifecycle rule would corrupt the table
  by deleting files still referenced by live snapshots.
- `cloud-infra-nlq-query-athena-results` — 7-day lifecycle rule. Athena
  query staging is disposable.

## Components built

### Terraform (`terraform/app/`)

| File | Purpose |
|---|---|
| `main.tf` (existing, extended) | Provider, backend, VPC/subnets/IGW/route table, S3 buckets (`cinq-config`, `cinq-config-mock`, `<app>-athena-results`), lifecycle rules |
| `sqs.tf` | `cinq-extract-queue`, `cinq-extract-dlq`, redrive policy (maxReceiveCount=3), queue policy allowing `s3.amazonaws.com` to SendMessage, S3 bucket notification wiring |
| `glue.tf` | `aws_glue_catalog_database.cinq` |
| `athena.tf` | `null_resource` drivers that run `athena/iceberg_table.sql` + `athena/operational_live.sql` via `athena/run_ddl.sh`, with triggers on `sha256(ddl_file)` so DDL changes force re-apply |
| `lambda_extract.tf` | IAM role + inline policy, zip Lambda, AWS SDK for pandas layer ARN, SQS event source mapping (batch 25 / 60s / ReportBatchItemFailures / MaximumConcurrency=5), CloudWatch Log Group |
| `lambda_compact.tf` | IAM role, zip Lambda, EventBridge daily schedule rule, Lambda permission |
| `variables.tf` (extended) | TTL windows, batch sizes, concurrency, compact cron, retention, SDK pandas layer ARN |
| `outputs.tf` | Queue URLs, bucket names, Glue database, Iceberg table + view names — consumed by `scripts/test_pipeline.sh` |

Athena DDL assets live under `terraform/app/athena/`:
- `iceberg_table.sql` — `CREATE TABLE IF NOT EXISTS cinq.operational … TBLPROPERTIES('table_type'='ICEBERG', 'format'='parquet', 'write_compression'='zstd')`
- `operational_live.sql` — `CREATE OR REPLACE VIEW cinq.operational_live AS SELECT * FROM cinq.operational WHERE last_seen_at > current_timestamp - interval '${ttl_hours}' hour`
- `run_ddl.sh` — reusable `aws athena start-query-execution` + poller

Both SQL files are templated via `templatefile()` so database name, table
name, bucket, and TTL hours come from terraform variables.

### Lambda source (`lambda/`)

**`lambda/extract/handler.py`** — SQS batch handler:
1. Iterates SQS records, parses the wrapped S3 event, downloads and
   gunzips each `.json.gz`.
2. Flattens `configurationItems` to rows with hard-typed columns
   (scalars typed in pyarrow, nested payloads JSON-stringified).
3. Sorts rows by `account_id` (partition column) to keep Athena's
   Iceberg writer streaming per-partition.
4. Builds one `pyarrow.Table`, writes one Parquet file (snappy, with
   dictionary encoding and stats) to
   `s3://cinq-config/_staging/<batch-uuid>/data.parquet`.
5. Creates a transient Glue external table
   `cinq.extract_staging_<batch-uuid>` via `glue:CreateTable`.
6. Runs `INSERT INTO cinq.operational (cols…) SELECT cols… FROM
   cinq.extract_staging_<batch-uuid>` via Athena.
7. In a `finally` block: drops the Glue table and deletes the Parquet
   file.
8. On per-record failure, adds the message ID to `batchItemFailures` so
   only that record gets redriven.

**`lambda/compact/handler.py`** — nightly compaction (pure stdlib + boto3):
1. `MERGE INTO cinq.operational tgt USING (SELECT * FROM (ROW_NUMBER()
   … WHERE rn=1)) src ON (account_id, arn) WHEN MATCHED AND tgt.last_seen_at
   < src.last_seen_at THEN UPDATE SET … WHEN NOT MATCHED THEN INSERT …` —
   collapses duplicates to latest.
2. `DELETE FROM cinq.operational WHERE last_seen_at < current_timestamp
   - interval '7' day` — hard TTL sweep.
3. `OPTIMIZE cinq.operational REWRITE DATA USING BIN_PACK` — compact
   small files.
4. `VACUUM cinq.operational` — expire old Iceberg snapshots so storage
   stays bounded.

### Makefile additions

| Target | Purpose |
|---|---|
| `package-extract` / `package-compact` | Ensure `build/` exists for the `archive_file` data sources to populate |
| `deploy` (modified) | Now depends on the package targets so a single `make deploy` packages + applies |
| `test-pipeline` | `make generate-mock` → `scripts/test_pipeline.sh` |

Overridable knobs: `PROFILE`, `ACCOUNTS`, `VPCS`, `SEED`, `MOCK_BUCKET`,
`CONFIG_BUCKET`, `AWS_REGION`, `TEST_TIMEOUT`.

### Test driver (`scripts/test_pipeline.sh`)

1. Reads outputs (`extract_queue_url`, `glue_database`,
   `iceberg_table`, `iceberg_live_view`, `athena_results_bucket`)
   directly from terraform state — no AWS describe-and-guess.
2. Polls SQS `ApproximateNumberOfMessages` +
   `ApproximateNumberOfMessagesNotVisible` +
   `ApproximateNumberOfMessagesDelayed` until all three reach 0.
3. Runs three Athena queries against the live view:
   - snapshot count via `"cinq"."operational$snapshots"` (Iceberg
     metadata table, deterministic)
   - row/account/type totals
   - top 10 resource types

## Configuration defaults

| Setting | Default | Rationale |
|---|---|---|
| extract Lambda memory | 2 GB | pandas peak memory at ~1M-row batches |
| extract Lambda timeout | 5 min | 25-file batch × production-size (190MB) files + Athena INSERT |
| extract reserved concurrency | 5 | Caps concurrent Iceberg writers |
| SQS batch size | 25 | 25× fewer commits than per-file triggering |
| SQS batch window | 60s | Upper bound on "upload → queryable" latency |
| compact Lambda memory | 1 GB | It only polls Athena; no data in-proc |
| compact Lambda timeout | 15 min | MERGE on 25M rows with headroom |
| compact schedule | daily 03:00 UTC | Off-peak |
| TTL view window | 24 h | Matches the stated requirement |
| TTL hard delete | 7 d | Audit/recovery window |
| Mock bucket lifecycle | 14 d / 1 d noncurrent | Cheap audit trail |

All expressed as terraform variables; override per-environment.

## Verification results

End-to-end live test at **500 accounts** with the `compute` profile:

```
aws-vault exec ee-sandbox -- make test-pipeline ACCOUNTS=500
```

Outcome:

| Metric | Result |
|---|---|
| Snapshots uploaded to `cinq-config-mock` | 500 |
| SQS messages queued | 500 |
| Extract Lambda invocations | ~25 (batches of ≤25 at concurrency 5) |
| Iceberg snapshots (`operational$snapshots` row count) | 25 |
| Rows in `cinq.operational_live` | 27,054 |
| Distinct `account_id` | 500 |
| Distinct `resource_type` | 15 |
| DLQ depth after run | 0 |
| Queue final state | `visible=0 in_flight=0 delayed=0` |
| Top resource type | `AWS::EC2::SecurityGroup` (4,509 rows) |

The queue drained cleanly with no redeliveries, no messages in DLQ, and
the live view reported the expected row count across all 500 accounts.

## Issues encountered during bring-up

Saved for posterity so the next pipeline build doesn't re-discover them.

### 1. `athena_query_wait_polling_delay` is not a valid kwarg

Initial handler passed `athena_query_wait_polling_delay=1.0` to
`wr.athena.to_iceberg` based on a guess. awswrangler 3.14's signature
doesn't accept it; the handler raised
`TypeError: got an unexpected keyword argument`. Fix: remove the kwarg.
Lesson: inspect the library source (`pip download --no-deps` →
`unzip`) rather than inventing parameter names.

### 2. Missing `glue:CreateTable` / `glue:DeleteTable` on the extract IAM role

awswrangler's `to_iceberg` creates a temporary external Glue table per
invocation (for its CTAS-style write path), then drops it. The initial
IAM policy granted `GetTable`, `UpdateTable`, partition ops, etc., but
not `CreateTable` or `DeleteTable`. Failures showed as
`AccessDeniedException: … glue:DeleteTable` in CloudWatch. Fix: add
both actions to the role's inline policy, scoped to
`arn:aws:glue:*:*:table/cinq/*`.

### 3. awswrangler tries to create `aws-athena-query-results-<acct>-<region>`

When `s3_output` isn't explicitly passed, awswrangler calls
`create_athena_bucket()` for Athena's default output location. That
function does a `HeadBucket` and, on 404, a `CreateBucket`. On this
account the Lambda didn't have bucket-create permission, so it fell
into a `BucketExists` waiter loop and timed out after ~100s (the
`Max attempts exceeded` message in the traceback).

Fix: pass `s3_output=f"s3://{ATHENA_RESULTS_BUCKET}/extract/"` to
`to_iceberg` so awswrangler uses our pre-provisioned results bucket
and never touches the default.

### 4. `test_pipeline.sh` drain check missed `ApproximateNumberOfMessagesDelayed`

The first drain-wait loop only checked `visible + in_flight`. When
messages returned `batchItemFailures`, SQS held them in the **delayed**
state during retry backoff — neither visible nor in-flight — so the
script thought the queue had drained. Fix: include
`ApproximateNumberOfMessagesDelayed` in the termination condition.

### 5. `wr.athena.to_iceberg` → `ICEBERG_TOO_MANY_OPEN_PARTITIONS` at 54 rows

The blocker. Even with 1 account and 54 sorted rows — so 1 target
partition — Athena rejected the generated `INSERT INTO … SELECT …`
with `ICEBERG_TOO_MANY_OPEN_PARTITIONS: Exceeded limit of 100 open
writers for partitions`. The error is normally fixed by sorting source
rows by partition keys, but our rows were already sorted.

We verified directly from the CLI that a minimal
`INSERT INTO cinq.operational (account_id, arn, …) VALUES ('111…',
'arn:…', …)` **succeeded**, proving the Iceberg table and its write
path are fine. The problem is specific to the temp-table shape that
awswrangler constructs internally via `s3.to_parquet(dataset=True,
database=…, table=…)`.

Fix: bypass `wr.athena.to_iceberg` entirely. The handler now:
1. Builds one `pyarrow.Table` with an explicit schema matching the
   Iceberg table.
2. Writes it as **one** Parquet file to
   `s3://cinq-config/_staging/<batch-uuid>/data.parquet`.
3. Creates a transient external Glue table directly via
   `glue:CreateTable` (column list hand-authored to match the schema).
4. Fires `INSERT INTO cinq.operational (cols…) SELECT cols… FROM
   cinq.extract_staging_<uuid>` via Athena `start_query_execution`.
5. Drops the Glue table and deletes the staging file in a `finally`
   block.

This worked first try at both 1-account and 500-account scales. We
suspect awswrangler's `s3.to_parquet` dataset mode is producing
multiple small Parquet files that multiply the task count during the
INSERT, each opening partition writers — but we didn't confirm the
root cause. Worth revisiting if a future awswrangler upgrade promises
a fix.

### 6. pyarrow in the managed layer has no zstd codec

Our first manual Parquet write used `compression="zstd"`; pyarrow
raised `ArrowNotImplementedError: Support for codec 'zstd' not built`.
The AWS SDK for pandas layer's pyarrow is stripped of zstd. Fix:
switch to `compression="snappy"` — universally available, slightly
larger files, perfectly acceptable for a staging file that lives for
~5 seconds before being deleted.

### 7. Stale mock data and `terraform taint` chaining

Previous development sessions left ~2000 files in `cinq-config-mock`
and leftover partitioned Parquet files in `cinq-config/` from an
earlier `export_config_to_parquet.py` experiment. Clearing
`s3://cinq-config/` also deletes the Iceberg metadata, so after each
reset the Iceberg table had to be recreated. Terraform won't re-run
the `null_resource.iceberg_table` unless its triggers change or it's
tainted, so we had to `terraform taint null_resource.iceberg_table`
(then again for `null_resource.operational_live_view`) before
re-applying.

Note: `terraform taint` only accepts one resource per invocation —
chaining two in one command fails the second. Run them as separate
calls.

## Running the pipeline

### Fresh deploy from scratch
```bash
aws-vault exec ee-sandbox -- make deploy
```

### Live end-to-end test
```bash
aws-vault exec ee-sandbox -- make test-pipeline ACCOUNTS=500
```

Overrides:
```bash
make test-pipeline ACCOUNTS=50 PROFILE=networking TEST_TIMEOUT=120
```

### Reset and re-test (clean slate)
```bash
aws-vault exec ee-sandbox -- aws s3 rm s3://cinq-config/ --recursive
aws-vault exec ee-sandbox -- aws glue delete-table --database-name cinq --name operational_live
aws-vault exec ee-sandbox -- aws glue delete-table --database-name cinq --name operational
aws-vault exec ee-sandbox -- terraform -chdir=terraform/app taint null_resource.iceberg_table
aws-vault exec ee-sandbox -- terraform -chdir=terraform/app taint null_resource.operational_live_view
aws-vault exec ee-sandbox -- terraform -chdir=terraform/app apply -auto-approve
aws-vault exec ee-sandbox -- aws sqs purge-queue --queue-url $(terraform -chdir=terraform/app output -raw extract_queue_url)
aws-vault exec ee-sandbox -- make test-pipeline ACCOUNTS=500
```

### Troubleshooting checklist

| Symptom | First place to look |
|---|---|
| Queue stuck at `visible=0 in_flight=N delayed=0` | `aws logs tail /aws/lambda/cloud-infra-nlq-query-extract --since 5m` |
| Queue stuck at `delayed=N` | Lambda returned `batchItemFailures` → check logs for the underlying error |
| `IAM AccessDenied` in logs | Scope missing from `lambda_extract.tf` or `lambda_compact.tf` inline policies |
| `BucketExists waiter failed` | `s3_output` not passed to awswrangler (shouldn't happen now) |
| `ICEBERG_TOO_MANY_OPEN_PARTITIONS` | Someone regressed back to `wr.athena.to_iceberg` — the manual staging-table path avoids this |
| DLQ non-zero | Check DLQ messages with `aws sqs receive-message` then inspect the S3 key for corruption |
| Compact Lambda failures | CloudWatch `/aws/lambda/cloud-infra-nlq-query-compact`, look for MERGE SQL errors |

## What comes next

Phase 2 candidates (pick after this has baked for a bit):
- Wire in real AWS Config in the sandbox account and point the pipeline
  at the real delivery bucket (the only change is source bucket name).
- Build the NLQ query layer that consumes `cinq.operational_live`.
- Add CloudWatch alarms on DLQ depth and extract Lambda error rate.
- Add an integration test that exercises the TTL behaviour explicitly
  (generate profile A, wait, generate profile B on same accounts,
  verify profile A types disappear from the live view).
- Revisit `wr.athena.to_iceberg` on a newer awswrangler release to see
  if the `ICEBERG_TOO_MANY_OPEN_PARTITIONS` issue has been fixed — if
  so, collapse the handler back to a one-liner.
