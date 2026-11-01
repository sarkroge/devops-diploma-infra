output "terraform_service_account_id" {
  description = "Service account for the main infrastructure configuration."
  value       = yandex_iam_service_account.terraform.id
}

output "state_bucket_name" {
  description = "Bucket for the main infrastructure Terraform state."
  value       = yandex_storage_bucket.state.id
}

output "state_access_key" {
  description = "S3 access key. Use locally or in CI secrets, never in Git."
  value       = yandex_iam_service_account_static_access_key.state.access_key
  sensitive   = true
}

output "state_secret_key" {
  description = "S3 secret key. Use locally or in CI secrets, never in Git."
  value       = yandex_iam_service_account_static_access_key.state.secret_key
  sensitive   = true
}
