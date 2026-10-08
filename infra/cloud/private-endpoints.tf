#############################################
# PRIVATE ENDPOINTS — subnet, DNS zones, links and endpoints
#
# Private paths for the Foundry account under test and the backing resources the workload
# uses: the registry it pulls from.
#
# These endpoints govern INBOUND reach. None of them constrains the agent's outbound
# traffic; that is the egress policy's job. Keep the two ideas apart.
#
# THE TWO CONTROLLED ENDPOINTS ARE DELIBERATELY ABSENT FROM THIS FILE. Giving the test
# receiver a private endpoint would mean a failed call to it had two sufficient causes,
# and the demo could no longer attribute the denial to the egress policy. See
# var.test_endpoints_public.
#
# There is no Key Vault. The subscription forces Key Vault endpoints to be private, so
# Terraform could never write a secret from an operator workstation -- and nothing read
# from the vault anyway. Generated values are surfaced as sensitive outputs instead.
#############################################

resource "azurerm_subnet" "private_endpoints" {
  name                 = "pe-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.pe_subnet_cidr]
}

locals {
  private_dns_zones = {
    acr         = "privatelink.azurecr.io"
    cogservices = "privatelink.cognitiveservices.azure.com"
    openai      = "privatelink.openai.azure.com"
    services_ai = "privatelink.services.ai.azure.com"
  }
}

resource "azurerm_private_dns_zone" "zones" {
  for_each            = local.private_dns_zones
  name                = each.value
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "links" {
  for_each              = local.private_dns_zones
  name                  = "${each.key}-vnet-link"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.zones[each.key].name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

#############################################
# Foundry account — the control under test
#
# The account is inbound-private (publicNetworkAccess Disabled, networkAcls default Deny)
# and reachable only across this endpoint. The harness is the client; it runs on AKS in
# this VNet to mimic an on-premises environment, so it resolves the account through these
# zones and never traverses the internet to reach it.
#
# READ THIS BEFORE CITING IT AS CONTAINMENT. This endpoint controls who can reach IN. It
# places no restriction whatsoever on what the agent can reach OUT to, which is the claim
# the demo actually makes. Outbound is networkInjections plus the egress policy. Treating
# a private endpoint as egress containment is the specific error this repository exists to
# disprove, so do not reproduce it in a diagram, a slide, or a report.
#
# Three DNS zones, not one: the account answers on cognitiveservices, openai and
# services.ai names, and a client that resolves the wrong one gets a public IP it cannot
# reach rather than a clear failure.
#############################################

resource "azurerm_private_endpoint" "foundry" {
  name                = "${local.resource_name}-foundry-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  depends_on = [
    azapi_resource.project,
    azurerm_cognitive_deployment.chat,
  ]

  private_service_connection {
    name                           = "${local.resource_name}-foundry-psc"
    private_connection_resource_id = azapi_resource.foundry.id
    subresource_names              = ["account"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name = "foundry-dns"
    private_dns_zone_ids = [
      azurerm_private_dns_zone.zones["cogservices"].id,
      azurerm_private_dns_zone.zones["openai"].id,
      azurerm_private_dns_zone.zones["services_ai"].id,
    ]
  }

  tags = local.common_tags
}

#############################################
# Container Registry
#############################################

resource "azurerm_private_endpoint" "acr" {
  name                = "${local.resource_name}-acr-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-acr-psc"
    private_connection_resource_id = azurerm_container_registry.main.id
    subresource_names              = ["registry"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "acr-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["acr"].id]
  }

  tags = local.common_tags
}
