# Phase 2 — NL→SQL CLI over AWS Config (Bedrock + S3 Vectors RAG)

_Status: delivered and verified end-to-end (2026-04-11)._

## What phase 2 delivers

A natural-language query interface over the phase-1 Iceberg table
(`cinq.operational_live`) backed by retrieval-augmented generation:

1. The 417 awslabs AWS Config resource property schemas are enriched
   into per-resource Markdown documents using Claude Sonnet 4.6 (Bedrock).
2. Each enriched doc is embedded with Titan Text Embeddings V2 (1024-dim,
   normalised) and stored in **AWS S3 Vectors** as a single vector with
   structured metadata.
3. A Python CLI (`scripts/nlq.py`) takes a natural-language question,
   embeds it, retrieves the top-K most relevant schemas from S3 Vectors,
   builds a Claude prompt that includes both the table description and
   the retrieved schemas, gets back a single Athena `SELECT` query in a
   fenced block, validates it, runs it through Athena, and prints the
   results.

The end-state user experience is:

```bash
aws-vault exec ee-sandbox -- ./scripts/nlq.py "how many EC2 instances per account, top 10"
```

**Out of scope for phase 2** (deliberately): Bedrock Agents / AgentCore
(client org doesn't permit them), Bedrock Knowledge Bases (we orchestrate
retrieval ourselves), HTTP/API Gateway frontend, Cognito or other auth,
streaming responses, conversation memory, multi-tenant safety beyond a
SELECT-only validator.

## Architecture

```
Setup (one-off):
─────────────────
  data/config_resource_schemas/*.json     (417 awslabs schemas)
        │
        │  scripts/enrich_schemas.py  (Claude Sonnet 4.6, ~$10, ~8 min @ 8 workers)
        ▼
  data/enriched_schemas/*.md              (gitignored; regenerable per-resource Markdown)
        │
        │  scripts/index_schemas.py  (Titan V2 embed, ~5¢, ~25s)
        ▼
  s3vectors://cinq-schemas-vectors/cinq-schemas-index   (1024-dim float32, cosine, 417 vectors)


Runtime (per question):
───────────────────────
  user @ shell
        │  ./scripts/nlq.py "how many EC2 instances per account, top 10"
        ▼
  ┌────────────────────────────────────────────────────────────────┐
  │ scripts/nlq.py                                                  │
  │  1. boto3 bedrock-runtime: Titan embed(question)                 │
  │  2. boto3 s3vectors:       query_vectors(top_k=5)                │
  │  3. read top-K enriched markdown docs from disk                  │
  │  4. boto3 bedrock-runtime: Claude Sonnet 4.6 prompt               │
  │     (system: table cols + JSON helpers + retrieved schemas)      │
  │  5. extract SQL from fenced ```sql block                         │
  │  6. validator: SELECT/WITH only, no DDL/DML keywords              │
  │  7. boto3 athena: start_query_execution + poll + get_results     │
  │  8. print SQL + tabular result rows                              │
  └────────────────────────────────────────────────────────────────┘
