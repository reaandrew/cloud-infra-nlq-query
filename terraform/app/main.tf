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

# Second AWS provider alias pinned to us-east-1 — required by CloudFront
# for the SPA's ACM certificate (CloudFront only consumes ACM certs from
# us-east-1, regardless of where the distribution is consumed).
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_availability_zones" "available" {
  state = "available"
}

# S3 bucket for operational AWS Config data (unpacked, queryable)
resource "aws_s3_bucket" "config" {
  bucket = var.config_bucket_name
}

resource "aws_s3_bucket_versioning" "config" {
  bucket = aws_s3_bucket.config.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 bucket for mock AWS Config data
resource "aws_s3_bucket" "config_mock" {
  bucket = "${var.config_bucket_name}-mock"
}

resource "aws_s3_bucket_versioning" "config_mock" {
  bucket = aws_s3_bucket.config_mock.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "config_mock" {
  bucket = aws_s3_bucket.config_mock.id

  rule {
    id     = "expire-snapshots"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = var.mock_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.mock_noncurrent_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# S3 bucket for Athena query results (required by Athena; kept separate from operational data)
resource "aws_s3_bucket" "athena_results" {
  bucket        = "${var.app_name}-athena-results"
  force_destroy = true
}

resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    id     = "expire-results"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = 7
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# S3 bucket for NLQ async job progress docs. Each in-flight NLQ job gets
# one JSON file at jobs/{job_id}.json that the worker Lambda overwrites
# on every stage transition. The submit/status Lambda reads from this
# bucket for GET /nlq/jobs/{id}. Lifecycle: 1-day expiry — jobs are
# ephemeral, the client doesn't need history.
resource "aws_s3_bucket" "nlq_jobs" {
  bucket        = "${var.app_name}-nlq-jobs"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "nlq_jobs" {
  bucket                  = aws_s3_bucket.nlq_jobs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "nlq_jobs" {
  bucket = aws_s3_bucket.nlq_jobs.id

  rule {
    id     = "expire-jobs"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = 1
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# VPC
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.app_name}-vpc"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.app_name}-igw"
  }
}

resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.app_name}-public-${count.index}"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.app_name}-public-rt"
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}
