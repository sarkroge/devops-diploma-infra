output "network_id" {
  value       = yandex_vpc_network.diploma.id
  description = "Diploma VPC network ID."
}

output "subnets" {
  description = "Subnets used by the future Kubernetes nodes."
  value = {
    for name, subnet in yandex_vpc_subnet.diploma : name => {
      id   = subnet.id
      zone = subnet.zone
      cidr = subnet.v4_cidr_blocks
    }
  }
}

output "registry_id" {
  value       = yandex_container_registry.diploma.id
  description = "Container Registry ID for image builds."
}

output "app_image_repository" {
  value       = "cr.yandex/${yandex_container_registry.diploma.id}/diploma-app"
  description = "Image repository path; an image will be pushed later."
}
