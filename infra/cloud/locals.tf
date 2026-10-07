#############################################
# LOCALS AND RESOURCE GROUP
#
# Every name derives from `local.resource_name`, and every address derives from
# `local.vnet_cidr`. Neither takes a value from a variable.
#############################################

locals {
  location      = var.region
  resource_name = "${random_pet.this.id}-${random_id.this.dec}"

  resource_group_name = "${local.resource_name}-rg"
  vnet_name           = "${local.resource_name}-vnet"
  foundry_name        = "${local.resource_name}-foundry"
  project_name        = "${local.resource_name}-project"
  loganalytics_name   = "${local.resource_name}-logs"
  appinsights_name    = "${local.resource_name}-ai"
  aks_name            = "${local.resource_name}-aks"
  aks_node_rg_name    = "${local.aks_name}_nodes_rg"
  postgres_name       = "${local.resource_name}-pg"
  caenv_name          = "${local.resource_name}-cae"

  # Key Vault and ACR names reject hyphens and have tight length limits, so they are
  # squashed rather than given a name of their own.
  keyvault_name = substr("${replace(local.resource_name, "-", "")}kv", 0, 24)
  acr_name      = substr("${replace(local.resource_name, "-", "")}acr", 0, 50)

  # Addressing. A /16 drawn from a random point in 10/8, carved into /24s. Nothing is
  # hardcoded, so two environments in one subscription will not overlap.
  vnet_cidr                 = cidrsubnet("10.0.0.0/8", 8, random_integer.vnet_cidr.result)
  aks_subnet_cidr           = cidrsubnet(local.vnet_cidr, 8, 1)
  pe_subnet_cidr            = cidrsubnet(local.vnet_cidr, 8, 2)
  containerapps_subnet_cidr = cidrsubnet(local.vnet_cidr, 8, 3)
  postgres_subnet_cidr      = cidrsubnet(local.vnet_cidr, 8, 4)

  common_tags = {
    Application = var.tags
    DeployedOn  = timestamp()
    AppName     = local.resource_name
  }
}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = local.location

  tags = local.common_tags
}
