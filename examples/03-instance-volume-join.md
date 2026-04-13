# Example 3 — EC2 Instance ↔ EBS Volume cross-resource join

The first real cross-resource example. Two CTEs over the same table —
one filtered to `AWS::EC2::Instance`, one filtered to `AWS::EC2::Volume`
— joined on the `attachments[0].instanceId` value extracted from the
Volume's `configuration` JSON.

This is the pattern that's only possible because every AWS Config
resource type lives in a single Iceberg table. In a vanilla Config
deployment you'd be making per-account API calls and joining in
application code.

## Question

> for each EC2 instance show the volumes attached to it. join EC2::Instance with EC2::Volume on the attachment instance ID. limit to 20 rows

## Retrieved schemas (top 5)

| # | resource_type | distance | service | category |
|---|---|---:|---|---|
| 1 | `AWS::EC2::Volume` | 0.5696 | EC2 | storage |
| 2 | `AWS::SSM::ManagedInstanceInventory` | 0.6674 | SSM | management |
| 3 | `AWS::ServiceDiscovery::Instance` | 0.6846 | ServiceDiscovery | networking |
| 4 | `AWS::EC2::FlowLog` | 0.6914 | EC2 | networking |
| 5 | `AWS::EC2::Instance` | 0.7077 | EC2 | compute |

Both required schemas (`Volume` and `Instance`) are in the top-5,
which is what makes this query work — Claude sees both schema docs and
can cross-reference field paths between them. With a smaller `--top-k`
the second resource might have missed the cut.

## Generated SQL

```sql
WITH instances AS (
    SELECT
        account_id,
        aws_region,
        resource_id   AS instance_id,
        resource_name AS instance_name,
        json_extract_scalar(configuration, '$.state.name')    AS instance_state,
        json_extract_scalar(configuration, '$.instanceType')  AS instance_type
    FROM cinq.operational_live
    WHERE resource_type = 'AWS::EC2::Instance'
),
volumes AS (
    SELECT
        account_id,
        aws_region,
        resource_id AS volume_id,
        json_extract_scalar(configuration, '$.volumeType')                          AS volume_type,
        CAST(json_extract_scalar(configuration, '$.size') AS INTEGER)               AS size_gib,
        json_extract_scalar(configuration, '$.state.value')                         AS volume_state,
        json_extract_scalar(configuration, '$.encrypted')                           AS encrypted,
        json_extract_scalar(configuration, '$.attachments[0].instanceId')           AS attached_instance_id,
        json_extract_scalar(configuration, '$.attachments[0].device')               AS device_name,
        json_extract_scalar(configuration, '$.attachments[0].deleteOnTermination')  AS delete_on_termination
    FROM cinq.operational_live
    WHERE resource_type = 'AWS::EC2::Volume'
)
SELECT
    i.account_id,
    i.aws_region,
    i.instance_id,
    i.instance_name,
    i.instance_state,
    i.instance_type,
    v.volume_id,
    v.volume_type,
    v.size_gib,
    v.volume_state,
    v.encrypted,
    v.device_name,
    v.delete_on_termination
FROM instances i
JOIN volumes v
    ON i.instance_id = v.attached_instance_id
   AND i.account_id = v.account_id
ORDER BY i.instance_id, v.device_name
LIMIT 20
```

The join keys are `instance_id` (extracted from Volume's
`attachments[0].instanceId`) and `account_id` (a flat column on both
sides — important so volumes from one account don't accidentally join
with instances from another). Claude added the `account_id` join
condition without being asked, which is the correct safety behaviour.

## Athena results (first 10 of 20 rows shown)

| account_id | instance_id | instance_name | type | volume_id | size_gib | encrypted | device |
|---|---|---|---|---|---:|---|---|
| 871590378377 | i-0389ae1860b797020 | test-api-service-instance | t3.medium | vol-abb81a150bc480b2a | 128 | true | development-gateway-device |
| 871590378377 | i-0389ae1860b797020 | test-api-service-instance | t3.medium | vol-5f4770ce836460861 | 512 | true | production-data-pipeline-device |
| 354342113419 | i-03f7c5ecb16464899 | development-web-app-instance | t3.small | vol-a9edac5b79628f81d | 4096 | true | development-worker-device |
| 354342113419 | i-03f7c5ecb16464899 | development-web-app-instance | t3.small | vol-acc84b84f0e2afbf8 | 512 | true | staging-scheduler-device |
| 684850587137 | i-060dacaf376047c88 | staging-monitoring-instance | t3.medium | vol-481243c747e2cdcdd | 2048 | true | production-web-app-device |
| 684850587137 | i-060dacaf376047c88 | staging-monitoring-instance | t3.medium | vol-be17011d4831b9ad4 | 4096 | true | staging-auth-service-device |
| 406404042870 | i-06c2b772cfe1b11e3 | production-web-app-instance | t3.micro | vol-b0fdfb25b7013b1b7 | 512 | false | production-gateway-device |
| 180092702123 | i-09c37df52894f2b66 | production-data-pipeline-instance | m5.large | vol-fa941da727209e996 | 512 | true | production-scheduler-device |
| 180092702123 | i-09c37df52894f2b66 | production-data-pipeline-instance | m5.large | vol-f2a6b18cddcf61cc2 | 1024 | false | staging-api-service-device |
| 136171878809 | i-0e07dbdb6e4b05cc4 | staging-data-pipeline-instance | t3.small | vol-b202c420f6830df29 | 256 | true | production-monitoring-device |

20 rows total. Each instance shows up multiple times — once per attached
volume — which is exactly what an instance↔volume join should produce.

## Performance

| Stage | Time |
|---|---:|
| `embed` | 686.5 ms |
| `retrieve` | 614.5 ms |
| `generate` (Claude Sonnet 4.6, ~14K input + ~700 output tokens) | 5984.9 ms |
| `athena` | 2470.5 ms |
| **total** | **9758.1 ms** |

Generation has jumped to ~6s because Claude is producing a much longer
response (the full WITH-CTE structure is several hundred output tokens)
and reasoning about two schemas instead of one. This is consistent with
Bedrock's tokens-per-second throughput for Sonnet 4.6 — output tokens
are the slow path. Athena is still the same ~2.5s baseline.