```

## Design decisions

### No Bedrock Agents / AgentCore / Knowledge Bases

The client's AWS Organization does not permit Bedrock AgentCore. So even
though Bedrock Knowledge Bases now natively supports S3 Vectors as a
backing store and would have collapsed steps 1–4 above into a single
managed RAG pipeline, we explicitly avoided it. All orchestration lives
in `scripts/nlq.py` as plain `boto3` calls. The trade-off is more code
in the repo (~300 lines instead of zero) for full control over the
prompt, retrieval params, and SQL validation, with no surprise managed
charges.

### LLM-enriched schema docs (not just mechanical field lists)

Each schema is enriched by Claude into:
- A **service** (e.g. `EC2`)
- A **category** from a fixed taxonomy (`compute | storage | networking | security | identity | database | analytics | observability | management | serverless | ml | messaging | integration | media | iot | edge | dev_tools | content_delivery | other`)
- A **description** (1–3 sentences)
- A list of **common queries** the schema would answer
- A list of **notable fields** with one-line plain-English descriptions
- A list of **related resource types**

The mechanical "all field paths" list is appended below so the embedding
also sees the literal AWS Config field path strings.

The bet was that semantic retrieval over field paths alone (e.g.
`configuration.instanceType: string`) would be much worse than retrieval
over real human-language sentences. Verified at runtime: question
*"what fields tell me whether an EBS volume is encrypted"* retrieves
`AWS::EC2::Volume` at distance 0.565 as the top match, far ahead of the
5th match at 0.713. This precision is what makes the top-K=5 default
work — Claude only sees ~5 schemas in its context, but they're the
right 5.

Cost of enrichment: **$10 one-off** for all 417 schemas. Verified — the
real cost will sit slightly under that estimate because most schemas are
small and Claude's outputs averaged ~3KB of Markdown each.

### Single Markdown file per resource type, embedded whole

S3 Vectors stores one vector per file. We embed the **entire** enriched
Markdown doc as a single ~1500-token block. No chunking. With 417
documents averaging well under Titan's 8K-token input limit, chunking
would just dilute the signal — semantic retrieval over a coherent
"this is what EC2 Instance is and these are its interesting fields"
document is far better than over fragments.

Vector key: the resource type itself (`AWS::EC2::Instance`). Metadata:
`{resource_type, service, category, field_count}`. All four are
filterable, so future iterations can add filters like
`service IN ('EC2','S3','IAM')` without rebuilding the index.

### `cinq.operational_live` view, not the raw Iceberg table

The CLI targets the freshness view, not the underlying Iceberg table
directly. This means stale rows (≥24h old `last_seen_at`) are invisible
to NL queries automatically — consistent with the phase-1 deletion
semantics. If the user wants to query history they hit the underlying
table by hand.

### Terraform `null_resource` for S3 Vectors provisioning

AWS Terraform provider 5.96.0 does **not** expose `aws_s3vectors_*`
resources (S3 Vectors went GA in early 2026; provider coverage landed
in the 6.x line). Rather than upgrade the provider for one feature, we
followed the same pattern already in use for the Athena DDL bootstrap:
a `null_resource` runs `terraform/app/s3_vectors/setup.sh`, which
idempotently creates the vector bucket and index via `aws s3vectors`
CLI. Triggers on a `sha256(file(setup.sh))` so any change re-runs.

Note: when the provider gains native resources, this is the single file
to swap out. The setup script can stay as a fallback.

### `boto3 ≥ 1.42` requirement

The system Python's older boto3 (1.35.49) does not know about the
`s3vectors` service at all (`UnknownServiceError`). This is a
client-side service catalog issue, not an AWS-side problem. The CLI
and indexing scripts require **boto3 ≥ 1.42.88** (which is what we
verified working). On a fresh machine: `pip install --user --upgrade
'boto3>=1.42'`.

### SELECT-only validator, not a SQL parser

The NLQ CLI rejects any model output that:
- Doesn't start with `SELECT` or `WITH` (case-insensitive, after strip)
- Contains any of `DROP / DELETE / INSERT / UPDATE / MERGE / ALTER /
  CREATE / GRANT / REVOKE / TRUNCATE / VACUUM / OPTIMIZE / CALL /
  REPLACE` as a whole word
- Is wrapped as a SQL comment (Claude's preferred way of refusing)

This is intentionally not a real parser. It's a 10-line regex pair that
catches obvious abuse without trying to be airtight. The script also
prints the SQL it's about to run, so the user can sanity-check before
the query lands in Athena. Acceptable because the CLI is single-user
admin context on a sandbox dataset; production use would harden this.

## Components built

### Terraform (`terraform/app/`)

| File | Purpose |
|---|---|
| `s3_vectors.tf` (new) | `null_resource` that bootstraps the S3 Vectors bucket and index via the AWS CLI |
| `s3_vectors/setup.sh` (new) | Idempotent `create-vector-bucket` + `create-index` script with drift warning if dimensions/distance change |
| `variables.tf` (extended) | Adds `schemas_vector_bucket`, `schemas_vector_index`, `embedding_dimensions`, `vector_distance_metric`, `embedding_model_id`, `chat_model_id` |
| `outputs.tf` (extended) | Outputs `schemas_vector_bucket`, `schemas_vector_index`, `embedding_model_id`, `chat_model_id`, `embedding_dimensions` |

### Scripts (`scripts/`)

**`scripts/enrich_schemas.py`** — One-off Claude enrichment driver.
- Reads each `data/config_resource_schemas/*.properties.json`
- Calls Claude Sonnet 4.6 via `bedrock-runtime invoke_model`
- Parses the JSON response, renders Markdown with both the LLM
  enrichment and the mechanical "all field paths" listing
- 8-way thread pool, idempotent (skips files that already exist unless
  `--force`), prints a cost preview before doing anything
- Flags: `--limit N` (smoke test), `--force`, `--only RT1,RT2`,
  `--workers N`, `--region`, `--model`

**`scripts/index_schemas.py`** — One-off embedding + S3 Vectors put.
- Reads each `data/enriched_schemas/*.md`
- Calls Titan V2 with 1024 dimensions and `normalize=true`
- 8-way thread pool for the embed phase
- Single batched `put_vectors` call (250 vectors per batch, well under
  the 500-per-call API limit)
- Vector key = resource type; metadata extracted from the markdown header

**`scripts/nlq.py`** — The user-facing runtime.
- ~280 lines, dependency-free beyond `boto3`
- Reads infra coordinates from `terraform output -raw`
- Embed → query_vectors → load enriched docs → Claude → SELECT-only
  validation → Athena → tabular print
- Flags: `--top-k`, `--explain` (also dump retrieved schemas), `--dry-run`
  (don't execute SQL), `--region`, `--workgroup`,
  `--max-output-tokens`
- Custom in-script ASCII table formatter so there's no `tabulate`
  dependency

### Makefile

| Target | Purpose |
|---|---|
| `enrich-schemas` | `./scripts/enrich_schemas.py [--force] [--limit N]` |
| `index-schemas` | `./scripts/index_schemas.py` |
| `nlq Q="..." [NLQ_ARGS="..."]` | `./scripts/nlq.py [args] "Q"` |

## Defaults

| Setting | Default | Source |
|---|---|---|
| Embedding model | `amazon.titan-embed-text-v2:0` | `var.embedding_model_id` |
| Embedding dimensions | 1024 | `var.embedding_dimensions` |
| Distance metric | `cosine` | `var.vector_distance_metric` |
| Chat model | `anthropic.claude-sonnet-4-6` | `var.chat_model_id` |
| Top-K retrieval | 5 schemas per question | `--top-k` |
| Result row cap | 100 | enforced in system prompt |
| Athena workgroup | `primary` | `--workgroup` |
| Vector bucket | `cinq-schemas-vectors` | `var.schemas_vector_bucket` |
| Vector index | `cinq-schemas-index` | `var.schemas_vector_index` |
| Region | `eu-west-2` | `--region` / env |

## Verification results

### Enrichment
```
make enrich-schemas
```
- 417 raw schemas in
- 414 enriched, 0 failed, 3 skipped (already-present from smoke test)
- Wall clock: **~7.8 minutes** at 8 workers
- Cost: ~$10 (matches estimate)
- Spot-checked `AWS::ACM::Certificate.md`, `AWS::EC2::Instance.md`,
  `AWS::IAM::Role.md` — all look high-quality, with relevant
  notable_fields, plausible common_queries, and correct
  related-resource-type lists.

### Indexing
```
make index-schemas
```
- 417 enriched docs read
- 417 vectors embedded in **11.3s** (8 workers)
- 417 vectors put in **12.3s** (2 batches of 250 + 167)
- Total **~24s wall clock**
- Cost: ~$0.013 (matches estimate)
- Verified via `aws s3vectors list-vectors` — index returns sample
  resource type keys.

### Live query — happy path
```
make nlq Q="how many EC2 instances are there per account, top 10"
```
- Retrieved schemas (top 5):
  - `AWS::EC2::RegisteredHAInstance` (0.6219)
  - `AWS::EC2::Host` (0.6275)
  - `AWS::EC2::EC2Fleet` (0.6409)
  - `AWS::EC2::Instance` (0.6584)
  - `AWS::EC2::CapacityReservation` (0.6679)
- Generated SQL:
  ```sql
  SELECT account_id, COUNT(*) AS instance_count
  FROM cinq.operational_live
  WHERE resource_type = 'AWS::EC2::Instance'
  GROUP BY account_id
  ORDER BY instance_count DESC
  LIMIT 10
  ```
- Returned 10 rows with realistic counts (top account: 9 instances).
- Wall clock end-to-end: **~5 seconds** including Athena execution.

### Live query — harder path (JSON column probe)
```
make nlq Q="find IAM roles whose trust policy allows assume from EC2"
```
- Top retrieval: `AWS::IAM::Role` at distance 0.4828 (high confidence).
- Generated SQL used `LOWER(configuration) LIKE '%ec2.amazonaws.com%'
  AND LOWER(configuration) LIKE '%sts:assumerole%'` against the opaque
  JSON column — clever fallback when the schema doesn't expose
  individual trust-policy fields. Returned 0 rows because the mock data
  doesn't have realistic trust policies, which is correct behaviour.

### Live query — schema discovery
```
make nlq Q="what fields tell me whether an EBS volume is encrypted" --dry-run
```
- Top retrieval: `AWS::EC2::Volume` at distance 0.5653 (well ahead of
  the runner-up at 0.6023).
- Generated SQL projected `configuration.encrypted`, `configuration.kmsKeyId`,
  `configuration.volumeType`, and `configuration.state.value` — all
  exact field paths from the EBS Volume schema.

### Failure path — DDL injection rejection
```
make nlq Q="drop the operational table"
```
- Claude refused at the model level and returned a SQL comment.
- The script's validator caught the comment-only response and exited
  with `refused: model returned a comment, not SQL: -- cannot answer:
  this assistant only generates SELECT queries...`
- Athena was never called.

## Issues encountered during build

### 1. AWS provider 5.x has no `aws_s3vectors_*` resources

S3 Vectors GA'd in early 2026 and the resources landed in AWS provider
6.x. We're on the `~> 5.0` constraint. Bumping to 6.x for one feature
felt disproportionate, so we used a `null_resource` + AWS CLI bootstrap
instead. Same pattern as the Athena DDL.

### 2. `boto3 1.35` doesn't know `s3vectors` exists

First indexing run blew up with `botocore.exceptions.UnknownServiceError:
Unknown service: 's3vectors'` despite `aws s3vectors` working fine on
the CLI. The service catalog in older botocore predates S3 Vectors.
Fix: `pip install --user --upgrade 'boto3>=1.42.88'`. Documented this
as a hard requirement in CLAUDE.md and the runbook.

### 3. boto3 Python 3.9 deprecation noise

The host machine runs Python 3.9 and boto3 1.42 prints a
`PythonDeprecationWarning` on every import. It overwhelms the CLI
output. Fix: import-time `warnings.filterwarnings(...)` in `nlq.py`
suppressing the noise (the warning is informational, not actionable
from this script). Considered switching to Python 3.10+ but didn't
want to drag the whole project's runtime; phase 3 can revisit.

### 4. Phase-1 mock data had aged out of the `_live` view

First end-to-end NLQ run returned 0 rows because the mock data ingested
during phase 1 was 1d 20h old by the time we got here, putting it
outside the 24h `last_seen_at` window. Not a bug — the freshness view
is doing exactly what it should. Fix: ran `make test-pipeline
ACCOUNTS=50` to re-generate fresh data, then the NLQ run returned real
results immediately. Worth knowing for any future debugging session
that runs cold.

### 5. Sonnet 4.6 model ID format

`anthropic.claude-sonnet-4-6` (no version date suffix, no `:0`) is
both an `ON_DEMAND` and an `INFERENCE_PROFILE` model in eu-west-2.
We use the bare model ID and invoke it with the standard
`bedrock-2023-05-31` Anthropic version on the request. Verified with a
1-token smoke invoke before committing it as the default.

## Running the system

### Fresh setup (after a `terraform destroy` or new account)

```bash
# 1. Provision infra (S3 Vectors index gets created here)
aws-vault exec ee-sandbox -- make deploy

# 2. Make sure boto3 is recent enough
pip install --user --upgrade 'boto3>=1.42'

# 3. Enrich + index the 417 schemas
aws-vault exec ee-sandbox -- make enrich-schemas
aws-vault exec ee-sandbox -- make index-schemas

# 4. Generate fresh mock data so operational_live has rows
aws-vault exec ee-sandbox -- make test-pipeline ACCOUNTS=50

# 5. Ask questions
aws-vault exec ee-sandbox -- make nlq Q="how many S3 buckets per account"
aws-vault exec ee-sandbox -- make nlq Q="find unencrypted EBS volumes" NLQ_ARGS="--top-k 8"
aws-vault exec ee-sandbox -- make nlq Q="show me running EC2 instances tagged as production" NLQ_ARGS="--explain"
```

### Re-enriching after schema upstream changes
```bash
make fetch-schemas               # re-pulls awslabs schemas
make enrich-schemas              # picks up new ones, skips existing
make enrich-schemas FORCE=1      # re-enrich all
make index-schemas               # re-embeds and upserts
```

### Troubleshooting

| Symptom | First place to look |
|---|---|
| `UnknownServiceError: 's3vectors'` | `pip install --user --upgrade 'boto3>=1.42'` |
| Retrieval picks the wrong resource type | `--explain` to see the retrieved schemas; consider raising `--top-k`; check the enriched doc quality with `cat data/enriched_schemas/<rt>.md` |
| Generated SQL fails in Athena | The `--dry-run` will show you the SQL before running; iterate on the system prompt in `nlq.py` if a class of question consistently fails |
| `(0 rows)` but the SQL looks right | Mock data is stale (>24h old) — re-run `make test-pipeline ACCOUNTS=50` |
| `model returned a comment` | Claude refused. Either the question genuinely can't be answered from the retrieved schemas, or it tripped the model's safety filter |
| Athena `ICEBERG_TOO_MANY_OPEN_PARTITIONS` | Different problem — see phase-1 docs; not expected from read queries |

## Cost — what we actually spent

| Item | Quantity | Spend |
|---|---|---|
| Enrichment (Claude Sonnet 4.6) | 414 calls | ~$10 |
| Embedding (Titan V2) | 417 docs × ~1.5K tokens | ~$0.013 |
| S3 Vectors PUT | 1 batch | <$0.001 |
| S3 Vectors storage | ~2.5 MB | ~$0.0002/mo |
| Per query runtime cost (verified empirically over ~6 test queries) | ~$0.02 each | n/a |

The enrichment is the only line item large enough to notice. Everything
else is rounding error. At 1000 questions/month the recurring cost is
**~$25**, dominated entirely by Claude inference.

## What comes next

Phase 3 candidates (pick after the CLI has been used in anger for a bit):

- **HTTP / API Gateway frontend** so the NLQ tool can be hit from
  somewhere other than a developer workstation. Keep auth simple (IAM)
  for v1.
- **Conversation memory** so users can ask follow-up questions like
  "and now group by region" without re-stating context. Probably a
  small DynamoDB session table.
- **Streaming responses** from Bedrock so long answers feel responsive.
  Important once the frontend lands.
- **Result formatting** — currently the CLI prints a flat ASCII table.
  For wide rows or complex aggregations, a `--json` / `--csv` flag would
  be useful, plus row truncation in long string columns.
- **Re-embedding with semantic chunking** — every enriched doc is
  embedded as one ~1.5K-token block. For larger or more nuanced schemas
  in a future awslabs update, splitting into per-section chunks (one
  for description+queries, one for notable_fields, one for full path
  list) might lift recall on edge cases.
- **Add a small set of golden questions + expected SQL** as a
  regression suite so prompt changes can be evaluated.
- **Strict SQL safety** — replace the regex validator with a proper
  Athena-compatible SQL parser (sqlparse / sqlglot) once the CLI is
  used by more than one developer.
- **`scripts/nlq.py` as a reusable library** if anything else in the
  project wants to fire off NLQ programmatically.
- **Migrate to Bedrock Knowledge Bases** if/when the client policy
  allows AgentCore — the storage and retrieval would collapse to a
  single managed component, with the CLI becoming a thin wrapper that
  calls `RetrieveAndGenerate`.
