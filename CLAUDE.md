# Cloud-Infra NLQ Query Project Guide

## Project Status

The project has been reset to a minimal baseline. Prior Lambda/OpenSearch/API Gateway
work has been removed. The current infrastructure is:

- **S3 bucket `cinq-config`** — operational store for unpacked AWS Config data
- **S3 bucket `cinq-config-mock`** — mock AWS Config data (generated via
  `scripts/generate_config_snapshot.py`)
- **S3 bucket `cloud-infra-nlq-query-tfstate`** — Terraform state (managed in
  `terraform/initial_setup/`)
- **VPC** with public subnets, internet gateway and route table (in `terraform/app/`)

Next steps will be built on top of this baseline.

## Deployment

### AWS Authentication
Always use the `ee-sandbox` profile for AWS operations:
```bash
aws-vault exec ee-sandbox -- <command>
```

### Deploy Infrastructure
From the project root:
```bash
aws-vault exec ee-sandbox -- make deploy
```

This runs `terraform apply` in `terraform/app/`.

## Project Structure

### Terraform

- **terraform/initial_setup/** — Terraform state bucket
- **terraform/admin_setup/** — Admin resources and OIDC trust for CI/CD
- **terraform/app/** — Main application infrastructure (S3 buckets, VPC)

### Scripts

- **scripts/generate_config_snapshot.py** — Schema-driven mock AWS Config snapshot generator
- **scripts/fetch_config_resource_schemas.sh** — Fetches AWS Config resource schemas from
  the awslabs repository (output is gitignored under `data/config_resource_schemas/`)
- **scripts/config_profiles.json** — Profile definitions for the snapshot generator

## Development Workflow

### Git Commit Conventions

Follow conventional commits:
- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `chore:` - Maintenance tasks
- `refactor:` - Code restructuring
- `test:` - Test additions or modifications

## Environment

- **REGION**: eu-west-2
