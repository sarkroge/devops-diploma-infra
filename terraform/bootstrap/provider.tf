# Bootstrap uses the current user's short-lived IAM token from YC_TOKEN.
# Subsequent infrastructure runs will use the Terraform service account.
provider "yandex" {
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
}
