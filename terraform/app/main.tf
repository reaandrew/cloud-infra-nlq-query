terraform {
  required_version = ">= 1.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket       = "cloud-infra-nlq-query-tfstate"
    key          = "app/terraform.tfstate"
    region       = "eu-west-2"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}

# S3 bucket for storing AWS Config documentation and examples
resource "aws_s3_bucket" "config_docs" {
  bucket = var.config_docs_bucket_name
}

resource "aws_s3_bucket_versioning" "config_docs" {
  bucket = aws_s3_bucket.config_docs.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 bucket for config specs (event source)
resource "aws_s3_bucket" "config_specs" {
  bucket = "cinq-config-specs"
}

resource "aws_s3_bucket_versioning" "config_specs" {
  bucket = aws_s3_bucket.config_specs.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 bucket for storing config spec chunks (destination)
resource "aws_s3_bucket" "config_spec_chunks" {
  bucket = "cinq-config-spec-chunks"
}

resource "aws_s3_bucket_versioning" "config_spec_chunks" {
  bucket = aws_s3_bucket.config_spec_chunks.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 bucket for storing config vector embeddings
resource "aws_s3_bucket" "config_vectors" {
  bucket = "cinq-config-vectors"
}

resource "aws_s3_bucket_versioning" "config_vectors" {
  bucket = aws_s3_bucket.config_vectors.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 event notification for chunks bucket
resource "aws_s3_bucket_notification" "config_chunks_events" {
  bucket = aws_s3_bucket.config_spec_chunks.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.fetch_vectors.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "chunks/"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_invoke_fetch_vectors,
    aws_s3_bucket.config_spec_chunks
  ]
}

# IAM role for the Lambda functions
resource "aws_iam_role" "lambda_role" {
  name = "config-query-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Attach the AWS managed Bedrock policy to the lambda roles
resource "aws_iam_role_policy_attachment" "bedrock_policy_attachment_config_query" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
}

# IAM policy for the Lambda functions
resource "aws_iam_role_policy" "lambda_policy" {
  name = "config-query-lambda-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "config:SelectAggregateResourceConfig",
          "config:SelectResourceConfig"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.config_docs.arn,
          "${aws_s3_bucket.config_docs.arn}/*",
          aws_s3_bucket.config_specs.arn,
          "${aws_s3_bucket.config_specs.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "es:ESHttpGet",
          "es:ESHttpPut",
          "es:ESHttpPost",
          "es:ESHttpDelete"
        ]
        Resource = [
          "${aws_opensearch_domain.config_vectors.arn}",
          "${aws_opensearch_domain.config_vectors.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-sonnet-20240229-v1:0"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.opensearch_credentials.arn
      }
    ]
  })
}

# Lambda function for executing Config queries
resource "aws_lambda_function" "config_query" {
  filename         = "lambda/config_query.zip"
  function_name    = "cloud-infra-nlq-query-config-query"
  role            = aws_iam_role.lambda_role.arn
  handler         = "index.handler"
  runtime         = "nodejs18.x"
  timeout         = 30
  memory_size     = 256
  source_code_hash = filebase64sha256("lambda/config_query.zip")

  environment {
    variables = {
      CONFIG_DOCS_BUCKET = aws_s3_bucket.config_docs.id
      REGION = var.aws_region
      OPENSEARCH_DOMAIN = aws_opensearch_domain.config_vectors.endpoint
      OPENSEARCH_INDEX = "config-vectors"
      TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
      OPENSEARCH_CREDS_SECRET = aws_secretsmanager_secret.opensearch_credentials.name
    }
  }
}

