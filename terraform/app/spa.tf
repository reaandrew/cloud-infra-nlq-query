# SPA front-end hosting: private S3 bucket served via CloudFront with an OAC,
# custom domain via ACM cert in us-east-1 + Route 53 alias record.
#
# Build flow:
#   make package-spa  → npm run build → dist/
#   make sync-spa     → aws s3 sync dist/ s3://cinq-nlq-spa/ --delete
#                       → aws cloudfront create-invalidation
#
# Both run automatically as part of `make deploy` after terraform.

# ---------- S3 bucket ----------

resource "aws_s3_bucket" "spa" {
  bucket        = var.spa_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "spa" {
  bucket                  = aws_s3_bucket.spa.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "spa" {
  bucket = aws_s3_bucket.spa.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# ---------- ACM cert (us-east-1, required by CloudFront) ----------

resource "aws_acm_certificate" "spa" {
  provider          = aws.us_east_1
  domain_name       = var.spa_domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "spa_validation" {
  for_each = {
    for dvo in aws_acm_certificate.spa.domain_validation_options : dvo.domain_name => {
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

resource "aws_acm_certificate_validation" "spa" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.spa.arn
  validation_record_fqdns = [for r in aws_route53_record.spa_validation : r.fqdn]
}

# ---------- CloudFront ----------

resource "aws_cloudfront_origin_access_control" "spa" {
  name                              = "${var.app_name}-spa"
  description                       = "OAC for the cinq SPA bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Tight security headers + sensible browser cache. Connect-src includes the
# API GW custom domain so the SPA can fetch from it.
resource "aws_cloudfront_response_headers_policy" "spa" {
  name = "${var.app_name}-spa-headers"

  security_headers_config {
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = true
      override                   = true
    }
    content_security_policy {
      content_security_policy = join(" ", [
        "default-src 'self';",
        "script-src 'self';",
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline';",
        "font-src 'self' https://fonts.gstatic.com;",
        "img-src 'self' data:;",
        "connect-src 'self' https://${var.api_domain_name};",
        "frame-ancestors 'none';",
        "base-uri 'self';",
        "form-action 'self';",
      ])
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "spa" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "${var.app_name} — NLQ SPA"
  aliases             = [var.spa_domain_name]
  price_class         = "PriceClass_100"
  http_version        = "http2and3"

  origin {
    origin_id                = "spa-bucket"
    domain_name              = aws_s3_bucket.spa.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.spa.id
  }

  default_cache_behavior {
    target_origin_id       = "spa-bucket"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # AWS managed cache policy: CachingOptimized
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.spa.id
  }

  # SPA fallback — anything that 404s falls through to /index.html so client-side
  # routing keeps working on hard refresh.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.spa.certificate_arn
    minimum_protocol_version = "TLSv1.2_2021"
    ssl_support_method       = "sni-only"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  depends_on = [aws_acm_certificate_validation.spa]
}

# Bucket policy granting CloudFront's OAC permission to read objects.
resource "aws_s3_bucket_policy" "spa" {
  bucket = aws_s3_bucket.spa.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowCloudFrontOAC"
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.spa.arn}/*"
      Condition = {
        StringEquals = {
          "AWS:SourceArn" = aws_cloudfront_distribution.spa.arn
        }
      }
    }]
  })
}

# ---------- Route 53 alias ----------

resource "aws_route53_record" "spa" {
  zone_id = data.aws_route53_zone.api.zone_id
  name    = var.spa_domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.spa.domain_name
    zone_id                = aws_cloudfront_distribution.spa.hosted_zone_id
    evaluate_target_health = false
  }
}
