# Cloud-Infra NLQ Query Project Guide

## Project Status

An auto-triggered pipeline ingests AWS Config snapshots from a mock source bucket
into an Iceberg table in a Glue Data Catalog, queryable via Athena. Rows land in
seconds after a snapshot is uploaded; stale rows drop out of the operational view
within a configurable TTL window.

## Architecture

```
cinq-config-mock (S3)
    │  S3:ObjectCreated on *.json.gz under ConfigSnapshot/
    ▼
cinq-extract-queue (SQS, batch 25, 60s window, DLQ at 3 retries)
    │
    ▼
extract Lambda (zip + AWS SDK for pandas managed layer)
    │  flattens configurationItems → pyarrow → Parquet (snappy)
    │  → staging external Glue table → Athena INSERT INTO → drops staging
    ▼
cinq-config (S3) ── Iceberg table cinq.operational ── Glue Data Catalog
                                              ▲
                                              │  EventBridge daily 03:00 UTC
                                              │
                            compact Lambda (zip, boto3 only)
                              MERGE INTO / DELETE / OPTIMIZE / VACUUM
                                              │
                                              ▼
                            Athena view cinq.operational_live
                                 (downstream consumers query this)
```

### Key design decisions

- **SQS batching (25 files, 60s window) + reserved concurrency 5** on the extract
  Lambda caps concurrent Iceberg commits so we stay below Glue's optimistic-
  concurrency retry threshold.
- **Append-only from the extract Lambda**. Dedupe-to-latest happens server-side
  via the nightly compact Lambda's `MERGE INTO`, so the live view can be a
  simple TTL-filter without a `ROW_NUMBER()` window.
- **Staging-table write pattern** (not `wr.athena.to_iceberg`). The Lambda writes
  a single Parquet file with pyarrow, creates a short-lived external Glue table
  pointing at it, fires `INSERT INTO … SELECT …`, then drops the staging table.
  awswrangler's built-in `to_iceberg` triggered `ICEBERG_TOO_MANY_OPEN_PARTITIONS`
  on this table even with 54 rows; the manual pattern avoids it.
- **Opaque JSON columns** for `configuration`, `supplementary_configuration`,
  `relationships`, `tags`. AWS Config has ~400 resource types with incompatible
  nested shapes — flattening fights the data.
- **S3 lifecycle rule only on `cinq-config-mock`**. `cinq-config` is an Iceberg
  table; file cleanup is Iceberg's job (`VACUUM`, `expire_snapshots`, run by the
  compact Lambda). A blanket lifecycle rule there would corrupt the table.

## Deployment

### AWS Authentication
Always use the `ee-sandbox` profile:
```bash
aws-vault exec ee-sandbox -- <command>
```

### Deploy infrastructure
From the project root:
```bash
aws-vault exec ee-sandbox -- make deploy
```
Runs `terraform apply` in `terraform/app/`. Packaging the Lambda zips is a
prerequisite of `deploy`, so a single command suffices.

## Testing the pipeline end-to-end

```bash
aws-vault exec ee-sandbox -- make test-pipeline ACCOUNTS=500
```

What this does:
1. Generates 500 mock AWS Config snapshots into `cinq-config-mock`.
2. S3 fires ObjectCreated events → SQS.
3. The extract Lambda processes batches of up to 25 snapshots per invocation,
   appends each batch to the Iceberg table.
4. The script polls SQS until drained (visible + in-flight + delayed all 0),
   then queries Athena for row counts and resource-type histogram.

Expected on a fresh run with the `compute` profile: ~27k rows across 500
distinct accounts, 15 resource types, ~25 Iceberg snapshots (one per batch).

### Dev-time only (no pipeline)
```bash
make bootstrap               # generate mock data (Lambda pipeline processes asynchronously)
make generate-mock ACCOUNTS=50 PROFILE=compute
```

## Project Structure

### Terraform (`terraform/app/`)

