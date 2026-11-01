variable "cloud_id" {
  description = "Yandex Cloud ID. Supply using TF_VAR_cloud_id."
  type        = string

  validation {
    condition     = length(trimspace(var.cloud_id)) > 0
    error_message = "cloud_id must not be empty."
  }
}

variable "folder_id" {
  description = "Target folder ID. Supply using TF_VAR_folder_id."
  type        = string

  validation {
    condition     = length(trimspace(var.folder_id)) > 0
    error_message = "folder_id must not be empty."
  }
}
