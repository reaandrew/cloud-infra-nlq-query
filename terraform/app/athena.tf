# Iceberg table + freshness view, created via Athena DDL.
#
# We deliberately don't use aws_glue_catalog_table — Iceberg mutates its own
# table metadata out of band (every commit writes a new metadata.json), and
# the native resource keeps trying to revert those mutations. Athena DDL
# owns the table lifecycle; Terraform just triggers an apply when the DDL
# files change.

locals {
  iceberg_table_ddl = templatefile("${path.module}/athena/iceberg_table.sql", {
    database   = var.glue_database_name
    table_name = var.iceberg_table_name
    bucket     = aws_s3_bucket.config.bucket
  })

  operational_live_view_ddl = templatefile("${path.module}/athena/operational_live.sql", {
    database   = var.glue_database_name
    view_name  = var.iceberg_view_name
    table_name = var.iceberg_table_name
    ttl_hours  = var.ttl_view_hours
  })
}

resource "local_file" "iceberg_table_sql" {
  filename = "${path.module}/.terraform/athena-ddl/iceberg_table.sql"
  content  = local.iceberg_table_ddl
}

resource "local_file" "operational_live_view_sql" {
  filename = "${path.module}/.terraform/athena-ddl/operational_live.sql"
  content  = local.operational_live_view_ddl
}

# One-shot: create the Iceberg table. IF NOT EXISTS makes retries idempotent.
resource "null_resource" "iceberg_table" {
  triggers = {
    ddl_sha256     = sha256(local.iceberg_table_ddl)
    database       = var.glue_database_name
    table          = var.iceberg_table_name
    results_bucket = aws_s3_bucket.athena_results.bucket
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      ${path.module}/athena/run_ddl.sh \
        ${local_file.iceberg_table_sql.filename} \
        ${var.glue_database_name} \
        ${aws_s3_bucket.athena_results.bucket}
    EOT
  }

  depends_on = [
    aws_glue_catalog_database.cinq,
    aws_s3_bucket.athena_results,
    aws_s3_bucket.config,
    local_file.iceberg_table_sql,
  ]
}

# Create / replace the freshness view. Depends on the table existing.
resource "null_resource" "operational_live_view" {
  triggers = {
    ddl_sha256 = sha256(local.operational_live_view_ddl)
    database   = var.glue_database_name
    view       = var.iceberg_view_name
    table_dep  = null_resource.iceberg_table.id
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      ${path.module}/athena/run_ddl.sh \
        ${local_file.operational_live_view_sql.filename} \
        ${var.glue_database_name} \
        ${aws_s3_bucket.athena_results.bucket}
    EOT
  }

  depends_on = [
    null_resource.iceberg_table,
    local_file.operational_live_view_sql,
  ]
}
