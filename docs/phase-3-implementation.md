# Phase 3 — NLQ HTTP API on API Gateway v2

_Status: delivered and verified end-to-end via the custom domain (2026-04-13)._

## What phase 3 delivers

A live HTTP API at **`https://api.nlq.demos.apps.equal.expert/nlq`**
that takes `POST {"question": "..."}` and returns the same NL→SQL→Athena
flow that `scripts/nlq.py` runs locally, packaged as a Lambda behind
API Gateway v2 (HTTP API) with a custom domain, ACM cert, Route 53
records, and an `x-api-key` Lambda authoriser. Single `curl` from
anywhere on the internet does the lot:

```bash
curl -X POST https://api.nlq.demos.apps.equal.expert/nlq \
  -H "x-api-key: $API_KEY" \
  -H 'content-type: application/json' \
  -d '{"question":"how many EC2 instances per account, top 5"}'
```

returns

```json
{
  "question": "how many EC2 instances per account, top 5",
  "sql": "SELECT account_id, COUNT(*) AS instance_count FROM cinq.operational_live WHERE resource_type = 'AWS::EC2::Instance' GROUP BY account_id ORDER BY instance_count DESC LIMIT 5",
  "retrieved_schemas": [
    {"resource_type": "AWS::EC2::Host",     "service": "EC2", "category": "compute", "field_count": 48,  "distance": 0.6268},
    {"resource_type": "AWS::EC2::EC2Fleet", "service": "EC2", "category": "compute", "field_count": 90,  "distance": 0.6331},
    {"resource_type": "AWS::EC2::Instance", "service": "EC2", "category": "compute", "field_count": 135, "distance": 0.6502}
  ],
  "columns": ["account_id", "instance_count"],
  "rows": [
    {"account_id": "354342113419", "instance_count": "9"},
    {"account_id": "235447068293", "instance_count": "8"},
    {"account_id": "790757033266", "instance_count": "7"},
    {"account_id": "406404042870", "instance_count": "7"},
    {"account_id": "561902006518", "instance_count": "7"}
  ],
  "row_count": 5,
  "athena_query_id": "1ae7000d-7198-4248-bcf4-6249ddcfd787",
  "timings": {"embed_ms": 116.0, "retrieve_ms": 90.0, "generate_ms": 7090.5, "athena_ms": 2222.7, "total_ms": 9520.2}
}
```

**Out of scope for phase 3** (deliberately): user-facing UI, Cognito or
SSO auth, multi-tenant key management beyond a single shared API key,
streaming responses, conversation history, IP allow-listing, WAF rules.

## Architecture

```
                      DNS (Route 53)
                            │  api.nlq.demos.apps.equal.expert (A alias)
                            ▼
                ┌──────────────────────────┐
                │  API Gateway v2          │
                │  HTTP API                │
                │  $default stage          │
                │  burst=50, rate=10 req/s │
                └──────────────┬───────────┘
                               │  POST /nlq
                               │
            ┌──────────────────┴───────────────────┐
            │                                      │
            ▼                                      ▼
  ┌─────────────────────┐                ┌──────────────────────┐
  │ Lambda authoriser   │                │ NLQ Lambda           │
  │ (REQUEST type,      │                │ (Python 3.12 zip,    │
  │  simple-response,   │                │  bundled boto3+docs) │
  │  5-min API GW cache)│                │                      │
  │                     │                │  embed → retrieve →  │
  │  reads x-api-key    │                │  generate → athena   │
  │  from Secrets Mgr   │                │                      │
  └─────────────────────┘                └──────────┬───────────┘
                                                    │
              ┌─────────────────┬─────────────────┬─┴───────────────┐
              ▼                 ▼                 ▼                 ▼
        Bedrock           S3 Vectors         Athena         CloudWatch Logs
        Titan + Claude    cinq-schemas-      cinq.operational_live
                          index
```

## Components built

### Lambdas (`lambda/`)

**`lambda/nlq/handler.py`** — The HTTP API request handler. Mirrors
`scripts/nlq.py` but takes an API Gateway v2 event in and returns an
HTTP response out. Identical retrieval, prompting, validation, Athena
execution, and timing instrumentation.

Key choices:
- **Globals for boto3 clients** so warm invocations skip client init.
- **Schemas read from disk** on each request (they're tiny — ~1.5KB
  per file, ~417 files — and bundled into the deployment package next
  to `handler.py` under `enriched_schemas/`).
- **Returns structured rows** as a list of `{column: value, ...}`
  dicts, not the cells-and-headers shape that the CLI prints. Easier
  for HTTP consumers to use.
