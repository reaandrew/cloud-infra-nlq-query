variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "eu-west-2"
}

variable "app_name" {
  description = "Name of the application"
  type        = string
  default     = "cloud-infra-nlq-query"
}

variable "config_bucket_name" {
  description = "Name of the S3 bucket for operational AWS Config data. A second bucket with a '-mock' suffix is also created."
  type        = string
  default     = "cinq-config"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for public subnets (one per AZ)"
  type        = list(string)
  default     = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "glue_database_name" {
  description = "Glue Data Catalog database that holds the Iceberg table"
  type        = string
  default     = "cinq"
}

variable "iceberg_table_name" {
  description = "Iceberg table name for the flattened operational AWS Config data"
  type        = string
  default     = "operational"
}

variable "iceberg_view_name" {
  description = "Athena view name exposing the TTL-filtered, deduped live view"
  type        = string
  default     = "operational_live"
}

variable "ttl_view_hours" {
  description = "Soft TTL: rows older than this are hidden by the operational_live view"
  type        = number
  default     = 24
}

variable "ttl_hard_delete_days" {
  description = "Hard TTL: rows older than this are physically deleted by the compact Lambda"
  type        = number
  default     = 7
}

variable "compact_schedule_cron" {
  description = "EventBridge cron expression for the compact Lambda (UTC)"
  type        = string
  default     = "cron(0 3 * * ? *)"
}

variable "mock_retention_days" {
  description = "Days to retain current objects in cinq-config-mock"
  type        = number
  default     = 14
}

variable "mock_noncurrent_retention_days" {
  description = "Days to retain noncurrent object versions in cinq-config-mock"
  type        = number
  default     = 1
}

variable "extract_batch_size" {
  description = "Max SQS records per extract Lambda invocation"
  type        = number
  default     = 25
}

variable "extract_batch_window_seconds" {
  description = "SQS batching window for the extract Lambda"
  type        = number
  default     = 60
}

variable "extract_reserved_concurrency" {
  description = "Reserved concurrency cap on the extract Lambda. Caps concurrent Iceberg writers to avoid commit storms."
  type        = number
  default     = 5
}

variable "extract_lambda_memory_mb" {
  description = "Memory allocated to the extract Lambda"
  type        = number
  default     = 2048
}

variable "extract_lambda_timeout_seconds" {
  description = "Timeout for the extract Lambda"
  type        = number
  default     = 300
}

variable "compact_lambda_memory_mb" {
  description = "Memory allocated to the compact Lambda"
  type        = number
  default     = 1024
}

variable "compact_lambda_timeout_seconds" {
  description = "Timeout for the compact Lambda"
  type        = number
  default     = 900
}

variable "sdk_pandas_layer_arn" {
  description = "ARN of the AWS SDK for pandas managed Lambda layer (Python 3.12). Bundles pyarrow + pandas + boto3 + awswrangler so the extract Lambda doesn't need ECR/container images."
  type        = string
  default     = "arn:aws:lambda:eu-west-2:336392948345:layer:AWSSDKPandas-Python312:20"
}

# ---------- Phase 2: Schema RAG (S3 Vectors + Bedrock) ----------

variable "schemas_vector_bucket" {
  description = "S3 Vectors bucket holding the resource-type schema embeddings"
  type        = string
  default     = "cinq-schemas-vectors"
}

variable "schemas_vector_index" {
  description = "S3 Vectors index inside the schemas vector bucket"
  type        = string
  default     = "cinq-schemas-index"
}

variable "embedding_dimensions" {
  description = "Embedding dimensions for the schema vectors. Titan Text Embeddings V2 supports 1024 (default), 512, or 256."
  type        = number
  default     = 1024
}

variable "vector_distance_metric" {
  description = "Similarity metric for the schema vector index. Cosine is conventional for normalised embeddings."
  type        = string
  default     = "cosine"
}

variable "embedding_model_id" {
  description = "Bedrock model ID for embedding generation (Titan Text Embeddings V2)."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "chat_model_id" {
  description = "Bedrock model ID for natural language to SQL generation. Verified ON_DEMAND in eu-west-2 as of phase 2 build."
  type        = string
  default     = "anthropic.claude-sonnet-4-6"
}

# ---------- Phase 3: HTTP API ----------

variable "api_domain_name" {
  description = "Custom domain name for the NLQ HTTP API"
  type        = string
  default     = "api.nlq.demos.apps.equal.expert"
}

variable "api_dns_zone_name" {
  description = "Route 53 hosted zone that owns the api_domain_name. The zone must already exist in this account."
  type        = string
  default     = "demos.apps.equal.expert"
}

variable "nlq_lambda_memory_mb" {
  description = "Memory allocated to the NLQ HTTP API Lambda"
  type        = number
  default     = 1024
}

variable "nlq_lambda_timeout_seconds" {
  description = "Timeout for the NLQ HTTP API Lambda. Must accommodate Bedrock + Athena round trips."
  type        = number
  default     = 90
}
