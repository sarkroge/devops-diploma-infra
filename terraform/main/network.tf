resource "yandex_vpc_network" "diploma" {
  folder_id   = var.folder_id
  name        = "diploma-network"
  description = "Network for the self-hosted diploma Kubernetes cluster"
}

resource "yandex_vpc_subnet" "diploma" {
  for_each = var.subnets

  folder_id      = var.folder_id
  name           = "diploma-subnet-${each.key}"
  zone           = each.value.zone
  network_id     = yandex_vpc_network.diploma.id
  v4_cidr_blocks = [each.value.cidr]
}
