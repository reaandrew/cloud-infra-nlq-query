# S3 Vectors bucket + index for the cinq.operational schema RAG index.
#
# AWS Terraform provider 5.x does not yet expose aws_s3vectors_* resources
# (S3 Vectors went GA in early 2026 and provider support landed in 6.x), so
# we drive bucket+index creation through the AWS CLI inside a null_resource.
# Same pattern as the Athena DDL bootstrap (terraform/app/athena/run_ddl.sh).

resource "null_resource" "schemas_vector_index" {
  triggers = {
    bucket    = var.schemas_vector_bucket
    index     = var.schemas_vector_index
    dimension = tostring(var.embedding_dimensions)
    distance  = var.vector_distance_metric
    setup_sha = sha256(file("${path.module}/s3_vectors/setup.sh"))
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      ${path.module}/s3_vectors/setup.sh \
        ${var.schemas_vector_bucket} \
        ${var.schemas_vector_index} \
        ${var.embedding_dimensions} \
        ${var.vector_distance_metric}
    EOT
  }
}