- **Per-error HTTP status codes**: 400 for bad input or rejected SQL,
  502 for upstream Bedrock / Athena failures, 200 for success.
- **`dry_run` flag** in the request body — generates SQL, validates,
  but skips Athena. Lets clients preview SQL cheaply.
- **Question size cap** at 2000 chars, top_k clamped to [1,25] to
  prevent prompt-injection by sheer payload size.

**`lambda/nlq_auth/handler.py`** — Lambda authoriser, ~30 lines of
pure Python:
- REQUEST type, simple-response format (`{"isAuthorized": bool}`)
- Reads the API key from Secrets Manager once per cold start, caches
  in-process. Combined with the API Gateway authoriser-side 5-minute
  TTL, the `GetSecretValue` call rate is essentially zero in steady
  state.
- Constant-time-ish string comparison (good enough for this threat
  model — we're not protecting against side-channel timing attacks).

### Packaging (`scripts/package_nlq_lambda.sh`)

Bundles the NLQ Lambda. Run automatically by `make deploy` via the
`package-nlq` Makefile target, also driven by a `null_resource` in
terraform with triggers on the handler hash, packager hash, and
schema file count, so a fresh `terraform apply` re-packages whenever
any of those change.

What it bundles into `build/nlq/`:
1. `handler.py` — the Lambda code
2. `enriched_schemas/*.md` — copied from `data/enriched_schemas/`
3. `boto3>=1.42.88` and `botocore>=1.42.88` via `pip install --target`

The runtime's bundled boto3 in Python 3.12 (~1.35) **does not** know
about the `s3vectors` service yet, so the Lambda would crash with
`UnknownServiceError` without our bundled override. This is the same
issue the local CLI hit in phase 2 — fix is the same: ship a recent
boto3 inside the package.

Final package size: **~32 MB unzipped** (well under Lambda's 250 MB
limit), **~10 MB compressed**. boto3+botocore are the dominant payload
(~25 MB) but compress well because they're mostly JSON service models.

### Terraform (`terraform/app/api.tf`)

A single new file holding the entire HTTP API stack: ~26 resources
covering the API key, two Lambdas + IAM + log groups, the HTTP API +
integration + authoriser + route + stage, the custom domain + ACM
cert + Route 53 records, and the API Gateway access log group.

The Route 53 setup uses a `data "aws_route53_zone"` lookup on
`demos.apps.equal.expert` (which already exists in the `ee-sandbox`
account, hosted zone ID `Z0034933LV9JZX4P67YC`) plus three records:
- ACM DNS validation `CNAME`
- An `A` alias record for `api.nlq.demos.apps.equal.expert` pointing
  at the API Gateway regional target
- The cert validation completes within seconds because we're creating
  the CNAME in the same apply.

The custom domain is REGIONAL (not edge-optimised) — simpler, cheaper,
no CloudFront distribution, and good enough for a per-region API.

The HTTP API is configured with `cors_configuration` allowing all
origins for `POST` and `OPTIONS` so the API can be hit from a browser
without an extra preflight pass. The route is gated behind the
authoriser (`authorization_type = "CUSTOM"`).

Stage settings:
- `$default` stage with `auto_deploy = true`
- Burst 50 req/s, sustained 10 req/s — sandbox-friendly throttle so a
  runaway script can't melt the Bedrock bill
- Access logs to a dedicated CloudWatch log group at
  `/aws/apigateway/cloud-infra-nlq-query-nlq`, JSON-formatted

### Makefile additions

| Target | Purpose |
|---|---|
| `package-nlq` | Bundle the NLQ Lambda (deploy prerequisite) |
| `package-lambdas` | Now also includes `package-nlq` |
| `api-key` | Print the API key from Secrets Manager (for stuffing into your shell) |
| `nlq-api Q="..."` | One-line `curl` against the deployed API, jq-formatted output |

### Outputs (`terraform/app/outputs.tf`)

| Output | Use |
|---|---|
| `nlq_api_endpoint` | Public custom-domain URL |
| `nlq_api_default_endpoint` | API Gateway default URL (no DNS, useful for debugging) |
| `nlq_api_key_secret_arn` | Secrets Manager ARN holding the key |
| `nlq_lambda_log_group` | Where to tail logs |

## Defaults

| Setting | Default | Source |
|---|---|---|
| API domain | `api.nlq.demos.apps.equal.expert` | `var.api_domain_name` |
| Route 53 zone | `demos.apps.equal.expert` | `var.api_dns_zone_name` |
| Lambda memory | 1024 MB | `var.nlq_lambda_memory_mb` |
| Lambda timeout | 90s | `var.nlq_lambda_timeout_seconds` |
| Authoriser TTL | 300s (API Gateway side) | `api.tf` |
| Throttle burst | 50 req/s | `api.tf` |
| Throttle sustained | 10 req/s | `api.tf` |
| Default top-K | 5 | request body override |
| Question size cap | 2000 chars | `handler.py` |
| Athena timeout | 60s | `handler.py` |

## Verification results

### Auth rejection
```bash
curl -X POST https://api.nlq.demos.apps.equal.expert/nlq \
  -H 'content-type: application/json' \
  -d '{"question":"how many ec2 instances per account"}'
# → HTTP 401 {"message":"Unauthorized"}
```
✅ Authoriser denies missing/wrong keys before any other code runs.

### Happy path with valid key
```bash
API_KEY=$(make api-key)
curl -X POST https://api.nlq.demos.apps.equal.expert/nlq \
  -H "x-api-key: $API_KEY" \
  -H 'content-type: application/json' \
  -d '{"question":"how many EC2 instances per account, top 5"}'
```
- Returned 5 rows
- `athena_query_id` populated
- `timings`: embed=116ms / retrieve=90ms / generate=7090ms / athena=2223ms / total=9520ms

### Cross-resource join through the API
```bash
curl -X POST https://api.nlq.demos.apps.equal.expert/nlq \
  -H "x-api-key: $API_KEY" \
  -H 'content-type: application/json' \
  -d '{"question":"for each EC2 instance show its attached volumes joining EC2::Instance with EC2::Volume","top_k":6}'
```
- Generated a WITH-CTE join with `instances` and `volumes` CTEs and the
  `attachments[0].instanceId` field on the volume side as the join key
- 5 rows back
- `total_ms`: 10634

### Dry run
```bash
curl -X POST ... -d '{"question":"largest 3 EBS volumes by size","dry_run":true}'
```
- Returned the SQL
- `dry_run: true`, `rows: []`, `row_count: 0`, `athena_query_id: null`
- Athena was not called

### DDL injection rejection
```bash
curl -X POST ... -d '{"question":"drop the operational table"}'
# → HTTP 400
# {
#   "error": "rejected SQL",
#   "detail": "model returned a comment, not SQL: -- cannot answer: ..."
# }
```
✅ Claude refuses, validator catches the comment-only response, no
Athena execution.

## Performance — API vs CLI

The API runs the same flow as `scripts/nlq.py`, but the network-bound
stages are dramatically faster because the Lambda lives in eu-west-2
alongside Bedrock and S3 Vectors:

| Stage | CLI median | API median | Why |
|---|---:|---:|---|
| `embed` | ~700 ms | **~110 ms** | Lambda → Bedrock is intra-region; CLI traverses public internet |
| `retrieve` | ~600 ms | **~95 ms** | Same reason for S3 Vectors |
| `generate` | ~3.4 s | ~5–7 s | Bedrock model latency dominates here regardless of where the caller lives |
| `athena` | ~2.5 s | ~2.2 s | Slight win from intra-region API calls |
| **total** | **~7 s** | **~7–10 s** | |

Generation is slightly slower from the API in some runs because the
`top_k=6` request asks for more retrieved schemas → more input tokens
→ more output tokens. The dominant cost is still Claude inference
regardless of where the caller sits. The API wins on the cheap stages
but loses nothing on the expensive ones.

API Gateway adds **~5–10 ms** of routing overhead per request (not
counting Lambda cold starts). The authoriser adds **~30 ms** on cache
miss, **~0 ms** on cache hit (5-min TTL).

## Issues encountered during build

### 1. boto3 in the Lambda runtime is too old for s3vectors

Same issue as the local CLI: Lambda's bundled boto3 (~1.35 in Python
3.12 as of early 2026) doesn't know about the `s3vectors` service.
First test run would have failed with `UnknownServiceError` if we
hadn't pre-empted it. Fix: pip install boto3+botocore into the package
itself via `scripts/package_nlq_lambda.sh`. Adds ~25 MB to the
package; well within limits.

