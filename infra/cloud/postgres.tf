#############################################
# POSTGRES — Dapr Workflow state store
#
# This is what makes the Phase 9 durability claim testable. The workflow's state lives
# here, outside the pod, so killing the workflow pod mid-run and watching the orchestration
# resume is a real test of persistence rather than a test of how long a process stayed up.
#
# VNet-integrated with no public access. Unlike the two controlled endpoints, this is not
# a destination the agent is ever supposed to reach, so there is no attribution argument
# for exposing it.
#
# CREATED ONLY WHEN var.enable_state_store IS TRUE, AND IT DEFAULTS TO FALSE. Nothing
# consumes this server before Phase 8, and some regions -- including eastus2, where the
# containment demo runs today -- restrict Flexible Server provisioning entirely. Because
# Flexible Server uses VNet injection, the server is pinned to its subnet's region, so
# creating it unconditionally would force the whole environment to move for a database no
# phase uses yet. Turn it on when Phase 8 starts, in a region that allows it.
#############################################

resource "azurerm_private_dns_zone" "postgres" {
  count = var.enable_state_store ? 1 : 0

  name                = "${local.resource_name}.private.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  count = var.enable_state_store ? 1 : 0

  name                  = "postgres-vnet-link"
  resource_group_name   = azurerm_resource_group.this.name
  private_dns_zone_name = azurerm_private_dns_zone.postgres[0].name
  virtual_network_id    = azurerm_virtual_network.main.id
  registration_enabled  = false

  tags = local.common_tags
}

resource "azurerm_postgresql_flexible_server" "main" {
  count = var.enable_state_store ? 1 : 0

  name                = local.postgres_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  version             = var.postgres_version

  administrator_login    = var.postgres_admin_username
  administrator_password = random_password.postgres_admin[0].result

  sku_name   = var.postgres_sku_name
  storage_mb = var.postgres_storage_mb

  # Private only. VNet integration, not a private endpoint - Flexible Server injects
  # itself into the delegated subnet.
  delegated_subnet_id           = azurerm_subnet.postgres[0].id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres[0].id
  public_network_access_enabled = false

  # Single zone. This store exists to survive a POD restart, which it does regardless;
  # zone redundancy would add cost without making the Phase 9 claim any stronger.
  zone = "1"

  backup_retention_days = 7

  lifecycle {
    ignore_changes = [zone]
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]

  tags = local.common_tags
}

resource "azurerm_postgresql_flexible_server_database" "workflow" {
  count = var.enable_state_store ? 1 : 0

  name      = "workflow"
  server_id = azurerm_postgresql_flexible_server.main[0].id
  charset   = "UTF8"
  collation = "en_US.utf8"

  lifecycle {
    prevent_destroy = false
  }
}
