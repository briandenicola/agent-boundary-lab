#############################################
# LOCALS AND RESOURCE GROUP
#
# Names follow the house convention: a random pet plus a short random id, with every
# other name derived from it. Nothing here takes a name from a variable.
#############################################

resource "random_pet" "this" {}

resource "random_id" "this" {
  byte_length = 2
}

locals {
  resource_name       = "${random_pet.this.id}-${random_id.this.dec}"
  resource_group_name = "${local.resource_name}-spike-rg"
  foundry_name        = "${local.resource_name}-foundry"
}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = var.region

  tags = {
    Application = var.tags
    DeployedOn  = timestamp()
    AppName     = local.resource_name
    Purpose     = "Throwaway composability probe. Safe to delete at any time."
  }
}