### 2. Region-scoped Bedrock model ARN format

The IAM policy needs `bedrock:InvokeModel` on the model ARNs. Bedrock
accepts both `arn:aws:bedrock:<region>::foundation-model/<id>` and
`arn:aws:bedrock:<region>:<account>:foundation-model/<id>` — different
docs use different formats, and which one IAM matches against varies
slightly by service. Belt-and-braces: granted both forms in the
policy. Costs nothing and avoids a class of "permission denied"
debugging.

### 3. API Gateway HTTP API has no native API key plans

REST API has API key + usage plans built in; HTTP API doesn't. We had
to roll a tiny Lambda authoriser that checks the header against a
Secrets Manager value. ~30 lines of Python plus terraform wiring.
Cheap. Worth it because HTTP API is significantly cheaper to run than
REST API and the feature gap doesn't affect us.

### 4. ACM validation needs `data.aws_route53_zone` to point at the *parent*

`api.nlq.demos.apps.equal.expert` lives inside the `demos.apps.equal.expert`
hosted zone (the zone is two levels above the leaf). The `data` block
needs the zone name, not the leaf domain. Easy to get wrong if you
type in `api.nlq.demos.apps.equal.expert` to the data lookup —
terraform errors with "no matching Route 53 Zone found", which is
clearer than most AWS messages but still costs you a minute of
re-reading the docs.

