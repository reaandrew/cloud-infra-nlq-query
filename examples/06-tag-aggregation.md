# Example 6 — Tag-based aggregation (JSON object key probe)

Aggregation by a value pulled out of the `tags` JSON column. AWS Config
stores tags as either a JSON object or array depending on the source;
in our pipeline they're a flattened JSON object, so a single
`json_extract_scalar(tags, '$.Environment')` lookup works.

## Question

> show me a count of EC2 instances broken down by their Environment tag value, top 10

## Retrieved schemas (top 5)

| # | resource_type | distance | service | category |
|---|---|---:|---|---|
| 1 | `AWS::Cloud9::EnvironmentEC2` | 0.5621 | Cloud9 | dev_tools |
| 2 | `AWS::ElasticBeanstalk::Environment` | 0.6509 | ElasticBeanstalk | compute |
| 3 | `AWS::EC2::RegisteredHAInstance` | 0.6584 | EC2 | compute |
| 4 | `AWS::AppConfig::Environment` | 0.6588 | AppConfig | management |
| 5 | `AWS::M2::Environment` | 0.6668 | M2 | compute |

The retrieval is **interestingly off** here: the embedding picked up
on the word *"Environment"* and pulled in resource types that have
"Environment" in the name (Cloud9 / ElasticBeanstalk / AppConfig / M2).
None of these are what the question is actually about — the user wants
EC2 Instance rows aggregated by their `Environment` tag.

Despite the noisy retrieval, Claude generated the right SQL anyway —
because the `tags` column is a flat schema-wide column documented in
the system prompt, not in any per-resource enriched doc. This is a
useful reminder that the system prompt's table description is doing
real work and isn't redundant with retrieval.

If you wanted retrieval to land more precisely you could phrase the
question as *"count EC2 Instance rows by the Environment tag"* — the
explicit `EC2 Instance` token would shift retrieval toward the right
schema, although the SQL doesn't actually need it.

## Generated SQL

```sql
SELECT
    json_extract_scalar(tags, '$.Environment') AS environment_tag,
    COUNT(*) AS instance_count
FROM cinq.operational_live
WHERE resource_type = 'AWS::EC2::Instance'
GROUP BY json_extract_scalar(tags, '$.Environment')
ORDER BY instance_count DESC
LIMIT 10
```

Tight and correct. Notice it correctly:
- Pulled the tag value via `json_extract_scalar`
- Filtered on `resource_type = 'AWS::EC2::Instance'` even though no
  schema in the retrieval mentioned EC2 Instance directly
- Grouped by the same expression in `SELECT`, which is required (not
  the alias) because Trino evaluates `GROUP BY` before column aliases

## Athena results

| environment_tag | instance_count |
|---|---:|
| development | 70 |
| production | 67 |
| staging | 61 |

3 rows — those are the three `Environment` tag values the mock
generator emits.

## Performance

| Stage | Time |
|---|---:|
| `embed` | 712.4 ms |
| `retrieve` | 617.8 ms |
| `generate` (Claude Sonnet 4.6, ~8K input + ~120 output tokens) | 2018.2 ms |
| `athena` | 7518.9 ms |
| **total** | **10868.8 ms** |

Bedrock side is healthy (~3.4s combined). The Athena number at ~7.5s
is suspicious for such a tiny query — most of the time isn't actual
work, it's the start_query_execution + polling cycle interacting with
Athena's queue. We've seen `athena` land anywhere from 2.3s (example 1)
to 7.5s (here and example 4) with no obvious correlation to query
complexity or row count, so the variance is in Athena scheduling not
our SQL. A burst of identical queries would likely cache better and
land near the floor.
