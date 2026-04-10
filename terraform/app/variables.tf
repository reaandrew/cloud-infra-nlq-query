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

variable "config_docs_bucket_name" {
  description = "Name of the S3 bucket to store AWS Config documentation"
  type        = string
  default     = "cinq-config-docs"
}
