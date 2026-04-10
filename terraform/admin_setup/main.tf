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
    key          = "admin/terraform.tfstate"
    region       = "eu-west-2"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region
}

# Create IAM role for CI
resource "aws_iam_role" "ci_role" {
  name = var.ci_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::889772146711:oidc-provider/token.actions.githubusercontent.com"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = [
              "repo:reaandrew/cloud-infra-nlq-query:ref:refs/heads/main",
              "repo:reaandrew/cloud-infra-nlq-query:ref:refs/heads/feature/*",
              "repo:reaandrew/cloud-infra-nlq-query:ref:refs/tags/*"
            ]
          }
        }
      }
    ]
  })
}

# Create IAM policy for CI role
resource "aws_iam_role_policy" "ci_policy" {
  name = "${var.ci_role_name}-policy"
  role = aws_iam_role.ci_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${var.state_bucket_name}",
          "arn:aws:s3:::${var.state_bucket_name}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:*",
          "iam:PassRole",
          "iam:CreateRole",
          "iam:DeleteRole",
          "iam:GetRole",
          "iam:PutRolePolicy",
          "iam:DeleteRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:DetachRolePolicy",
          "iam:AttachRolePolicy",
          "events:*",
          "logs:*"
        ]
        Resource = [
          "arn:aws:lambda:${var.aws_region}:889772146711:function:${var.app_name}-*",
          "arn:aws:iam::889772146711:role/${var.app_name}-*",
          "arn:aws:events:${var.aws_region}:889772146711:rule/${var.app_name}-*",
          "arn:aws:logs:${var.aws_region}:889772146711:log-group:/aws/lambda/${var.app_name}-*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:GetFoundationModel"
        ]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
      }
    ]
  })
} 