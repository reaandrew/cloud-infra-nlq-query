data "archive_file" "compact" {
  type        = "zip"
  source_file = "${path.module}/../../lambda/compact/handler.py"
  output_path = "${path.module}/../../build/compact.zip"
}

resource "aws_iam_role" "compact" {
  name = "${var.app_name}-compact"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "compact" {
  role = aws_iam_role.compact.id
  name = "${var.app_name}-compact"
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
          "glue:UpdateTable",
          "glue:BatchCreatePartition",
          "glue:BatchUpdatePartition",
          "glue:BatchDeletePartition",
          "glue:CreatePartition",
          "glue:UpdatePartition",
          "glue:DeletePartition",
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
          "s3:DeleteObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
        ]
        Resource = [
          aws_s3_bucket.config.arn,
          "${aws_s3_bucket.config.arn}/*",
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "compact" {
  name              = "/aws/lambda/${var.app_name}-compact"
  retention_in_days = 14
}

resource "aws_lambda_function" "compact" {
  function_name    = "${var.app_name}-compact"
  role             = aws_iam_role.compact.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.compact.output_path
  source_code_hash = data.archive_file.compact.output_base64sha256
  memory_size      = var.compact_lambda_memory_mb
  timeout          = var.compact_lambda_timeout_seconds

  environment {
    variables = {
      GLUE_DATABASE         = var.glue_database_name
      ICEBERG_TABLE         = var.iceberg_table_name
      ATHENA_RESULTS_BUCKET = aws_s3_bucket.athena_results.bucket
      TTL_HARD_DELETE_DAYS  = tostring(var.ttl_hard_delete_days)
    }
  }

  depends_on = [
    aws_iam_role_policy.compact,
    aws_cloudwatch_log_group.compact,
    null_resource.iceberg_table,
  ]
}

resource "aws_cloudwatch_event_rule" "compact_schedule" {
  name                = "${var.app_name}-compact"
  description         = "Daily compact + TTL sweep for cinq.operational"
  schedule_expression = var.compact_schedule_cron
}

resource "aws_cloudwatch_event_target" "compact_schedule" {
  rule      = aws_cloudwatch_event_rule.compact_schedule.name
  target_id = "compact-lambda"
  arn       = aws_lambda_function.compact.arn
}

resource "aws_lambda_permission" "allow_eventbridge_compact" {
  statement_id  = "AllowEventBridgeInvokeCompact"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.compact.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.compact_schedule.arn
}
