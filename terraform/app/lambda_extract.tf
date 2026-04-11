data "archive_file" "extract" {
  type        = "zip"
  source_file = "${path.module}/../../lambda/extract/handler.py"
  output_path = "${path.module}/../../build/extract.zip"
}

resource "aws_iam_role" "extract" {
  name = "${var.app_name}-extract"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "extract" {
  role = aws_iam_role.extract.id
  name = "${var.app_name}-extract"
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
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:ChangeMessageVisibility",
        ]
        Resource = aws_sqs_queue.extract.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.config_mock.arn,
          "${aws_s3_bucket.config_mock.arn}/*",
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
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
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
    ]
  })
}

resource "aws_cloudwatch_log_group" "extract" {
  name              = "/aws/lambda/${var.app_name}-extract"
  retention_in_days = 14
}

resource "aws_lambda_function" "extract" {
  function_name                  = "${var.app_name}-extract"
  role                           = aws_iam_role.extract.arn
  runtime                        = "python3.12"
  handler                        = "handler.handler"
  filename                       = data.archive_file.extract.output_path
  source_code_hash               = data.archive_file.extract.output_base64sha256
  memory_size                    = var.extract_lambda_memory_mb
  timeout                        = var.extract_lambda_timeout_seconds
  reserved_concurrent_executions = var.extract_reserved_concurrency
  layers                         = [var.sdk_pandas_layer_arn]

  environment {
    variables = {
      GLUE_DATABASE         = var.glue_database_name
      ICEBERG_TABLE         = var.iceberg_table_name
      OPERATIONAL_BUCKET    = aws_s3_bucket.config.bucket
      ATHENA_RESULTS_BUCKET = aws_s3_bucket.athena_results.bucket
    }
  }

  depends_on = [
    aws_iam_role_policy.extract,
    aws_cloudwatch_log_group.extract,
    null_resource.iceberg_table,
  ]
}

resource "aws_lambda_event_source_mapping" "extract" {
  event_source_arn                   = aws_sqs_queue.extract.arn
  function_name                      = aws_lambda_function.extract.arn
  batch_size                         = var.extract_batch_size
  maximum_batching_window_in_seconds = var.extract_batch_window_seconds
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.extract_reserved_concurrency
  }
}
