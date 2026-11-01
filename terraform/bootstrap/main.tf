locals {
  state_bucket_name = "sarkroge-diploma-state-${var.folder_id}"

  terraform_roles = toset([
    "compute.editor",
    "vpc.admin",
    "container-registry.editor",
  ])
}

resource "yandex_iam_service_account" "terraform" {
  folder_id   = var.folder_id
  name        = "diploma-terraform"
  description = "Diploma infrastructure provisioning and Terraform state access"
}

# Additive memberships preserve other users' existing folder permissions.
resource "yandex_resourcemanager_folder_iam_member" "terraform" {
  for_each = local.terraform_roles

  folder_id = var.folder_id
  role      = each.value
  member    = "serviceAccount:${yandex_iam_service_account.terraform.id}"
}

# Created using the user's IAM token. No public ACL or public IAM members.
resource "yandex_storage_bucket" "state" {
  folder_id     = var.folder_id
  bucket        = local.state_bucket_name
  max_size      = 1073741824
  force_destroy = false

  anonymous_access_flags {
    read        = false
    list        = false
    config_read = false
  }

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Storage permission is limited to this bucket, not the entire folder.
resource "yandex_storage_bucket_iam_binding" "terraform_state" {
  bucket = yandex_storage_bucket.state.id
  role   = "storage.editor"
  members = [
    "serviceAccount:${yandex_iam_service_account.terraform.id}",
  ]
}

# S3 backend authentication. These values remain sensitive outputs.
# The bootstrap state contains the secret and must stay out of Git.
resource "yandex_iam_service_account_static_access_key" "state" {
  service_account_id = yandex_iam_service_account.terraform.id
  description        = "S3 credentials for the diploma Terraform backend"

  depends_on = [yandex_storage_bucket_iam_binding.terraform_state]
}
