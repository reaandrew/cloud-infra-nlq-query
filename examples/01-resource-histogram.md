# Example 1 — Resource histogram (single-resource aggregation)

The simplest case: count rows by `resource_type`. No JSON probing, no joins,
just a `GROUP BY` over the flat columns. Useful as a "what's even in here?"
sanity check.

## Question

> how many resources of each type are there in the account, top 15

## Retrieved schemas (top 5)

The retrieval is intentionally fuzzy here — the question doesn't name a
specific resource type, so the embedding doesn't have a strong signal.
That's fine: the generated SQL doesn't actually need any per-resource-type
field knowledge for this query.

| # | resource_type | distance | service | category |
|---|---|---:|---|---|
| 1 | `AWS::ServiceCatalog::Portfolio` | 0.7289 | ServiceCatalog | management |
| 2 | `AWS::Route53RecoveryReadiness::ResourceSet` | 0.7328 | Route53RecoveryReadiness | networking |
| 3 | `AWS::IoT::AccountAuditConfiguration` | 0.7451 | IoT | iot |
| 4 | `AWS::S3::AccountPublicAccessBlock` | 0.7460 | S3 | storage |
| 5 | `AWS::ResourceExplorer2::Index` | 0.7498 | ResourceExplorer2 | management |

## Generated SQL

```sql
SELECT
    resource_type,
    COUNT(*) AS resource_count
FROM cinq.operational_live
GROUP BY resource_type
ORDER BY resource_count DESC
LIMIT 15
```

## Athena results

| resource_type | resource_count |
|---|---:|
| AWS::EC2::Subnet | 450 |
| AWS::EC2::SecurityGroup | 450 |
| AWS::EC2::Volume | 299 |
| AWS::EC2::NetworkInterface | 240 |
| AWS::EC2::Instance | 198 |
| AWS::Lambda::Function | 163 |
| AWS::KMS::Key | 150 |
| AWS::EC2::VPC | 150 |
| AWS::S3::Bucket | 139 |
| AWS::IAM::Role | 114 |
| AWS::RDS::DBSnapshot | 104 |
| AWS::IAM::Policy | 96 |
| AWS::RDS::DBInstance | 75 |
| AWS::EFS::FileSystem | 50 |
| AWS::RDS::DBSubnetGroup | 22 |

15 rows.

## Performance

| Stage | Time |
|---|---:|
| `embed` (Titan V2, ~12 tokens) | 632.7 ms |
| `retrieve` (S3 Vectors top-5) | 518.7 ms |
| `generate` (Claude Sonnet 4.6, ~7K input + ~70 output tokens) | 1483.6 ms |
| `athena` (start + poll + fetch) | 2313.6 ms |
| **total** | **4951.5 ms** |

The fastest example in the set. Notable:
- Generation is fast (~1.5s) because Claude has very little to figure
  out — no JSON probes, no joins, just a histogram.
- Athena dominates at ~2.3s, almost all of which is start_query_execution
  + poll cycles, not actual scan time. Athena's minimum end-to-end
  latency for a one-statement query is the floor here, regardless of
  data size.
- Schema retrieval is "wasted" (5 unrelated schemas) but doesn't matter
  because the SQL doesn't use them.
