# Cloud-Infra NLP Query Project Guide

## Project Architecture

This project implements an AWS-based system for querying AWS Config resources using NLP. The architecture consists of:

1. **refresh_docs_data Lambda** - Python Lambda that downloads AWS Config resource specifications
2. **chunk_config_spec Lambda** - Node.js Lambda that processes Config resources into semantic chunks
3. **fetch_vectors Lambda** - Node.js Lambda that generates vector embeddings using Amazon Titan
4. **config_query Lambda** - Node.js Lambda that handles API queries

**Data Flow:**
1. `refresh_docs_data` → S3 `cinq-config-specs` bucket
2. S3 event triggers `chunk_config_spec` → S3 `cinq-config-spec-chunks` bucket 
3. S3 event triggers `fetch_vectors` → S3 `cinq-config-vectors` bucket

## Deployment Commands

### AWS Authentication
Always use the `ee-sandbox` profile for AWS operations:
```bash
aws-vault exec ee-sandbox -- <command>
```

### Deploy Infrastructure
Deploy the entire stack (run this from the project root):
```bash
aws-vault exec ee-sandbox -- make deploy
```

This command will automatically:
1. Package all Lambda functions 
2. Apply Terraform changes
3. Deploy all resources to AWS

Package Lambda functions individually (only needed for manual testing):
```bash
./scripts/package_lambda.sh
```

### Testing

#### Starting the Pipeline

Invoke the refresh_docs_data Lambda to start the processing pipeline:
```bash
aws-vault exec ee-sandbox -- aws lambda invoke --function-name cloud-infra-nlq-query-refresh-docs --payload '{}' --log-type Tail --query 'LogResult' --output text response.json | base64 -d
```

This starts the entire workflow:
1. It downloads the AWS Config resource specifications
2. Uploads them to the S3 config_specs bucket
3. This triggers the chunk_config_spec Lambda automatically via S3 event notification
4. The chunks trigger the fetch_vectors Lambda automatically via S3 event notification

#### Monitoring the Pipeline

Check CloudWatch logs for each Lambda:
```bash
aws-vault exec ee-sandbox -- aws logs get-log-events --log-group-name /aws/lambda/cloud-infra-nlq-query-refresh-docs --limit 20
aws-vault exec ee-sandbox -- aws logs get-log-events --log-group-name /aws/lambda/cloud-infra-nlq-query-chunk-config --limit 20
aws-vault exec ee-sandbox -- aws logs get-log-events --log-group-name /aws/lambda/cloud-infra-nlq-query-fetch-vectors --limit 20
```

View data in S3 buckets:
```bash
aws-vault exec ee-sandbox -- aws s3 ls s3://cinq-config-specs/config-specs/
aws-vault exec ee-sandbox -- aws s3 ls s3://cinq-config-spec-chunks/chunks/
aws-vault exec ee-sandbox -- aws s3 ls s3://cinq-config-vectors/
```

## Project Structure

### Terraform Directories

The project uses a multi-environment Terraform structure:

- **terraform/initial_setup/** - Initial resources (state bucket, DynamoDB lock table)
- **terraform/admin_setup/** - Admin resources and permissions
- **terraform/app/** - Main application infrastructure (Lambdas, S3, IAM, API Gateway)

### Lambda Functions

- **lambda/refresh_docs_data/** (Python 3.12)
  - Fetches AWS Config resource specifications
  - Environment vars: `DEST_BUCKET`, `DEST_KEY_PREFIX`, `REGION`

- **lambda/chunk_config_spec/** (Node.js 18.x)
  - Chunks AWS Config resource specifications
  - Environment vars: `CHUNKS_BUCKET`

- **lambda/fetch_vectors/** (Node.js 18.x)
  - Generates embeddings using Amazon Titan
  - Environment vars: `VECTORS_BUCKET`, `TITAN_MODEL_ID`, `REGION`

- **lambda/config_query/** (Node.js 18.x)
  - Handles API queries
  - Environment vars: `CONFIG_DOCS_BUCKET`

## S3 Buckets

- **cinq-config-specs** - Stores AWS Config resource specifications
- **cinq-config-spec-chunks** - Stores chunked Config resources
- **cinq-config-vectors** - Stores vector embeddings
- **cloud-infra-nlq-query-config-docs** - Stores documentation

## Development Workflow

### Git Commit Conventions

Follow conventional commits:
- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `chore:` - Maintenance tasks
- `refactor:` - Code restructuring
- `test:` - Test additions or modifications

Example:
```
fix: correct S3 event notification ARN format for Lambda triggers
```

### Common Development Tasks

1. Modify Lambda code in the respective directories
2. Package the Lambda function with `./scripts/package_lambda.sh`
3. Deploy changes with `aws-vault exec ee-sandbox -- make deploy`
4. Test by invoking the refresh_docs_data Lambda and checking logs

## Troubleshooting

Common issues:
- S3 event notification not triggering Lambda → Check IAM permissions and ARN formats
- Lambda execution errors → Check CloudWatch logs for specific Lambda
- Missing vector embeddings → Verify IAM permissions for Bedrock access
  - Bedrock permissions require both:
    1. Lambda role policy with `bedrock:InvokeModel` permission (in terraform/app/main.tf)
    2. Attaching the AWS managed policy `AmazonBedrockFullAccess` to the role
    3. Correct model ID format: `amazon.titan-embed-text-v2:0` (note the `:0` version suffix)

## Environment Variables

- **REGION**: eu-west-2
- **TITAN_MODEL_ID**: amazon.titan-embed-text-v2:0
- **CHUNKS_BUCKET**: cinq-config-spec-chunks
- **VECTORS_BUCKET**: cinq-config-vectors
- **DEST_BUCKET**: cinq-config-specs
- **DEST_KEY_PREFIX**: config-specs/