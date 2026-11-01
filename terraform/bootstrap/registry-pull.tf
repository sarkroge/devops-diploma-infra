resource "yandex_iam_service_account" "registry_pull" {
  folder_id   = var.folder_id
  name        = "diploma-registry-pull"
  description = "Read-only container image access for the diploma Kubernetes application"
}

resource "yandex_resourcemanager_folder_iam_member" "registry_pull" {
  folder_id = var.folder_id
  role      = "container-registry.images.puller"
  member    = "serviceAccount:${yandex_iam_service_account.registry_pull.id}"
}

output "registry_pull_service_account_id" {
  description = "Service account for the application imagePullSecret."
  value       = yandex_iam_service_account.registry_pull.id
}