# Lambda function for refreshing documentation
resource "aws_lambda_function" "refresh_docs_data" {
  filename         = "lambda/refresh_docs_data.zip"
  function_name    = "cloud-infra-nlq-query-refresh-docs"
  role            = aws_iam_role.lambda_role.arn
  handler         = "lambda_function.lambda_handler"
  runtime         = "python3.12"
  timeout         = 60
  memory_size     = 256
  source_code_hash = filebase64sha256("lambda/refresh_docs_data.zip")

  environment {
    variables = {
      DEST_BUCKET = aws_s3_bucket.config_specs.id
      DEST_KEY_PREFIX = "config-specs/"
      REGION = var.aws_region
    }
  }
}

# API Gateway REST API
resource "aws_apigatewayv2_api" "config_query" {
  name          = "config-query-api"
  protocol_type = "HTTP"
}

# API Gateway integration with Lambda
resource "aws_apigatewayv2_integration" "config_query" {
  api_id           = aws_apigatewayv2_api.config_query.id
  integration_type = "AWS_PROXY"

  connection_type      = "INTERNET"
  description         = "Lambda integration"
  integration_method  = "POST"
  integration_uri     = aws_lambda_function.config_query.invoke_arn
}

# API Gateway route
resource "aws_apigatewayv2_route" "config_query" {
  api_id    = aws_apigatewayv2_api.config_query.id
  route_key = "POST /query"
  target    = "integrations/${aws_apigatewayv2_integration.config_query.id}"
}

# API Gateway stage
resource "aws_apigatewayv2_stage" "config_query" {
  api_id = aws_apigatewayv2_api.config_query.id
  name   = "prod"
  auto_deploy = true
}

# Lambda permission for API Gateway
resource "aws_lambda_permission" "config_query" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.config_query.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.config_query.execution_arn}/*/*"
}

# Lambda function for NLQ processing with Claude
resource "aws_lambda_function" "config_nlq_processor" {
  filename         = "lambda/config_nlq_processor.zip"
  function_name    = "cloud-infra-nlq-query-processor"
  role             = aws_iam_role.lambda_role.arn
  handler          = "index.handler"
  runtime          = "nodejs18.x"
  timeout          = 60   # Increased timeout for Claude processing
  memory_size      = 512  # Increased memory for vector operations and Claude
  source_code_hash = filebase64sha256("lambda/config_nlq_processor.zip")

  environment {
    variables = {
      REGION = var.aws_region
      OPENSEARCH_DOMAIN = aws_opensearch_domain.config_vectors.endpoint
      OPENSEARCH_INDEX = "config-vectors"
      TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
      CLAUDE_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
      OPENSEARCH_CREDS_SECRET = aws_secretsmanager_secret.opensearch_credentials.name
      RESULTS_LIMIT = "5"
    }
  }
}

# API Gateway route for NLQ processor
resource "aws_apigatewayv2_route" "config_nlq_processor" {
  api_id    = aws_apigatewayv2_api.config_query.id
  route_key = "POST /nlq"
  target    = "integrations/${aws_apigatewayv2_integration.config_nlq_processor.id}"
}

# API Gateway integration with NLQ processor Lambda
resource "aws_apigatewayv2_integration" "config_nlq_processor" {
  api_id           = aws_apigatewayv2_api.config_query.id
  integration_type = "AWS_PROXY"

  connection_type      = "INTERNET"
  description         = "Lambda integration for NLQ processor"
  integration_method  = "POST"
  integration_uri     = aws_lambda_function.config_nlq_processor.invoke_arn
}

# Lambda permission for API Gateway to invoke NLQ processor
resource "aws_lambda_permission" "config_nlq_processor" {
  statement_id  = "AllowAPIGatewayInvokeNLQ"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.config_nlq_processor.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.config_query.execution_arn}/*/*"
}

# IAM role for chunking Lambda
resource "aws_iam_role" "chunk_lambda_role" {
  name = "chunk-config-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "chunk_lambda_policy" {
  name = "chunk-config-lambda-policy"
  role = aws_iam_role.chunk_lambda_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject"
        ]
        Resource = [
          "${aws_s3_bucket.config_specs.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.config_spec_chunks.arn,
          "${aws_s3_bucket.config_spec_chunks.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      }
    ]
  })
}

