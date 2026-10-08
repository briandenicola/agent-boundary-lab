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
  caenv_name          = "${local.resource_name}-cae"
  postgres_name       = "${local.resource_name}-pg"

  # ACR names reject hyphens and have tight length limits, so they are squashed.
  acr_name = substr("${replace(local.resource_name, "-", "")}acr", 0, 50)

  # Container App names cap at 32 characters and reject a trailing hyphen or a doubled
  # one. `random_pet` has no length guarantee, so a name built by plain interpolation
  # fails on a long pet and passes on a short one -- the apply would be a coin toss.
  # Reserve room for the longest suffix ("-test-receiver", 14) and trim any hyphen the
  # truncation exposes, so every generated name is legal regardless of the pet drawn.
  ca_name_prefix     = trimsuffix(substr(local.resource_name, 0, min(length(local.resource_name), 18)), "-")
  policy_api_name    = "${local.ca_name_prefix}-policy-api"
  test_receiver_name = "${local.ca_name_prefix}-test-receiver"

  # Addressing. A /16 drawn from a random point in 10/8, carved into /24s. Nothing is
  # hardcoded, so two environments in one subscription will not overlap.
  vnet_cidr                 = cidrsubnet("10.0.0.0/8", 8, random_integer.vnet_cidr.result)
  aks_subnet_cidr           = cidrsubnet(local.vnet_cidr, 8, 1)
  postgres_subnet_cidr      = cidrsubnet(local.vnet_cidr, 8, 4)
  pe_subnet_cidr            = cidrsubnet(local.vnet_cidr, 8, 2)
  containerapps_subnet_cidr = cidrsubnet(local.vnet_cidr, 8, 3)

  # No DeployedOn tag, deliberately.
  #
  # It used to be `timestamp()`, which re-evaluates on every plan. That made the whole
  # map unknown and marked every tagged resource for in-place update forever: a clean
  # subscription planned as "0 to add, 24 to change, 0 to destroy" with 22 of those being
  # nothing but the rewritten timestamp.
  #
  # That is not cosmetic here. The demo's claim is that the RAI policy is the ONLY
  # variable between the Audit and the Enforced run, and the mechanical way to show it is
  # `No changes. Your infrastructure matches the configuration.` between the two runs.
  # A tag that always drifts makes that check impossible to pass, so the answer to "what
  # else changed between your two runs?" was permanently "24 resources, unknown".
  #
  # It also forced an in-place update of `azapi_resource.foundry` -- a PREVIEW resource we
  # already know drops configuration silently -- on every apply, purely to rewrite a
  # string, and pushed `foundry_endpoint` to (known after apply) with it.
  #
  # The deploy time is already recorded in the resource's own ARM metadata and in git. A
  # timestamp that lies on every plan is worth less than no timestamp. If one is ever
  # wanted back, it must come from a variable the operator sets deliberately, never from
  # a function that re-evaluates at plan time.
  common_tags = {
    Application = var.tags
    AppName     = local.resource_name
  }
}

resource "azurerm_resource_group" "this" {
  name     = local.resource_group_name
  location = local.location

  tags = local.common_tags
}
