terraform {
  required_version = ">= 1.12.0, < 2.0.0"

  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
      version = ">= 0.194.0, < 1.0.0"
    }
  }
}
