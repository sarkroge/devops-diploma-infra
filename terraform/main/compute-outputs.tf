output "nodes" {
  description = "VM details for SSH and the future Ansible inventory."
  value = {
    for name, node in yandex_compute_instance.nodes : name => {
      id           = node.id
      hostname     = node.hostname
      zone         = node.zone
      role         = local.cluster_nodes[name].role
      internal_ip  = node.network_interface[0].ip_address
      public_ip    = node.network_interface[0].nat_ip_address
      preemptible  = local.cluster_nodes[name].preemptible
      memory_gb    = local.cluster_nodes[name].memory_gb
      disk_size_gb = var.node_disk_size_gb
    }
  }
}

output "control_plane_ip" {
  description = "Static public IPv4 for the future Kubernetes API."
  value       = yandex_compute_instance.nodes["control-plane"].network_interface[0].nat_ip_address
}

output "web_ip" {
  description = "Static public IPv4 of worker-1 for the future HTTP ingress."
  value       = yandex_compute_instance.nodes["worker-1"].network_interface[0].nat_ip_address
}

output "ssh_commands" {
  description = "Run from the repository root, after checking server host fingerprints."
  value = {
    for name, node in yandex_compute_instance.nodes : name => "ssh -i .secrets/diploma-ssh ubuntu@${node.network_interface[0].nat_ip_address}"
  }
}
