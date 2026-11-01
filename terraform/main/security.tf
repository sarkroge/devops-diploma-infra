resource "yandex_vpc_security_group" "nodes" {
  folder_id  = var.folder_id
  name       = "diploma-nodes"
  network_id = yandex_vpc_network.diploma.id

  ingress {
    description       = "Private communication between cluster nodes"
    protocol          = "ANY"
    predefined_target = "self_security_group"
  }

  ingress {
    description    = "SSH from administrator addresses"
    protocol       = "TCP"
    port           = 22
    v4_cidr_blocks = var.admin_cidrs
  }

  egress {
    description    = "Outbound package, image and API access"
    protocol       = "ANY"
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "kubernetes_api" {
  folder_id  = var.folder_id
  name       = "diploma-kubernetes-api"
  network_id = yandex_vpc_network.diploma.id

  # Attached only to control-plane. kubeadm configures TLS and authentication.
  # Public reachability is needed by the future external CI/CD runner.
  ingress {
    description    = "Kubernetes API over TLS for kubectl and CI/CD"
    protocol       = "TCP"
    port           = 6443
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "yandex_vpc_security_group" "web" {
  folder_id  = var.folder_id
  name       = "diploma-web"
  network_id = yandex_vpc_network.diploma.id

  # Attached to workers; the ingress controller will listen on host port 80.
  ingress {
    description    = "HTTP for the test application and Grafana"
    protocol       = "TCP"
    port           = 80
    v4_cidr_blocks = ["0.0.0.0/0"]
  }
}