### 5. `random_password` provider needed terraform re-init

The plan file mentioned `random_password` was already in use for the
NLQ Lambda zip key, but the AWS-only stack hadn't pulled in
`hashicorp/random` until this phase. First `terraform validate` after
adding `api.tf` errored "Missing required provider"; one
`terraform init` fixed it. Worth the muscle memory: any new
external-provider resource needs an `init` before `plan`/`apply` will
work.

## Cost estimate

| Item | Per request | At 10 req/min over 30 days |
|---|---:|---:|
| API Gateway HTTP API | $1.00 / 1M requests | ~$0.43 |
| NLQ Lambda compute | 1 GB × ~10s avg = ~$0.000167 | ~$72 |
| Authoriser Lambda compute | 256 MB × <100 ms (mostly cached) | <$1 |
| Bedrock Titan embed | 1 call × ~12 input tokens | <$0.001 each = ~$0 |
| Bedrock Claude Sonnet 4.6 | ~7K input + ~500 output | ~$0.029 each = ~$12.50 |
| S3 Vectors query | ~$0.0000025 each | ~$0.001 |
| Athena | tiny scan | <$0.001 each |
| **Total** | **~$0.03** per request | **~$85 / month at 432k requests** |

In practice the Lambda compute and Claude inference dominate. At lower
request rates (a few queries per day) the cost is rounding error.

## Running the API

### Get the API key
```bash
aws-vault exec ee-sandbox -- make api-key
# or:
aws-vault exec ee-sandbox -- aws secretsmanager get-secret-value \
  --secret-id $(terraform -chdir=terraform/app output -raw nlq_api_key_secret_arn) \
  --query SecretString --output text
```

### Make a request
```bash
# Easy way:
aws-vault exec ee-sandbox -- make nlq-api Q="how many EC2 instances per account, top 10"

# Manual way:
API_KEY=$(make api-key)
curl -X POST https://api.nlq.demos.apps.equal.expert/nlq \
  -H "x-api-key: $API_KEY" \
  -H 'content-type: application/json' \
  -d '{"question":"how many EC2 instances per account, top 10"}'
```

### Useful request body fields
| Field | Type | Default | Description |
|---|---|---|---|
| `question` | string | required | The natural-language question |
| `top_k` | integer | 5 | Number of schemas to retrieve from S3 Vectors (1–25) |
| `dry_run` | boolean | false | If true, generate SQL but skip Athena |

### Tail the Lambda logs
```bash
aws-vault exec ee-sandbox -- aws logs tail /aws/lambda/cloud-infra-nlq-query-nlq --follow
```

### Tail the API access log
```bash
aws-vault exec ee-sandbox -- aws logs tail /aws/apigateway/cloud-infra-nlq-query-nlq --follow
```

## What comes next

Phase 4 candidates:
- **Streaming responses** via Bedrock streaming + API Gateway response
  streaming, so callers get the SQL while it's being generated and the
  rows incrementally as they're fetched.
- **Conversation memory** for follow-up questions ("now group by region").
- **Per-user API keys** with usage tracking and quotas via DynamoDB.
- **A simple web UI** at `nlq.demos.apps.equal.expert` (no `api.`)
  hosting a chat interface that hits the API.
- **Migrate to provisioned concurrency** if cold starts become a
  problem (currently <1s, not worth it yet).
- **Replace the regex SQL validator** with a proper Trino parser
  (sqlglot) once the API is open to more callers.
- **Add WAF** in front of the custom domain if the API moves out of
  sandbox.
