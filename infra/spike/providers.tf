#############################################
# PROVIDERS
#
# State is local on purpose. This module is a throwaway probe that is created and
# destroyed in the same sitting, so there is nothing worth keeping in a remote backend.
#############################################

terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3"
    }
  }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
  storage_use_azuread = true
}

# The subscription is ambient from `az login`. It is deliberately not a variable, so a
# stale value in a tfvars file cannot send a billable apply somewhere unexpected.
data "azurerm_client_config" "current" {}
