# NLQ examples

Six worked examples of natural-language → SQL → Athena results,
captured live from `scripts/nlq.py --timings` against the phase-1
Iceberg table. Each file is the full record of one query: the question
exactly as asked, the schemas the S3 Vectors retriever picked, the SQL
Claude generated, the actual rows Athena returned, and a per-stage
timing breakdown.

| # | File | Pattern | Total time |
|---|---|---|---:|
| 1 | [01-resource-histogram.md](01-resource-histogram.md) | Single-resource aggregation, no JSON probe | 4.95 s |
| 2 | [02-largest-ebs-volumes.md](02-largest-ebs-volumes.md) | Single-resource, JSON column probe + cast | 6.47 s |
| 3 | [03-instance-volume-join.md](03-instance-volume-join.md) | Two-resource cross-join (Instance ↔ Volume) | 9.76 s |
| 4 | [04-subnet-occupancy-join.md](04-subnet-occupancy-join.md) | Three-resource join with LEFT JOIN + COALESCE | 15.46 s |
| 5 | [05-vpc-inventory-join.md](05-vpc-inventory-join.md) | Four-resource pivot via `COUNT(*) FILTER (WHERE …)` | 19.25 s |
| 6 | [06-tag-aggregation.md](06-tag-aggregation.md) | Tag-based aggregation, JSON object key probe | 10.87 s |

## How to run any of these yourself

```bash
aws-vault exec ee-sandbox -- ./scripts/nlq.py --timings "<your question>"
```

Or use the Makefile target with `NLQ_ARGS` to pass `--timings`:

```bash
aws-vault exec ee-sandbox -- make nlq Q="how many EC2 instances per account, top 10" NLQ_ARGS="--timings"
```

## Performance commentary

The end-to-end NLQ flow has four sequential stages, each making one or
more network round-trips. Across all six examples the median wall-clock
breakdown is roughly:

| Stage | Median | Range | What's happening |
|---|---:|---:|---|
| `embed` | ~700 ms | 633 – 5610 ms | One Bedrock `invoke_model` call against Titan V2. Question is small (~12 tokens), so this is mostly request latency, not compute. |
| `retrieve` | ~600 ms | 519 – 622 ms | One `s3vectors query_vectors` call. Independent of result size at this scale. |
| `generate` | ~3.4 s | 1484 – 9954 ms | One Bedrock `invoke_model` call against Claude Sonnet 4.6. **Linear in output tokens**, which scales with SQL complexity. |
| `athena` | ~2.5 s | 2314 – 7519 ms | `start_query_execution` + 1.5s polling + `get_query_results`. Mostly scheduling overhead, not scan time. |
| **total** | **~7 s** | 4.95 – 19.25 s | |

### What's predictable

- **`embed`** is essentially constant near 700 ms when the Bedrock
  endpoint is warm. The 5.6 s outlier in example 5 is unrepresentative
  — looks like a regional cold start or transient throttle.
- **`retrieve`** is the most stable stage at ~600 ms, every run, every
  query. S3 Vectors `query_vectors` against a 417-vector index is
  trivially fast — at this scale you're paying for the API round trip
  plus a tiny similarity search.
- **`generate`** scales **with SQL output size**, not retrieval count
  or schema doc length:
  - Simple histogram (~70 output tokens) → 1.5 s
  - JSON-probe (~150 output tokens) → 2.7 s
  - Two-resource join (~700 output tokens) → 6.0 s
  - Five-CTE join (~900 output tokens) → 6.7 s
  - Four-resource pivot (~600 output tokens) → 5.6 s

  Ballpark: **~7 ms per output token** on Sonnet 4.6 in eu-west-2 — the
  tokens-per-second envelope of the model. Input token count
  (~7 K – 16 K) barely moves the needle compared to output.

- **`athena`** has a hard floor around 2.3 s for any query because
  `start_query_execution` → first `get_query_execution` poll always
  waits at least one polling tick. Above that, scan time depends on
  the join cardinality — but at our 27 K-row scale, scan time is
  noise relative to scheduling.

