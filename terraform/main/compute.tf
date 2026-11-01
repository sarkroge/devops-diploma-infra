locals {
  cluster_nodes = {
    control-plane = {
      subnet_key        = "a"
      hostname          = "k8s-control-plane"
      internal_ip       = "10.20.10.10"
      role              = "control-plane"
      memory_gb         = 2
      preemptible       = false
      reserve_public_ip = true
    }
    worker-1 = {
      subnet_key        = "e"
      hostname          = "k8s-worker-1"
      internal_ip       = "10.20.40.10"
      role              = "worker"
      memory_gb         = 2
      preemptible       = true
      reserve_public_ip = true
    }
    worker-2 = {
      subnet_key        = "a"
      hostname          = "k8s-worker-2"
      internal_ip       = "10.20.10.12"
      role              = "worker"
      memory_gb         = var.monitoring_worker_memory_gb
      preemptible       = true
      reserve_public_ip = false
    }
  }

  cloud_init = {
    ssh_pwauth   = false
    disable_root = true
    users = [{
      name                = "ubuntu"
      groups              = ["sudo"]
      shell               = "/bin/bash"
      sudo                = "ALL=(ALL) NOPASSWD:ALL"
      lock_passwd         = true
      ssh_authorized_keys = [trimspace(var.ssh_public_key)]
    }]
  }
}

resource "yandex_vpc_address" "nodes" {
  for_each = { for name, node in local.cluster_nodes : name => node if node.reserve_public_ip }

  folder_id = var.folder_id
  name      = "diploma-${each.key}-ip"

  external_ipv4_address {
    zone_id = var.subnets[each.value.subnet_key].zone
  }
}

resource "yandex_compute_instance" "nodes" {
  for_each = local.cluster_nodes

  folder_id                 = var.folder_id
  name                      = "diploma-${each.key}"
  hostname                  = each.value.hostname
  zone                      = var.subnets[each.value.subnet_key].zone
  platform_id               = "standard-v3"
  allow_stopping_for_update = true

  labels = {
    project = "devops-diploma"
    role    = each.value.role
  }

  resources {
    cores         = 2
    core_fraction = 20
    memory        = each.value.memory_gb
  }

  scheduling_policy {
    preemptible = each.value.preemptible
  }

  boot_disk {
    auto_delete = true

    initialize_params {
      name     = "diploma-${each.key}-boot"
      image_id = var.node_image_id
      type     = "network-hdd"
      size     = var.node_disk_size_gb
    }
  }

  network_interface {
    subnet_id      = yandex_vpc_subnet.diploma[each.value.subnet_key].id
    ip_address     = each.value.internal_ip
    nat            = true
    nat_ip_address = each.value.reserve_public_ip ? yandex_vpc_address.nodes[each.key].external_ipv4_address[0].address : null
    security_group_ids = [
      yandex_vpc_security_group.nodes.id,
      each.value.role == "control-plane" ? yandex_vpc_security_group.kubernetes_api.id : yandex_vpc_security_group.web.id,
    ]
  }

  metadata = {
    ssh-keys  = "ubuntu:${trimspace(var.ssh_public_key)}"
    user-data = "#cloud-config\n${yamlencode(local.cloud_init)}"
  }
}
