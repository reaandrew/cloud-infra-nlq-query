# Example 2 — Largest EBS volumes (single-resource JSON probe)

Reaches into the opaque `configuration` JSON column to pull out the
volume size, type, and encryption status. Demonstrates that the system
prompt's `json_extract_scalar` guidance and the enriched schema's
`notable_fields` list are enough for Claude to pick the right paths.

## Question

> list the largest 10 EBS volumes by size showing volume ID, size, type, encryption status and account

## Retrieved schemas (top 5)

| # | resource_type | distance | service | category |
|---|---|---:|---|---|
| 1 | `AWS::EC2::Volume` | 0.6266 | EC2 | storage |
| 2 | `AWS::ECS::CapacityProvider` | 0.7951 | ECS | compute |
| 3 | `AWS::ElasticLoadBalancingV2::LoadBalancer` | 0.8005 | ElasticLoadBalancingV2 | networking |
| 4 | `AWS::EFS::FileSystem` | 0.8129 | EFS | storage |
| 5 | `AWS::Lightsail::Disk` | 0.8155 | Lightsail | storage |

The top hit is exactly right (`AWS::EC2::Volume` at distance 0.627,
well ahead of the rest). Only the top schema is actually used by the
generated SQL.

## Generated SQL

```sql
SELECT
    resource_id AS volume_id,
    CAST(json_extract_scalar(configuration, '$.size') AS INTEGER) AS size_gib,
    json_extract_scalar(configuration, '$.volumeType') AS volume_type,
    CAST(json_extract_scalar(configuration, '$.encrypted') AS BOOLEAN) AS encrypted,
    account_id
FROM cinq.operational_live
WHERE resource_type = 'AWS::EC2::Volume'
ORDER BY size_gib DESC
LIMIT 10
```

Notice it correctly:
- Filters on `resource_type = 'AWS::EC2::Volume'` (per the system prompt rule).
- Casts `$.size` to integer for ordering.
- Casts `$.encrypted` to boolean for human-friendly output.
- Picks the exact field paths from the enriched `AWS::EC2::Volume.md`
  schema doc.

## Athena results

| volume_id | size_gib | volume_type | encrypted | account_id |
|---|---:|---|---|---|
| vol-07d4c2d3d54798063 | 4096 | development-web-app-volumetype | false | 336890980656 |
| vol-b58ea3de05eb86765 | 4096 | production-web-app-volumetype | true | 336890980656 |
| vol-e6d9ca95d95442485 | 4096 | development-auth-service-volumetype | true | 491257417623 |
| vol-aca6cf9448e8ebca9 | 4096 | development-api-service-volumetype | false | 561902006518 |
| vol-ea2d5cddb1c45ff83 | 4096 | production-data-pipeline-volumetype | false | 491257417623 |
| vol-58f9de45d21863a7f | 4096 | production-scheduler-volumetype | true | 886833016361 |
| vol-80b4b1d3b4e416257 | 4096 | production-auth-service-volumetype | true | 235447068293 |
| vol-e7801cdc2aa679a23 | 4096 | staging-api-service-volumetype | true | 481597082643 |
| vol-2090587b8f89582f8 | 4096 | development-web-app-volumetype | true | 561902006518 |
| vol-a22ab6bc91928f6be | 4096 | staging-gateway-volumetype | true | 911856239313 |

10 rows. The `volume_type` values look unrealistic because they come
from the mock generator, not from real AWS data, but the field path
extraction is correct.

## Performance

| Stage | Time |
|---|---:|
| `embed` | 695.8 ms |
| `retrieve` | 581.0 ms |
| `generate` (Claude Sonnet 4.6, ~7K input + ~150 output tokens) | 2735.9 ms |
| `athena` | 2453.0 ms |
| **total** | **6467.5 ms** |

Generation is ~2x slower than example 1 because Claude has more to do
— it has to choose between candidate JSON paths (`$.size`, `$.volumeType`,
`$.encrypted`) and decide which CASTs to apply. Still well under 3s for
the LLM, even with the full retrieved-schema context.
