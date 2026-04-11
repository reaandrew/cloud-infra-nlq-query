# Glue Data Catalog database that holds the Iceberg table for flattened
# AWS Config data. The table itself is created via Athena DDL (see athena.tf)
# because the native aws_glue_catalog_table resource fights Iceberg's
# out-of-band schema/metadata mutations.

resource "aws_glue_catalog_database" "cinq" {
  name        = var.glue_database_name
  description = "Cloud-Infra NLQ Query — flattened AWS Config operational data"
}
