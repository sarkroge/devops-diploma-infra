resource "yandex_iam_service_account" "app_ci" {
  folder_id   = var.folder_id
  name        = "diploma-app-ci"
  description = "Build and publish diploma application images from GitHub Actions"
}

# This account manages images, without infrastructure or state permissions.
resource "yandex_resourcemanager_folder_iam_member" "app_ci" {
  folder_id = var.folder_id
  role      = "container-registry.images.pusher"
  member    = "serviceAccount:${yandex_iam_service_account.app_ci.id}"
}

output "app_ci_service_account_id" {
  description = "Service account for application image publishing."
  value       = yandex_iam_service_account.app_ci.id
}
