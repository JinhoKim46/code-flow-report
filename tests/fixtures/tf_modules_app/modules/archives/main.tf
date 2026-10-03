locals {
  src = "${path.module}/../../src"
}

resource "archive_file" "intake" {
  type        = "zip"
  source_dir  = "${local.src}/intake"
  output_path = "${local.src}/intake.zip"
}

resource "archive_file" "reports" {
  type        = "zip"
  source_dir  = "${local.src}/reports"
  output_path = "${local.src}/reports.zip"
}
