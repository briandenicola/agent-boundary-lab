terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3"
    }
  }
}

provider "azurerm" {
  tenant_id       = var.tenant_id
  subscription_id = split("/", var.foundry_project_resource_id)[2]
  features {}
}
