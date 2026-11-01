# YC_SERVICE_ACCOUNT_KEY_FILE must point to the authorized service account key.
# Unset YC_TOKEN to avoid authenticating as the bootstrap user instead.
provider "yandex" {
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
}