resource "aws_lambda_function" "chunk_config" {
  filename         = "lambda/chunk_config_spec.zip"
  function_name    = "cloud-infra-nlq-query-chunk-config"
  role             = aws_iam_role.chunk_lambda_role.arn
  handler          = "index.handler"
  runtime          = "nodejs18.x"
  timeout          = 60
  memory_size      = 256
  source_code_hash = filebase64sha256("lambda/chunk_config_spec.zip")

  environment {
    variables = {
      CHUNKS_BUCKET = aws_s3_bucket.config_spec_chunks.id
    }
  }
}

# S3 event notification for source bucket
resource "aws_s3_bucket_notification" "config_spec_events" {
  bucket = aws_s3_bucket.config_specs.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.chunk_config.arn
    events              = ["s3:ObjectCreated:*"]
    filter_suffix       = ".json"
  }

  depends_on = [
    aws_lambda_permission.allow_s3_invoke_chunk_config,
    aws_s3_bucket.config_specs
  ]
}

# Lambda permission for S3 to invoke chunk_config
resource "aws_lambda_permission" "allow_s3_invoke_chunk_config" {
  statement_id  = "AllowS3InvokeChunkConfig"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.chunk_config.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.config_specs.arn
}

# IAM role for the fetch_vectors Lambda
resource "aws_iam_role" "fetch_vectors_role" {
  name = "fetch-vectors-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# Attach the AWS managed Bedrock policy to the role
resource "aws_iam_role_policy_attachment" "bedrock_policy_attachment" {
  role       = aws_iam_role.fetch_vectors_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonBedrockFullAccess"
}

# IAM policy for fetch_vectors Lambda
resource "aws_iam_role_policy" "fetch_vectors_policy" {
  name = "fetch-vectors-lambda-policy"
  role = aws_iam_role.fetch_vectors_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.config_spec_chunks.arn,
          "${aws_s3_bucket.config_spec_chunks.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject"
        ]
        Resource = [
          aws_s3_bucket.config_vectors.arn,
          "${aws_s3_bucket.config_vectors.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
      }
    ]
  })
}

# Lambda function for fetching vectors/events from chunks
resource "aws_lambda_function" "fetch_vectors" {
  filename         = "lambda/fetch_vectors.zip"
  function_name    = "cloud-infra-nlq-query-fetch-vectors"
  role             = aws_iam_role.fetch_vectors_role.arn
  handler          = "index.handler"
  runtime          = "nodejs18.x"
  timeout          = 60
  memory_size      = 256
  source_code_hash = filebase64sha256("lambda/fetch_vectors.zip")

  environment {
    variables = {
      REGION = var.aws_region
      VECTORS_BUCKET = aws_s3_bucket.config_vectors.id
      TITAN_MODEL_ID = "amazon.titan-embed-text-v2:0"
    }
  }
}

# Lambda permission for S3 to invoke fetch_vectors
resource "aws_lambda_permission" "allow_s3_invoke_fetch_vectors" {
  statement_id  = "AllowS3InvokeFetchVectors"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fetch_vectors.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.config_spec_chunks.arn
}

# Create a random password for OpenSearch master user
resource "random_password" "opensearch_master_password" {
  length  = 16
  special = true
}

# Store the master user credentials in AWS Secrets Manager
resource "aws_secretsmanager_secret" "opensearch_credentials" {
  name        = "config-vectors-opensearch-credentials"
  description = "Master user credentials for OpenSearch domain"
}

resource "aws_secretsmanager_secret_version" "opensearch_credentials" {
  secret_id = aws_secretsmanager_secret.opensearch_credentials.id
  secret_string = jsonencode({
    username = "admin"
    password = random_password.opensearch_master_password.result
  })
}

