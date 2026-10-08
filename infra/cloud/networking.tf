#############################################
# NETWORKING — virtual network and subnets
#
# NOTE ON WHAT THIS VNET IS AND IS NOT.
#
# This VNet hosts the AKS cluster (harness and, later, the workflow app), the private endpoints and
# the Container Apps environment. It does NOT host the Foundry agent. Agent egress runs
# through the Microsoft-managed network created by the `networkInjections` block in
# foundry.tf, which is outside this address space entirely.
#
# That separation is the demo. The agent cannot be contained by anything configured here,
# so a denied call cannot be credited to an NSG rule in this file.
#############################################

resource "azurerm_virtual_network" "main" {
  name                = local.vnet_name
  address_space       = [local.vnet_cidr]
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

#############################################
# AKS node subnet
#############################################

resource "azurerm_subnet" "aks" {
  name                 = "aks-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.aks_subnet_cidr]
}

resource "azurerm_network_security_group" "aks" {
  name                = "${local.resource_name}-aks-nsg"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

resource "azurerm_subnet_network_security_group_association" "aks" {
  subnet_id                 = azurerm_subnet.aks.id
  network_security_group_id = azurerm_network_security_group.aks.id
}

#############################################
# Container Apps environment subnet
#
# Delegated to Microsoft.App/environments. A workload-profile environment requires a /27
# or larger; a /24 is allocated so the environment has room to scale without a re-plan.
#############################################

resource "azurerm_subnet" "container_apps" {
  name                 = "containerapps-subnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.main.name
  address_prefixes     = [local.containerapps_subnet_cidr]

  delegation {
    name = "containerapps"

    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

#############################################
#
# Flexible Server VNet integration injects the server into a delegated subnet rather than
# using a private endpoint, so this subnet cannot be shared with anything else.
#############################################

