terraform {
  required_version = ">= 1.9"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
    msgraph = {
      source  = "microsoft/msgraph"
      version = "= 0.5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3"
    }
  }
}

# Keep Graph's dedicated certificate identity separate from the operator's Azure login.
# CLI Graph tokens include a permission rejected by Agent ID APIs.
provider "msgraph" {
  tenant_id               = var.tenant_id
  client_id               = var.graph_deployer_client_id
  client_certificate_path = var.graph_deployer_certificate_path
  use_cli                 = false
}

provider "azurerm" {
  subscription_id = split("/", var.foundry_project_resource_id)[2]
  features {}
}
