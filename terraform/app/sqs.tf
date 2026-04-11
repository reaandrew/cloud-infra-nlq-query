# SQS queue that fans S3:ObjectCreated events on cinq-config-mock into the
# extract Lambda. Batched (25 records / 60s window) so the Lambda does one
# Iceberg commit per batch instead of per file — caps concurrent Iceberg
# writers at a level pyiceberg/Glue can handle without commit storms.

resource "aws_sqs_queue" "extract_dlq" {
  name                       = "${var.app_name}-extract-dlq"
  message_retention_seconds  = 1209600 # 14 days
  visibility_timeout_seconds = 60
}

resource "aws_sqs_queue" "extract" {
  name                       = "${var.app_name}-extract"
  message_retention_seconds  = 345600 # 4 days
  visibility_timeout_seconds = var.extract_lambda_timeout_seconds * 6

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.extract_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_s3_bucket_notification" "config_mock_events" {
  bucket = aws_s3_bucket.config_mock.id

  queue {
    queue_arn     = aws_sqs_queue.extract.arn
    events        = ["s3:ObjectCreated:*"]
    filter_suffix = ".json.gz"
  }

  depends_on = [aws_sqs_queue_policy.extract]
}

# Allow S3 on the mock bucket to publish events to the queue.
resource "aws_sqs_queue_policy" "extract" {
  queue_url = aws_sqs_queue.extract.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3SendMessage"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.extract.arn
      Condition = {
        ArnEquals = {
          "aws:SourceArn" = aws_s3_bucket.config_mock.arn
        }
      }
    }]
  })
}
