#############################################
# PRIVATE ENDPOINTS — subnet, DNS zones, links and endpoints
#
# Private paths for the backing resources the workload uses: the registry it pulls from
# and the vault it reads secrets from.
#
# THE TWO CONTROLLED ENDPOINTS ARE DELIBERATELY ABSENT FROM THIS FILE. Giving the test
# receiver a private endpoint would mean a failed call to it had two sufficient causes,
# and the demo could no longer attribute the denial to the egress policy. See
# var.test_endpoints_public.
#
# Postgres is also absent: Flexible Server uses VNet injection rather than a private
# endpoint, and is handled in postgres.tf.
#############################################

resource "azurerm_subnet" "private_endpoints" {
  name                 = "pe-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.pe_subnet_cidr]
}

locals {
  private_dns_zones = {
    keyvault = "privatelink.vaultcore.azure.net"
    acr      = "privatelink.azurecr.io"
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
# Key Vault
#############################################

resource "azurerm_private_endpoint" "keyvault" {
  name                = "${local.resource_name}-kv-pe"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "${local.resource_name}-kv-psc"
    private_connection_resource_id = azurerm_key_vault.main.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "keyvault-dns"
    private_dns_zone_ids = [azurerm_private_dns_zone.zones["keyvault"].id]
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
