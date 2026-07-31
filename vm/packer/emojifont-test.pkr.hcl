packer {
  required_plugins {
    tart = {
      version = ">= 1.14.0"
      source  = "github.com/cirruslabs/tart"
    }
  }
}

variable "base_image" {
  type        = string
  default     = "ghcr.io/cirruslabs/macos-sequoia-xcode:latest"
  description = "Base macOS image (needs Swift/CoreText for rendering tests)"
}

variable "vm_name" {
  type    = string
  default = "emojifont-test"
}

variable "cpu_count" {
  type    = number
  default = 4
}

variable "memory_gb" {
  type    = number
  default = 8
}

variable "disk_size_gb" {
  type    = number
  default = 150
}

variable "ssh_username" {
  type    = string
  default = "admin"
}

variable "ssh_password" {
  type      = string
  default   = "admin"
  sensitive = true
}

source "tart-cli" "emojifont" {
  vm_base_name = var.base_image
  vm_name      = var.vm_name
  cpu_count    = var.cpu_count
  memory_gb    = var.memory_gb
  disk_size_gb = var.disk_size_gb
  ssh_username = var.ssh_username
  ssh_password = var.ssh_password
  ssh_timeout  = "1200s"

  headless = true
}

build {
  sources = ["source.tart-cli.emojifont"]

  # Disable Spotlight and sleep
  provisioner "shell" {
    inline = [
      "sudo mdutil -a -i off || true",
      "sudo pmset -a sleep 0 displaysleep 0 disksleep 0",
      "defaults write com.apple.screensaver idleTime 0 || true"
    ]
  }

  # Ensure Homebrew is available
  provisioner "shell" {
    inline = [
      "if ! command -v brew &>/dev/null; then",
      "  /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"",
      "  echo 'eval \"$(/opt/homebrew/bin/brew shellenv)\"' >> ~/.zprofile",
      "fi"
    ]
  }

  # Copy and run the setup script
  provisioner "file" {
    source      = "scripts/setup.sh"
    destination = "~/setup.sh"
  }

  provisioner "shell" {
    inline = [
      "chmod +x ~/setup.sh",
      "~/setup.sh"
    ]
  }

  # Clean up
  provisioner "shell" {
    inline = [
      "eval \"$(/opt/homebrew/bin/brew shellenv)\"",
      "brew cleanup -s || true",
      "rm -rf ~/Library/Caches/* || true",
      "rm -rf /tmp/* || true"
    ]
  }
}
