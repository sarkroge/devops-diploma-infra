variable "cloud_id" {
  description = "Yandex Cloud ID, provided by TF_VAR_cloud_id."
  type        = string
}

variable "folder_id" {
  description = "Yandex Cloud folder ID, provided by TF_VAR_folder_id."
  type        = string
}

variable "subnets" {
  description = "Subnets in three availability zones."
  type = map(object({
    zone = string
    cidr = string
  }))
  default = {
    a = { zone = "ru-central1-a", cidr = "10.20.10.0/24" }
    d = { zone = "ru-central1-d", cidr = "10.20.30.0/24" }
    e = { zone = "ru-central1-e", cidr = "10.20.40.0/24" }
  }

  validation {
    condition     = length(var.subnets) >= 3 && length(toset([for subnet in values(var.subnets) : subnet.zone])) >= 3
    error_message = "Configure at least three subnets in three different zones."
  }
}
