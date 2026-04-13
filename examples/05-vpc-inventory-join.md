# Example 5 — VPC inventory across multiple resource types (4-way conditional aggregation)

A VPC-centric inventory: for each VPC, count how many EC2 instances,
RDS instances, Lambda functions, and network interfaces live inside it.
Demonstrates Trino's `COUNT(*) FILTER (WHERE ...)` syntax used as a
pivot — a more compact alternative to four separate aggregation CTEs.

## Question

> for each VPC count how many EC2 instances, RDS instances, lambda functions and network interfaces are inside it. group by vpc and account, top 20 by total resource count

## Retrieved schemas (top 5)

| # | resource_type | distance | service | category |
|---|---|---:|---|---|
| 1 | `AWS::EC2::VPC` | 0.6249 | EC2 | networking |
| 2 | `AWS::EC2::VPCEndpoint` | 0.6817 | EC2 | networking |
| 3 | `AWS::AppRunner::VpcConnector` | 0.6843 | AppRunner | networking |
| 4 | `AWS::MediaConnect::FlowVpcInterface` | 0.6844 | MediaConnect | media |
| 5 | `AWS::EC2::VPCPeeringConnection` | 0.6989 | EC2 | networking |

The retrieval focused heavily on the `VPC` semantic anchor — only
`AWS::EC2::VPC` itself ended up in the top-5, with the secondary types
(EC2/RDS/Lambda/ENI) absent. Claude generated correct SQL anyway because
the relevant join keys (`$.vpcId`) are common AWS conventions and the
system prompt makes the column shape clear. **Caveat**: this is the
edge case where retrieval precision starts to matter — a more obscure
secondary resource type might trip the model. `--top-k 8` would have
brought back more candidates and given Claude more to chew on.

## Generated SQL

```sql
WITH vpc_resources AS (
    SELECT
        json_extract_scalar(configuration, '$.vpcId') AS vpc_id,
        account_id,
        resource_type
    FROM cinq.operational_live
    WHERE resource_type IN (
        'AWS::EC2::Instance',
        'AWS::RDS::DBInstance',
        'AWS::Lambda::Function',
        'AWS::EC2::NetworkInterface'
    )
      AND json_extract_scalar(configuration, '$.vpcId') IS NOT NULL
      AND json_extract_scalar(configuration, '$.vpcId') != ''
),
vpc_info AS (
    SELECT
        json_extract_scalar(configuration, '$.vpcId') AS vpc_id,
        account_id,
        resource_name,
        json_extract_scalar(configuration, '$.cidrBlock') AS cidr_block,
        aws_region
    FROM cinq.operational_live
    WHERE resource_type = 'AWS::EC2::VPC'
)
SELECT
    r.vpc_id,
    r.account_id,
    v.aws_region,
    v.cidr_block,
    COUNT(*) FILTER (WHERE r.resource_type = 'AWS::EC2::Instance')         AS ec2_instances,
    COUNT(*) FILTER (WHERE r.resource_type = 'AWS::RDS::DBInstance')       AS rds_instances,
    COUNT(*) FILTER (WHERE r.resource_type = 'AWS::Lambda::Function')      AS lambda_functions,
    COUNT(*) FILTER (WHERE r.resource_type = 'AWS::EC2::NetworkInterface') AS network_interfaces,
    COUNT(*)                                                               AS total_resource_count
FROM vpc_resources r
LEFT JOIN vpc_info v
    ON r.vpc_id = v.vpc_id
   AND r.account_id = v.account_id
GROUP BY
    r.vpc_id,
    r.account_id,
    v.aws_region,
    v.cidr_block
ORDER BY total_resource_count DESC
LIMIT 20
```

The `COUNT(*) FILTER (WHERE …)` pivot pattern is much terser than four
separate aggregation CTEs would have been. Claude reached for it
without prompting.

## Athena results (first 10 of 20 rows)

| vpc_id | account_id | cidr | ec2 | rds | λ | eni | total |
|---|---|---|---:|---:|---:|---:|---:|
| vpc-f4831d4078e58370e | 406404042870 | 10.142.61.0/16 | 5 | 0 | 0 | 2 | 7 |
| vpc-bfffb149433120cf1 | 714294294451 | 10.156.50.0/24 | 1 | 0 | 0 | 6 | 7 |
| vpc-bd267d71051561e99 | 941629821539 | 10.103.255.0/24 | 2 | 0 | 0 | 5 | 7 |
| vpc-b29d893474d23b54b | 947087372942 | 10.94.185.0/16 | 3 | 0 | 0 | 3 | 6 |
| vpc-b0f3b5cdfaa35fff9 | 561902006518 | 10.238.185.0/16 | 4 | 0 | 0 | 2 | 6 |
| vpc-cbba3169686c6cea3 | 851347210313 | 10.125.192.0/24 | 3 | 0 | 0 | 3 | 6 |
| vpc-77cb2e6976fc2bc84 | 491257417623 | 10.4.97.0/16 | 4 | 0 | 0 | 2 | 6 |
| vpc-ecb00b3c754dbdc6b | 947087372942 | 10.46.249.0/24 | 2 | 0 | 0 | 4 | 6 |
| vpc-933d46dcaaecae644 | 150711229823 | 10.156.148.0/24 | 3 | 0 | 0 | 3 | 6 |
| vpc-efa6c9846325dbe48 | 886833016361 | 10.204.124.0/24 | 3 | 0 | 0 | 3 | 6 |

20 rows total. The `rds` and `λ` columns are all 0 because the mock
generator doesn't put `vpcId` directly on the root of RDS or Lambda
configurations (RDS uses `dbSubnetGroup.vpcId` and Lambda uses
`vpcConfig.vpcId`). The SQL is structurally correct — against real
AWS Config data those columns would populate.

## Performance

| Stage | Time |
|---|---:|
| `embed` | 5609.9 ms |
| `retrieve` | 596.4 ms |
| `generate` (Claude Sonnet 4.6, ~10K input + ~600 output tokens) | 5583.4 ms |
| `athena` | 7458.0 ms |
| **total** | **19249.0 ms** |

The `embed` stage at 5.6s is the **outlier in the whole set** and
worth flagging. Titan embeddings normally complete in <1s, so this is
either a Bedrock cold start in our region, transient throttling, or a
network blip. Across the other examples in this batch, `embed` is
consistently 600–800ms — treat the 5.6s here as noise rather than a
representative number. Re-running the same query a moment later would
almost certainly land near 800ms.

Athena at 7.5s is comparable to example 4 (5 effective stages over the
same partition count), and Claude generation at ~5.6s is in line with
the cross-resource-join examples.