- **main.tf** — provider, backend, VPC/subnets/IGW/route table, S3 buckets
  (`cinq-config`, `cinq-config-mock`, `<app>-athena-results`), lifecycle rule
  on the mock bucket
- **sqs.tf** — `cinq-extract-queue`, `cinq-extract-dlq`, redrive policy, queue
  policy granting S3 permission, S3 bucket notification
- **glue.tf** — `aws_glue_catalog_database.cinq`
- **athena.tf** — `null_resource` drivers that run `athena/iceberg_table.sql`
  and `athena/operational_live.sql` via `athena/run_ddl.sh`
- **lambda_extract.tf** — IAM role, zip Lambda, AWS SDK for pandas layer ARN,
  SQS event source mapping
- **lambda_compact.tf** — IAM role, zip Lambda, EventBridge daily schedule
- **variables.tf** — all knobs (TTL windows, batch sizes, concurrency,
  compact cron)
- **outputs.tf** — queue URLs, bucket names, iceberg/view names

### Lambda source

- **lambda/extract/handler.py** — SQS batch handler. Flattens snapshots to a
  single pyarrow Table, writes one Parquet file to `s3://cinq-config/_staging/
  <uuid>/data.parquet`, creates a transient Glue external table, runs
  `INSERT INTO cinq.operational SELECT …`, drops the staging table.
- **lambda/compact/handler.py** — daily Athena sequence: `MERGE INTO`
  (dedupe to latest per `(account_id, arn)`), `DELETE FROM` (hard TTL sweep
  at `TTL_HARD_DELETE_DAYS`), `OPTIMIZE` (compact small files), `VACUUM`
  (expire old Iceberg snapshots).

### Scripts

- **scripts/generate_config_snapshot.py** — mock AWS Config snapshot
  generator, uploads to `cinq-config-mock` in the real AWS Config S3 layout
- **scripts/fetch_config_resource_schemas.sh** — fetches AWS Config resource
  schemas from the awslabs repo (output gitignored under
  `data/config_resource_schemas/`)
- **scripts/config_profiles.json** — profiles (`compute`, `data`, `security`,
  `networking`) for the snapshot generator
- **scripts/test_pipeline.sh** — end-to-end test driver invoked by
  `make test-pipeline`; reads terraform outputs, waits for SQS to drain,
  queries Athena for snapshot count + live view stats
- **scripts/export_config_to_parquet.py**, **scripts/unpack_config_snapshots.py**
  — local dev-time alternatives to the pipeline. Not used by the Lambdas.

## S3 Buckets

- **cinq-config-mock** — raw gzipped AWS Config snapshots. 14d/1d lifecycle rule.
- **cinq-config** — Iceberg table `cinq.operational` data + metadata, and a
  transient `_staging/` prefix used by the extract Lambda. **No lifecycle rule.**
- **cloud-infra-nlq-query-athena-results** — Athena query result staging.
  7d lifecycle rule.
- **cloud-infra-nlq-query-tfstate** — Terraform remote state (managed in
  `terraform/initial_setup/`).

## Glue Data Catalog

- Database: `cinq`
- Iceberg table: `cinq.operational` (partitioned by `account_id`)
- View: `cinq.operational_live` — filters `WHERE last_seen_at > current_timestamp
  - interval '24' hour`; downstream consumers query this, not the raw table

## Environment

- **Region**: eu-west-2
- **Lambda runtime**: Python 3.12
- **Managed layer**: `arn:aws:lambda:eu-west-2:336392948345:layer:AWSSDKPandas-Python312:20`
  (bundles pyarrow + pandas + boto3 + awswrangler; ECR is unavailable in this
  account so container-image Lambdas are off the table)

## Development Workflow

### Git Commit Conventions

Follow conventional commits:
- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `chore:` - Maintenance tasks
- `refactor:` - Code restructuring
- `test:` - Test additions or modifications
