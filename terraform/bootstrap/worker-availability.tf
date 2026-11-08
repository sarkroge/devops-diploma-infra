# Kept in bootstrap so the watcher survives recreation of terraform/main.
# The existing Terraform service account gets no new permissions.
variable "workers_autostart_enabled" {
  description = "Create the timer and allow the function to start stopped diploma workers."
  type        = bool
  default     = false
}

variable "workers_autostart_until" {
  description = "UTC RFC3339 deadline after which the function performs no starts."
  type        = string
  default     = "1970-01-01T00:00:00Z"

  validation {
    condition     = can(formatdate("YYYY", var.workers_autostart_until))
    error_message = "Use an RFC3339 timestamp, for example 2026-11-05T18:00:00Z."
  }
}

resource "yandex_iam_service_account" "worker_restarter" {
  folder_id   = var.folder_id
  name        = "diploma-worker-restarter"
  description = "Start stopped diploma workers during the review window"
}

# compute.operator is the built-in service role for list/get/start, without
# permission to create/delete/reconfigure VMs. It also permits stop/restart.
# Folder scope is required by name/label discovery across recreated VM IDs.
resource "yandex_resourcemanager_folder_iam_member" "worker_restarter_compute" {
  folder_id = var.folder_id
  role      = "compute.operator"
  member    = "serviceAccount:${yandex_iam_service_account.worker_restarter.id}"
}

resource "yandex_iam_service_account" "worker_restarter_trigger" {
  folder_id   = var.folder_id
  name        = "diploma-worker-timer"
  description = "Invoke only the diploma worker restarter function"
}

resource "yandex_function" "worker_restarter" {
  folder_id          = var.folder_id
  name               = "diploma-worker-restarter"
  description        = "Start STOPPED preemptible diploma workers; bounded review window"
  runtime            = "python312"
  entrypoint         = "index.handler"
  memory             = 128
  execution_timeout  = "60"
  concurrency        = 1
  service_account_id = yandex_iam_service_account.worker_restarter.id
  user_hash = sha256(jsonencode({
    code    = filesha256("${path.module}/../../functions/worker-restarter/function.zip")
    enabled = var.workers_autostart_enabled
    until   = var.workers_autostart_until
  }))

  environment = {
    FOLDER_ID       = var.folder_id
    ENABLED         = tostring(var.workers_autostart_enabled)
    AUTOSTART_UNTIL = var.workers_autostart_until
    PROJECT_LABEL   = "devops-diploma"
  }

  content {
    zip_filename = "${path.module}/../../functions/worker-restarter/function.zip"
  }

  # Autostart must not depend on availability of the Cloud Logging API.
  # Direct invocation still returns the handler result for diagnostics.
  log_options {
    disabled = true
  }

  depends_on = [
    yandex_resourcemanager_folder_iam_member.worker_restarter_compute,
  ]
}

# This is a new private function. Only its dedicated trigger account is added.
resource "yandex_function_iam_binding" "worker_restarter_invoker" {
  function_id = yandex_function.worker_restarter.id
  role        = "functions.functionInvoker"
  members     = ["serviceAccount:${yandex_iam_service_account.worker_restarter_trigger.id}"]
}

resource "yandex_function_trigger" "worker_restarter" {
  count       = var.workers_autostart_enabled ? 1 : 0
  folder_id   = var.folder_id
  name        = "diploma-worker-restarter"
  description = "Check diploma workers every two minutes"

  timer {
    cron_expression = "*/2 * * * ? *"
  }

  function {
    id                 = yandex_function.worker_restarter.id
    service_account_id = yandex_iam_service_account.worker_restarter_trigger.id
    retry_attempts     = "1"
    retry_interval     = "30"
  }

  depends_on = [yandex_function_iam_binding.worker_restarter_invoker]
}

output "worker_availability" {
  description = "Autostart configuration; deadline also applies to manual function invocations."
  value = {
    enabled          = var.workers_autostart_enabled
    until            = var.workers_autostart_until
    function_id      = yandex_function.worker_restarter.id
    trigger_id       = try(yandex_function_trigger.worker_restarter[0].id, null)
    log_group_id     = null
    logging_enabled  = false
    runtime_account  = yandex_iam_service_account.worker_restarter.id
    interval_minutes = 2
  }
}
