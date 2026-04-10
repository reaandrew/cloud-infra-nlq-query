variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "eu-west-2"
}

variable "state_bucket_name" {
  description = "Name of the S3 bucket for Terraform state"
  type        = string
  default     = "cloud-infra-nlq-query-tfstate"
}

variable "ci_role_name" {
  description = "Name of the CI IAM role"
  type        = string
  default     = "cloud-infra-nlq-query-ci-role"
}

variable "app_name" {
  description = "Name of the application"
  type        = string
  default     = "cloud-infra-nlq-query"
}