# OpenSearch Domain
resource "aws_opensearch_domain" "config_vectors" {
  domain_name    = "config-vectors-search"
  engine_version = "OpenSearch_2.5"

  cluster_config {
    instance_type          = "t3.small.search"
    instance_count         = 1
    zone_awareness_enabled = false
  }

  ebs_options {
    ebs_enabled = true
    volume_size = 10
  }

  advanced_options = {
    "rest.action.multi.allow_explicit_index" = "true"
  }

  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  # Advanced security options with master user from Secrets Manager
  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true
    master_user_options {
      master_user_name     = jsondecode(aws_secretsmanager_secret_version.opensearch_credentials.secret_string)["username"]
      master_user_password = jsondecode(aws_secretsmanager_secret_version.opensearch_credentials.secret_string)["password"]
    }
  }

  tags = {
    Domain = "config-vectors-search"
  }

  # Fine-grained access control requires a restrictive access policy
  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "*"
        }
        Action   = "es:*"
        Resource = "arn:aws:es:${var.aws_region}:${data.aws_caller_identity.current.account_id}:domain/config-vectors-search/*"
        Condition = {
          IpAddress = {
            "aws:SourceIp" = ["0.0.0.0/0"] # You should restrict this to your VPC or specific IP ranges
          }
        }
      }
    ]
  })

  depends_on = [data.aws_iam_role.opensearch_service_linked_role]
}

# Use data source to reference existing service-linked role for OpenSearch
# instead of trying to create it, since it already exists
data "aws_iam_role" "opensearch_service_linked_role" {
  name = "AWSServiceRoleForAmazonOpenSearchService"
}

# Get current AWS account ID
data "aws_caller_identity" "current" {}

# IAM role for the load_vectors_to_opensearch Lambda
resource "aws_iam_role" "load_vectors_role" {
  name = "load-vectors-opensearch-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# IAM policy for load_vectors_to_opensearch Lambda
resource "aws_iam_role_policy" "load_vectors_policy" {
  name = "load-vectors-opensearch-lambda-policy"
  role = aws_iam_role.load_vectors_role.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.config_vectors.arn,
          "${aws_s3_bucket.config_vectors.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "es:ESHttpGet",
          "es:ESHttpPut",
          "es:ESHttpPost",
          "es:ESHttpDelete"
        ]
        Resource = [
          "${aws_opensearch_domain.config_vectors.arn}",
          "${aws_opensearch_domain.config_vectors.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.opensearch_credentials.arn
      }
    ]
  })
}

# Lambda function for loading vectors into OpenSearch
resource "aws_lambda_function" "load_vectors_opensearch" {
  filename         = "lambda/load_vectors_to_opensearch.zip"
  function_name    = "cloud-infra-nlq-query-load-vectors-opensearch"
  role             = aws_iam_role.load_vectors_role.arn
  handler          = "index.handler"
  runtime          = "nodejs18.x"
  timeout          = 60
  memory_size      = 256
  source_code_hash = filebase64sha256("lambda/load_vectors_to_opensearch.zip")

  environment {
    variables = {
      REGION = var.aws_region
      OPENSEARCH_DOMAIN = aws_opensearch_domain.config_vectors.endpoint
      OPENSEARCH_INDEX = "config-vectors"
      OPENSEARCH_CREDS_SECRET = aws_secretsmanager_secret.opensearch_credentials.name
    }
  }
}

# S3 event notification for vectors bucket to trigger load_vectors_opensearch
resource "aws_s3_bucket_notification" "config_vectors_events" {
  bucket = aws_s3_bucket.config_vectors.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.load_vectors_opensearch.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [
    aws_lambda_permission.allow_s3_invoke_load_vectors,
    aws_s3_bucket.config_vectors
  ]
}

# Lambda permission for S3 to invoke load_vectors_opensearch
resource "aws_lambda_permission" "allow_s3_invoke_load_vectors" {
  statement_id  = "AllowS3InvokeLoadVectors"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.load_vectors_opensearch.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.config_vectors.arn
} 