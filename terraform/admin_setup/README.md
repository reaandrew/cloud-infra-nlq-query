# Admin Setup for Terraform Backend and CI Role

This directory contains Terraform configurations for setting up:
1. S3 bucket for Terraform state storage (with native S3 lockfile-based locking)
2. IAM role and policy for the GitHub Actions CI/CD pipeline

State locking uses Terraform's built-in S3 lockfile mechanism (`use_lockfile = true`), so no DynamoDB table is required.

## Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform >= 1.10 (for `use_lockfile` support)
- Appropriate AWS permissions to create S3 buckets and IAM roles

## Usage

1. Initialize Terraform:
```bash
terraform init
```

2. Create a `terraform.tfvars` file with your desired values (or rely on defaults):
```hcl
aws_region        = "eu-west-2"
state_bucket_name = "cloud-infra-nlq-query-tfstate"
ci_role_name      = "cloud-infra-nlq-query-ci-role"
```

3. Apply the configuration:
```bash
terraform apply
```

4. After successful apply, configure the backend for other Terraform configurations:
```bash
terraform init \
  -backend-config="bucket=cloud-infra-nlq-query-tfstate" \
  -backend-config="key=admin/terraform.tfstate" \
  -backend-config="region=eu-west-2" \
  -backend-config="use_lockfile=true"
```

## Important Notes

- The CI role is configured to be assumed by GitHub Actions via OIDC
- The CI role has permissions to access the Terraform state bucket
- Server-side encryption and versioning are enabled on the S3 bucket

## Outputs

After applying the configuration:
- S3 bucket name and ARN
- CI role ARN and name

These outputs can be used to configure your CI/CD pipeline.
