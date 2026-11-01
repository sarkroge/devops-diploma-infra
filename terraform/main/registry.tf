resource "yandex_container_registry" "diploma" {
  folder_id = var.folder_id
  name      = "diploma-registry"
}
