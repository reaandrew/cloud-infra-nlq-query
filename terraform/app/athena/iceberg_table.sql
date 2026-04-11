CREATE TABLE IF NOT EXISTS ${database}.${table_name} (
  account_id string,
  arn string,
  resource_type string,
  resource_id string,
  resource_name string,
  aws_region string,
  availability_zone string,
  status string,
  captured_at timestamp,
  created_at timestamp,
  state_id string,
  state_hash string,
  tags string,
  relationships string,
  configuration string,
  supplementary_configuration string,
  last_seen_at timestamp,
  source_key string
)
PARTITIONED BY (account_id)
LOCATION 's3://${bucket}/operational/'
TBLPROPERTIES (
  'table_type' = 'ICEBERG',
  'format' = 'parquet',
  'write_compression' = 'zstd'
)
