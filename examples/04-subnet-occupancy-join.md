# Example 4 — Subnet ↔ Instance ↔ Network Interface (3-way cross-resource join)

A more substantial three-resource-type join: count how many EC2 instances
and ENIs live in each subnet. The pattern generalises to any "what's in
this network primitive" question.

## Question

> for each subnet count how many EC2 instances and network interfaces are inside it. join EC2::Subnet with EC2::Instance and EC2::NetworkInterface on the subnetId. show top 15 subnets by total

## Retrieved schemas (top 5)

The retrieval picked all three required resource types plus two adjacent
ones — exactly the right shape for a three-way join.

| # | resource_type | distance | service | category |
|---|---|---:|---|---|
| 1 | `AWS::EC2::Subnet` | ~ | EC2 | networking |
| 2 | `AWS::EC2::NetworkInterface` | ~ | EC2 | networking |
| 3 | `AWS::EC2::Instance` | ~ | EC2 | compute |
| 4 | `AWS::EC2::SubnetNetworkAclAssociation` | ~ | EC2 | networking |
| 5 | `AWS::EC2::SubnetRouteTableAssociation` | ~ | EC2 | networking |

## Generated SQL

```sql
WITH subnets AS (
    SELECT
        account_id,
        aws_region,
        resource_id   AS subnet_id,
        resource_name AS subnet_name,
        json_extract_scalar(configuration, '$.vpcId')             AS vpc_id,
        json_extract_scalar(configuration, '$.cidrBlock')         AS cidr_block,
        json_extract_scalar(configuration, '$.availabilityZone')  AS az
    FROM cinq.operational_live
    WHERE resource_type = 'AWS::EC2::Subnet'
),
instances AS (
    SELECT
        account_id,
        json_extract_scalar(configuration, '$.subnetId') AS subnet_id
    FROM cinq.operational_live
    WHERE resource_type = 'AWS::EC2::Instance'
      AND json_extract_scalar(configuration, '$.subnetId') IS NOT NULL
),
network_interfaces AS (
    SELECT
        account_id,
        json_extract_scalar(configuration, '$.subnetId') AS subnet_id
    FROM cinq.operational_live
    WHERE resource_type = 'AWS::EC2::NetworkInterface'
      AND json_extract_scalar(configuration, '$.subnetId') IS NOT NULL
),
ec2_counts AS (
    SELECT account_id, subnet_id, COUNT(*) AS ec2_instance_count
    FROM instances
    GROUP BY account_id, subnet_id
),
eni_counts AS (
    SELECT account_id, subnet_id, COUNT(*) AS network_interface_count
    FROM network_interfaces
    GROUP BY account_id, subnet_id
)
SELECT
    s.subnet_id,
    s.subnet_name,
    s.account_id,
    s.aws_region,
    s.az,
    s.vpc_id,
    s.cidr_block,
    COALESCE(e.ec2_instance_count, 0)       AS ec2_instance_count,
    COALESCE(n.network_interface_count, 0)  AS network_interface_count,
    COALESCE(e.ec2_instance_count, 0)
      + COALESCE(n.network_interface_count, 0) AS total_resources
FROM subnets s
LEFT JOIN ec2_counts e
    ON s.subnet_id = e.subnet_id AND s.account_id = e.account_id
LEFT JOIN eni_counts n
    ON s.subnet_id = n.subnet_id AND s.account_id = n.account_id
ORDER BY total_resources DESC
LIMIT 15
```

Five CTEs, two `LEFT JOIN`s, and `COALESCE` to handle subnets with no
attached resources. Claude got the full pattern in one shot.

## Athena results

| subnet_id | subnet_name | account_id | az | vpc_id | cidr | ec2 | eni | total |
|---|---|---|---|---|---|---:|---:|---:|
| subnet-fe46f81695371ab47 | staging-gateway-subnet | 947087372942 | eu-west-2c | vpc-ecb00b3c754dbdc6b | 10.60.222.0/24 | 2 | 3 | 5 |
| subnet-90212592ebe1925fa | staging-data-pipeline-subnet | 481597082643 | eu-west-2a | vpc-372bf387c7bb4cb01 | 10.242.94.0/24 | 3 | 1 | 4 |
| subnet-f7a846e513835fad8 | development-scheduler-subnet | 748913461122 | eu-west-2c | vpc-3514767ff60a0e9d1 | 10.115.139.0/28 | 1 | 3 | 4 |
| subnet-2d78566498762f4cc | production-auth-service-subnet | 407473554860 | eu-west-2b | vpc-e13e47d561d523a0b | 10.113.225.0/28 | 0 | 4 | 4 |
| subnet-f980dd2606355a867 | test-worker-subnet | 941629821539 | eu-west-2a | vpc-bd267d71051561e99 | 10.120.95.0/24 | 1 | 3 | 4 |
| subnet-c1c8489b476df5473 | development-gateway-subnet | 714294294451 | eu-west-2b | vpc-bfffb149433120cf1 | 10.0.39.0/28 | 1 | 3 | 4 |
| subnet-24d75aff555816ed1 | production-monitoring-subnet | 491257417623 | eu-west-2a | vpc-77cb2e6976fc2bc84 | 10.251.174.0/28 | 2 | 2 | 4 |
| subnet-14a3e2f69972dfe9c | staging-scheduler-subnet | 826046287257 | eu-west-2a | vpc-c9621fddcaf1b3704 | 10.32.215.0/24 | 2 | 1 | 3 |
| subnet-7b342a3a585a6f20c | production-scheduler-subnet | 947087372942 | eu-west-2b | vpc-b29d893474d23b54b | 10.1.142.0/16 | 2 | 1 | 3 |
| subnet-95748a8ce593ee3d8 | production-data-pipeline-subnet | 714294294451 | eu-west-2c | vpc-7611757b213086603 | 10.162.64.0/28 | 0 | 3 | 3 |

15 rows total. Note the row with 0 EC2 instances but 4 ENIs — the
`LEFT JOIN` + `COALESCE` correctly surfaces "ENIs in a subnet with no
instances", which is the kind of orphan-detection signal you want.

## Performance

| Stage | Time |
|---|---:|
| `embed` | 706.1 ms |
| `retrieve` | 599.0 ms |
| `generate` (Claude Sonnet 4.6, ~16K input + ~900 output tokens) | 6660.1 ms |
| `athena` | 7487.6 ms |
| **total** | **15455.4 ms** |

Two interesting jumps from example 3:
- **Generation** at ~6.7s — slightly more output tokens than the 2-way
  join example (5 CTEs vs 2), proportional to expectation.
- **Athena** at ~7.5s vs ~2.5s — this is the first query where the
  scan size and the number of stages are large enough that the engine
  spends meaningful CPU on actual work, not just startup. Five CTEs
  scanning the same table effectively do 5 reads of the partition,
  then a hash-aggregate, then two LEFT JOIN bucket-shuffles. Still
  well under 10s for a 2700-row table — would be ~20s for 1M rows
  and remain interactive.
