variable "node_image_id" {
  description = "Pinned Ubuntu 24.04 image, checked with yc on 2026-11-01."
  type        = string
  default     = "fd8041m4h84kooeovknf"
}

variable "ssh_public_key" {
  description = "Public SSH key only. Generated locally by scripts/prepare-vms.sh."
  type        = string

  validation {
    condition     = can(regex("^ssh-ed25519 [A-Za-z0-9+/=]+", trimspace(var.ssh_public_key)))
    error_message = "Provide a public Ed25519 SSH key, never a private key."
  }
}

variable "admin_cidrs" {
  description = "IPv4 /32 source addresses permitted to connect over SSH."
  type        = list(string)

  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for cidr in var.admin_cidrs : can(cidrnetmask(cidr)) && can(regex("/32$", cidr))])
    error_message = "Provide one or more valid IPv4 /32 addresses for SSH access."
  }
}

variable "node_disk_size_gb" {
  description = "Boot disk size in GiB. The pinned image requires at least 10 GiB."
  type        = number
  default     = 10

  validation {
    condition     = var.node_disk_size_gb >= 10 && floor(var.node_disk_size_gb) == var.node_disk_size_gb
    error_message = "Boot disk must be an integer of at least 10 GiB."
  }
}

variable "monitoring_worker_memory_gb" {
  description = "RAM for worker-2, which will host the monitoring stack."
  type        = number
  default     = 4

  validation {
    condition     = contains([2, 4, 6, 8], var.monitoring_worker_memory_gb)
    error_message = "Select 2, 4, 6 or 8 GiB RAM."
  }
}
