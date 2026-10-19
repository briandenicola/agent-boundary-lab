#############################################
# PROVIDERS
#
# State is local, matching the spike and the rest of the demo repos. This environment is
# built and torn down by one operator in one sitting; a remote backend would add a
# bootstrap dependency without protecting anything that is not reproducible from source.
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
    time = {
      source  = "hashicorp/time"
      version = "~> 0.11"
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

# Providers use ARM_TENANT_ID / ARM_SUBSCRIPTION_ID from the operator environment.
# cloud:plan/bootstrap/up verify Azure CLI matches that explicit target first.
data "azurerm_client_config" "current" {}