### What's noisy

- Athena varies between 2.3 s and 7.5 s for queries that should all be
  trivially fast. This is Athena queue scheduling, not our SQL — the
  same query re-run a moment later usually lands near the floor. At
  larger data volumes (10s of GB) the variance would be dominated by
  scan time and become much more correlated with query complexity.
- Cold Bedrock invocations occasionally spike `embed` or `generate` by
  3–5 s. We saw it once in example 5; not consistent.

### Where time actually goes

For a typical 7-second cross-resource query, the breakdown is
roughly:

```
  embed     ████                                           ~10%
  retrieve  ████                                           ~10%
  generate  ████████████████████████████                   ~50%
  athena    ██████████████                                 ~30%
```

So **half the wall clock is Claude generating SQL**, and **a third is
Athena scheduling overhead**. Schema retrieval and question embedding
together are <20% of total time. None of these stages are CPU-bound
on our side — every dot above is a wait on a remote service.

### What this means in practice

- **For interactive use**: 5–10 seconds per question is fine. Users
  asking ad-hoc questions don't notice the difference between 5 s
  and 10 s; they notice the difference between 5 s and 30 s. We're
  comfortably in the first bucket.
- **For batch use** (e.g. a nightly job that asks 100 questions):
  total wall clock would be ~10 minutes serial. Could be parallelised
  via Bedrock's batch tier if needed, but at $25/month for 1000
  questions this isn't worth optimising.
- **The path to faster**: switching to Claude Haiku 4.5 would cut
  `generate` to maybe 1.5–2 s per query at the cost of slightly worse
  SQL quality on the cross-resource joins. Worth a phase-3 A/B if the
  CLI gets used in anger.
- **The path to cheaper**: nothing meaningful. Generation is already
  the dominant cost and you're paying for output tokens regardless.

### Where the system shines (and where it doesn't)

**Shines**:
- Single-resource aggregations (example 1, 6) — fast, accurate, no
  fuss.
- Cross-resource joins where both sides are in the top-K retrieval
  (example 3) — the system prompt + enriched schemas give Claude
  exactly enough to write correct WITH-CTE patterns.
- Three-way joins with `LEFT JOIN` + `COALESCE` for orphan-detection
  patterns (example 4) — Claude reaches for this pattern unprompted
  and gets it right.

**Struggles** (or where you should pay attention):
- When the question doesn't name a specific resource type, retrieval
  goes fuzzy (example 1, 6). The SQL still works because the system
  prompt is explicit about the flat columns, but the retrieved schemas
  are wasted context.
- When secondary resource types in a join are obscure or have
  uncommon JSON paths (example 5), retrieval may miss them and Claude
  has to lean on AWS naming conventions instead of explicit schema
  knowledge. Workaround: use `--top-k 8` for known cross-resource
  questions, or name the resource types explicitly in the question.
- When a question mixes a strong semantic word with an unrelated
  concept (example 6: *"Environment tag"* attracts every resource
  type with "Environment" in the name). The model recovers because
  it knows about the `tags` column from the system prompt, but
  retrieval is technically wrong.

### Cost actuals from this batch of 6 queries

Estimated from token counts:

| Item | Quantity | Cost |
|---|---|---:|
| Titan V2 embeds (6 questions × ~12 tokens) | ~72 tokens | <$0.001 |
| S3 Vectors queries | 6 calls | <$0.001 |
| Claude Sonnet 4.6 input | ~62 K tokens | ~$0.19 |
| Claude Sonnet 4.6 output | ~2.5 K tokens | ~$0.04 |
| Athena queries | 6 queries × <1 MB scanned | <$0.001 |
| **Total for the example set** | | **~$0.23** |

About **4 cents per question** in this batch, which is consistent with
the phase-2 doc's ~$0.02–0.03 estimate but on the high end because
several queries had longer-than-typical CTE outputs.
