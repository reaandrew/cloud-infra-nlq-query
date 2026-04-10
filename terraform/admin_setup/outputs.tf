output "state_bucket_name" {
  description = "Name of the S3 bucket for Terraform state"
  value       = var.state_bucket_name
}

output "state_bucket_arn" {
  description = "ARN of the S3 bucket for Terraform state"
  value       = "arn:aws:s3:::${var.state_bucket_name}"
}

output "ci_role_arn" {
  description = "ARN of the CI IAM role"
  value       = aws_iam_role.ci_role.arn
}

output "ci_role_name" {
  description = "Name of the CI IAM role"
  value       = aws_iam_role.ci_role.name
} 