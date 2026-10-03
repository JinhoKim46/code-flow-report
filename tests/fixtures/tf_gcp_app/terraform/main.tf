data "archive_file" "src" {
  type        = "zip"
  source_dir  = "${path.module}/../function"
  output_path = "/tmp/function.zip"
}

resource "google_storage_bucket" "source" {
  name     = "src-bucket"
  location = "US"
}

resource "google_storage_bucket_object" "zip" {
  name   = "function.zip"
  bucket = google_storage_bucket.source.name
  source = data.archive_file.src.output_path
}

resource "google_pubsub_topic" "jobs" {
  name = "jobs"
}

resource "google_service_account" "fn" {
  account_id = "fn-sa"
}

resource "google_cloudfunctions2_function" "process" {
  name = "process"
  build_config {
    runtime     = "python312"
    entry_point = "process_job"
    source {
      storage_source {
        bucket = google_storage_bucket.source.name
        object = google_storage_bucket_object.zip.name
      }
    }
  }
  service_config {
    service_account_email = google_service_account.fn.email
    environment_variables = {
      OUTPUT_BUCKET = google_storage_bucket.source.name
    }
  }
  event_trigger {
    event_type   = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic = google_pubsub_topic.jobs.id
  }
}

resource "google_cloudfunctions_function" "api" {
  name                  = "api"
  runtime               = "python311"
  entry_point           = "handle_http"
  trigger_http          = true
  source_archive_bucket = google_storage_bucket.source.name
  source_archive_object = google_storage_bucket_object.zip.name
}

resource "google_cloud_scheduler_job" "hourly" {
  name     = "hourly"
  schedule = "0 * * * *"
  pubsub_target {
    topic_name = google_pubsub_topic.jobs.id
    data       = base64encode("go")
  }
}

resource "google_storage_bucket_iam_member" "writer" {
  bucket = google_storage_bucket.source.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.fn.email}"
}
