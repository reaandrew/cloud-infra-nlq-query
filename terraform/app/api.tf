# NLQ HTTP API on API Gateway v2 with custom domain.
#
# Flow per request:
#   curl https://api.nlq.demos.apps.equal.expert/nlq
#       -H 'x-api-key: <secret>'
#       -d '{"question":"..."}'
#     │
#     ▼
#   API Gateway v2 (HTTP API)
#     │
#     ├─ Lambda authoriser (REQUEST type, simple-response) checks x-api-key
#     │   against value held in Secrets Manager. 5-min auth cache.
#     │
#     ▼
#   NLQ Lambda (zip + bundled boto3 + bundled enriched_schemas/)
#     │
#     ├─ Titan embed → S3 Vectors top-K → Claude SQL → Athena execute
#     ▼
#   JSON response

# ---------- API key ----------

resource "random_password" "nlq_api_key" {
  length           = 40
  special          = false
  override_special = "" # alnum only — easier for curl users
}

resource "aws_secretsmanager_secret" "nlq_api_key" {
  name                    = "${var.app_name}-nlq-api-key"
  description             = "API key for the NLQ HTTP API custom domain. Use as the x-api-key header."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "nlq_api_key" {
  secret_id     = aws_secretsmanager_secret.nlq_api_key.id
  secret_string = random_password.nlq_api_key.result
}

# ---------- NLQ Lambda (POST /nlq) ----------

resource "null_resource" "nlq_lambda_package" {
  triggers = {
    handler_sha   = filesha256("${path.module}/../../lambda/nlq/handler.py")
    packager_sha  = filesha256("${path.module}/../../scripts/package_nlq_lambda.sh")
    schemas_count = length(fileset("${path.module}/../../data/enriched_schemas", "*.md"))
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = "${path.module}/../../scripts/package_nlq_lambda.sh"
  }
}

data "archive_file" "nlq" {
  type        = "zip"
  source_dir  = "${path.module}/../../build/nlq"
  output_path = "${path.module}/../../build/nlq.zip"
  depends_on  = [null_resource.nlq_lambda_package]
}

resource "aws_iam_role" "nlq" {
  name = "${var.app_name}-nlq"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "nlq" {
  role = aws_iam_role.nlq.id
  name = "${var.app_name}-nlq"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      },
      {
        # var.chat_model_id can be either a foundation-model ID or an
        # inference-profile ID (e.g. global.anthropic.claude-sonnet-4-6
        # load-balances across many regions). Both need to be granted, and
        # the profile routes requests to multiple underlying foundation
        # models so the resource scope has to cover all of them.
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        Resource = [
          "arn:aws:bedrock:*::foundation-model/*",
          "arn:aws:bedrock:*:*:inference-profile/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3vectors:QueryVectors",
          "s3vectors:GetVectors",
          "s3vectors:ListVectors",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
          "athena:GetWorkGroup",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:*:catalog",
          "arn:aws:glue:${var.aws_region}:*:database/${var.glue_database_name}",
          "arn:aws:glue:${var.aws_region}:*:table/${var.glue_database_name}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*",
          aws_s3_bucket.config.arn,
          "${aws_s3_bucket.config.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "nlq" {
  name              = "/aws/lambda/${var.app_name}-nlq"
  retention_in_days = 14
}

resource "aws_lambda_function" "nlq" {
  function_name    = "${var.app_name}-nlq"
  role             = aws_iam_role.nlq.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.nlq.output_path
  source_code_hash = data.archive_file.nlq.output_base64sha256
  memory_size      = var.nlq_lambda_memory_mb
  timeout          = var.nlq_lambda_timeout_seconds

  environment {
    variables = {
      GLUE_DATABASE         = var.glue_database_name
      ICEBERG_VIEW          = var.iceberg_view_name
      EMBED_MODEL_ID        = var.embedding_model_id
      CHAT_MODEL_ID         = var.chat_model_id
      EMBED_DIMENSIONS      = tostring(var.embedding_dimensions)
      SCHEMAS_VECTOR_BUCKET = var.schemas_vector_bucket
      SCHEMAS_VECTOR_INDEX  = var.schemas_vector_index
      ATHENA_RESULTS_BUCKET = aws_s3_bucket.athena_results.bucket
      ATHENA_WORKGROUP      = "primary"
    }
  }

  depends_on = [
    aws_iam_role_policy.nlq,
    aws_cloudwatch_log_group.nlq,
  ]
}

# ---------- Stats Lambda (unauthenticated GET /stats/*) ----------

data "archive_file" "stats" {
  type        = "zip"
  source_file = "${path.module}/../../lambda/stats/handler.py"
  output_path = "${path.module}/../../build/stats.zip"
}

resource "aws_iam_role" "stats" {
  name = "${var.app_name}-stats"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "stats" {
  role = aws_iam_role.stats.id
  name = "${var.app_name}-stats"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:StopQueryExecution",
          "athena:GetWorkGroup",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "glue:GetDatabase",
          "glue:GetDatabases",
          "glue:GetTable",
          "glue:GetTables",
          "glue:GetPartition",
          "glue:GetPartitions",
        ]
        Resource = [
          "arn:aws:glue:${var.aws_region}:*:catalog",
          "arn:aws:glue:${var.aws_region}:*:database/${var.glue_database_name}",
          "arn:aws:glue:${var.aws_region}:*:table/${var.glue_database_name}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*",
          aws_s3_bucket.config.arn,
          "${aws_s3_bucket.config.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "stats" {
  name              = "/aws/lambda/${var.app_name}-stats"
  retention_in_days = 14
}

resource "aws_lambda_function" "stats" {
  function_name    = "${var.app_name}-stats"
  role             = aws_iam_role.stats.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.stats.output_path
  source_code_hash = data.archive_file.stats.output_base64sha256
  memory_size      = 512
  timeout          = 30

  environment {
    variables = {
      GLUE_DATABASE         = var.glue_database_name
      ICEBERG_VIEW          = var.iceberg_view_name
      ATHENA_RESULTS_BUCKET = aws_s3_bucket.athena_results.bucket
      ATHENA_WORKGROUP      = "primary"
    }
  }

  depends_on = [
    aws_iam_role_policy.stats,
    aws_cloudwatch_log_group.stats,
  ]
}

resource "aws_apigatewayv2_integration" "stats" {
  api_id                 = aws_apigatewayv2_api.nlq.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.stats.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "stats_overview" {
  api_id    = aws_apigatewayv2_api.nlq.id
  route_key = "GET /stats/overview"
  target    = "integrations/${aws_apigatewayv2_integration.stats.id}"
}

resource "aws_apigatewayv2_route" "stats_by_type" {
  api_id    = aws_apigatewayv2_api.nlq.id
  route_key = "GET /stats/by-type"
  target    = "integrations/${aws_apigatewayv2_integration.stats.id}"
}

resource "aws_apigatewayv2_route" "stats_by_account" {
  api_id    = aws_apigatewayv2_api.nlq.id
  route_key = "GET /stats/by-account"
  target    = "integrations/${aws_apigatewayv2_integration.stats.id}"
}

resource "aws_apigatewayv2_route" "stats_by_region" {
  api_id    = aws_apigatewayv2_api.nlq.id
  route_key = "GET /stats/by-region"
  target    = "integrations/${aws_apigatewayv2_integration.stats.id}"
}

resource "aws_lambda_permission" "stats_apigw" {
  statement_id  = "AllowAPIGatewayInvokeStats"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.stats.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.nlq.execution_arn}/*/*"
}

# ---------- Authoriser Lambda ----------

data "archive_file" "nlq_auth" {
  type        = "zip"
  source_file = "${path.module}/../../lambda/nlq_auth/handler.py"
  output_path = "${path.module}/../../build/nlq_auth.zip"
}

resource "aws_iam_role" "nlq_auth" {
  name = "${var.app_name}-nlq-auth"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "nlq_auth" {
  role = aws_iam_role.nlq_auth.id
  name = "${var.app_name}-nlq-auth"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:${var.aws_region}:*:*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.nlq_api_key.arn
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "nlq_auth" {
  name              = "/aws/lambda/${var.app_name}-nlq-auth"
  retention_in_days = 14
}

resource "aws_lambda_function" "nlq_auth" {
  function_name    = "${var.app_name}-nlq-auth"
  role             = aws_iam_role.nlq_auth.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.nlq_auth.output_path
  source_code_hash = data.archive_file.nlq_auth.output_base64sha256
  memory_size      = 256
  timeout          = 10

  environment {
    variables = {
      API_KEY_SECRET_ARN = aws_secretsmanager_secret.nlq_api_key.arn
    }
  }

  depends_on = [
    aws_iam_role_policy.nlq_auth,
    aws_cloudwatch_log_group.nlq_auth,
  ]
}

# ---------- API Gateway v2 (HTTP API) ----------

resource "aws_apigatewayv2_api" "nlq" {
  name          = "${var.app_name}-nlq"
  protocol_type = "HTTP"
  description   = "NLQ HTTP API — POST /nlq returns JSON results from Athena"

  cors_configuration {
    allow_methods  = ["GET", "POST", "OPTIONS"]
    allow_origins  = ["*"]
    allow_headers  = ["content-type", "x-api-key", "authorization"]
    expose_headers = ["content-type", "cache-control"]
    max_age        = 300
  }
}

resource "aws_apigatewayv2_integration" "nlq" {
  api_id                 = aws_apigatewayv2_api.nlq.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.nlq.invoke_arn
  integration_method     = "POST"
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000 # API GW HTTP API hard cap is 30s
}

resource "aws_apigatewayv2_authorizer" "nlq" {
  api_id                            = aws_apigatewayv2_api.nlq.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.nlq_auth.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  identity_sources                  = ["$request.header.x-api-key"]
  name                              = "${var.app_name}-nlq-auth"
  authorizer_result_ttl_in_seconds  = 300
}

resource "aws_apigatewayv2_route" "nlq_post" {
  api_id             = aws_apigatewayv2_api.nlq.id
  route_key          = "POST /nlq"
  target             = "integrations/${aws_apigatewayv2_integration.nlq.id}"
  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.nlq.id
}

resource "aws_apigatewayv2_stage" "nlq" {
  api_id      = aws_apigatewayv2_api.nlq.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 50
    throttling_rate_limit  = 10
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.nlq_access.arn
    format = jsonencode({
      requestId          = "$context.requestId"
      ip                 = "$context.identity.sourceIp"
      requestTime        = "$context.requestTime"
      httpMethod         = "$context.httpMethod"
      routeKey           = "$context.routeKey"
      status             = "$context.status"
      protocol           = "$context.protocol"
      responseLength     = "$context.responseLength"
      integrationLatency = "$context.integrationLatency"
      authorizerError    = "$context.authorizer.error"
    })
  }
}

resource "aws_cloudwatch_log_group" "nlq_access" {
  name              = "/aws/apigateway/${var.app_name}-nlq"
  retention_in_days = 14
}

resource "aws_lambda_permission" "nlq_apigw" {
  statement_id  = "AllowAPIGatewayInvokeNLQ"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.nlq.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.nlq.execution_arn}/*/*"
}

resource "aws_lambda_permission" "nlq_auth_apigw" {
  statement_id  = "AllowAPIGatewayInvokeNLQAuth"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.nlq_auth.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.nlq.execution_arn}/authorizers/${aws_apigatewayv2_authorizer.nlq.id}"
}

# ---------- Custom domain + ACM cert + Route 53 ----------

data "aws_route53_zone" "api" {
  name         = var.api_dns_zone_name
  private_zone = false
}

resource "aws_acm_certificate" "api" {
  domain_name       = var.api_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "api_validation" {
  for_each = {
    for dvo in aws_acm_certificate.api.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  zone_id         = data.aws_route53_zone.api.zone_id
  name            = each.value.name
  type            = each.value.type
  records         = [each.value.record]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "api" {
  certificate_arn         = aws_acm_certificate.api.arn
  validation_record_fqdns = [for r in aws_route53_record.api_validation : r.fqdn]
}

resource "aws_apigatewayv2_domain_name" "nlq" {
  domain_name = var.api_domain_name

  domain_name_configuration {
    certificate_arn = aws_acm_certificate_validation.api.certificate_arn
    endpoint_type   = "REGIONAL"
    security_policy = "TLS_1_2"
  }
}

resource "aws_apigatewayv2_api_mapping" "nlq" {
  api_id      = aws_apigatewayv2_api.nlq.id
  domain_name = aws_apigatewayv2_domain_name.nlq.id
  stage       = aws_apigatewayv2_stage.nlq.id
}

resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.api.zone_id
  name    = var.api_domain_name
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.nlq.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.nlq.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
