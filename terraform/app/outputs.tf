output "extract_queue_url" {
  description = "SQS queue URL that receives S3 events from the mock bucket"
  value       = aws_sqs_queue.extract.id
}

output "extract_queue_arn" {
  description = "SQS queue ARN for the extract pipeline"
  value       = aws_sqs_queue.extract.arn
}

output "extract_dlq_url" {
  description = "Dead-letter queue for failed extract Lambda invocations"
  value       = aws_sqs_queue.extract_dlq.id
}

output "operational_bucket" {
  description = "S3 bucket holding the Iceberg table data and metadata"
  value       = aws_s3_bucket.config.bucket
}

output "mock_bucket" {
  description = "S3 bucket that receives raw gzipped AWS Config snapshots"
  value       = aws_s3_bucket.config_mock.bucket
}

output "athena_results_bucket" {
  description = "S3 bucket for Athena query result staging"
  value       = aws_s3_bucket.athena_results.bucket
}

output "glue_database" {
  description = "Glue Data Catalog database holding the Iceberg table"
  value       = aws_glue_catalog_database.cinq.name
}

output "iceberg_table" {
  description = "Fully qualified Iceberg table name"
  value       = "${aws_glue_catalog_database.cinq.name}.${var.iceberg_table_name}"
}

output "iceberg_live_view" {
  description = "Fully qualified Athena view applying the TTL / freshness filter"
  value       = "${aws_glue_catalog_database.cinq.name}.${var.iceberg_view_name}"
}

output "schemas_vector_bucket" {
  description = "S3 Vectors bucket holding the resource-type schema embeddings"
  value       = var.schemas_vector_bucket
}

output "schemas_vector_index" {
  description = "S3 Vectors index name inside the schemas vector bucket"
  value       = var.schemas_vector_index
}

output "embedding_model_id" {
  description = "Bedrock model used for schema and question embeddings"
  value       = var.embedding_model_id
}

output "chat_model_id" {
  description = "Bedrock model used for NL → SQL generation"
  value       = var.chat_model_id
}

output "embedding_dimensions" {
  description = "Embedding vector dimensionality"
  value       = var.embedding_dimensions
}

# ---------- Phase 3: HTTP API ----------

output "nlq_api_endpoint" {
  description = "Custom-domain URL for the NLQ HTTP API"
  value       = "https://${var.api_domain_name}/nlq"
}

output "nlq_api_default_endpoint" {
  description = "API Gateway default endpoint (works without DNS, for testing)"
  value       = "${aws_apigatewayv2_api.nlq.api_endpoint}/nlq"
}

output "nlq_api_key_secret_arn" {
  description = "Secrets Manager ARN holding the API key. Fetch with `aws secretsmanager get-secret-value --secret-id <arn> --query SecretString --output text`"
  value       = aws_secretsmanager_secret.nlq_api_key.arn
}

output "nlq_lambda_log_group" {
  description = "CloudWatch log group for the NLQ Lambda"
  value       = aws_cloudwatch_log_group.nlq.name
}

output "spa_url" {
  description = "Public URL of the SPA front-end"
  value       = "https://${var.spa_domain_name}"
}

output "spa_bucket" {
  description = "S3 bucket holding the SPA assets"
  value       = aws_s3_bucket.spa.bucket
}

output "spa_distribution_id" {
  description = "CloudFront distribution ID for the SPA (use with create-invalidation)"
  value       = aws_cloudfront_distribution.spa.id
}
