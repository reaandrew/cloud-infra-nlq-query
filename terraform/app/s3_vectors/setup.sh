#!/usr/bin/env bash
# Idempotently create an S3 Vectors bucket and index. Used as the local-exec
# fallback because the AWS Terraform provider 5.x does not yet expose
# aws_s3vectors_* resources (S3 Vectors went GA in early 2026 and provider
# coverage landed in 6.x).
#
# Usage: setup.sh <bucket> <index> <dimension> <distance-metric>
set -euo pipefail

bucket="${1:?bucket required}"
index="${2:?index required}"
dimension="${3:?dimension required}"
distance="${4:?distance metric required}"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not on PATH" >&2
  exit 1
fi

# Bucket -----------------------------------------------------------------
if aws s3vectors get-vector-bucket --vector-bucket-name "$bucket" >/dev/null 2>&1; then
  echo "s3vectors: bucket $bucket already exists"
else
  echo "s3vectors: creating bucket $bucket"
  aws s3vectors create-vector-bucket --vector-bucket-name "$bucket" >/dev/null
fi

# Index ------------------------------------------------------------------
if aws s3vectors get-index --vector-bucket-name "$bucket" --index-name "$index" >/dev/null 2>&1; then
  echo "s3vectors: index $index already exists in $bucket"
  current=$(aws s3vectors get-index \
    --vector-bucket-name "$bucket" \
    --index-name "$index" \
    --query 'index.[dimension,distanceMetric,dataType]' \
    --output text)
  echo "  current: dimension distance dataType = $current"
  expected="$dimension	$distance	float32"
  if [[ "$current" != "$expected" ]]; then
    echo "WARNING: existing index does not match expected ($expected). Drop and re-run if you need to change it." >&2
  fi
else
  echo "s3vectors: creating index $index in $bucket (dim=$dimension distance=$distance)"
  aws s3vectors create-index \
    --vector-bucket-name "$bucket" \
    --index-name "$index" \
    --data-type float32 \
    --dimension "$dimension" \
    --distance-metric "$distance" >/dev/null
fi

echo "s3vectors: setup complete for $bucket/$index"
