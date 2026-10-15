# Hosted agents run in the Microsoft-managed network (foundry.tf networkInjections), not in
# our VNet. The account has publicNetworkAccess = Disabled, so the agent's model call
# arrived over a public path and got 403 "Public access is disabled". Our own private endpoint
# is in OUR vnet and cannot help that path. The managed network needs an outbound
# private-endpoint rule back to the account itself.
#
# Source: foundry-samples infrastructure-setup-bicep/18-managed-virtual-network README
# (a sample, not a Learn page), accessed 2026-10-09. Observed before this change:
# managednetworks/default had outboundRules = {} (compatibility.md B9g).
#
# This is a rule on the managed network, not on the RAI policy, so the egress allowlist is
# untouched and identical for the Audit and Enforced agents.

# The rule is created as a pending private-endpoint connection on the account; the account's
# own identity must be allowed to approve it. Scoped to the ACCOUNT, not the resource group
# the sample uses: the role's dataActions-free action list includes
# Microsoft.CognitiveServices/accounts/privateEndpointConnections/write, and the connection
# being approved lives on the account, so nothing wider is needed. The sample also assigns
# Contributor on the RG; we deliberately do NOT, because it is unverified as required. If the
# connection stays Pending, that is the first thing to revisit.
resource "azurerm_role_assignment" "foundry_network_approver" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Azure AI Enterprise Network Connection Approver"
  principal_id         = azapi_resource.foundry.output.identity.principalId
}

resource "azapi_resource" "foundry_self_pe_rule" {
  type                      = "Microsoft.CognitiveServices/accounts/managednetworks/outboundrules@2025-10-01-preview"
  name                      = "foundry-account-pe"
  parent_id                 = azapi_resource.managed_network.id
  schema_validation_enabled = false

  body = {
    properties = {
      type     = "PrivateEndpoint"
      category = "UserDefined"
      destination = {
        serviceResourceId = azapi_resource.foundry.id
        subresourceTarget = "account"
      }
    }
  }

  depends_on = [azurerm_role_assignment.foundry_network_approver]
  locks      = [azapi_resource.foundry.id]
  retry      = local.foundry_operation_retry
}

# AKS's registry endpoint is in our VNet, not Foundry's managed network. Observed
# 2026-10-15: adding this separate registry endpoint restored hosted-agent provisioning.
resource "azurerm_role_assignment" "foundry_acr_network_approver" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "Azure AI Enterprise Network Connection Approver"
  principal_id         = azapi_resource.foundry.output.identity.principalId
}

# The ACR-specific approval prerequisite includes Reader on the registry's resource
# group, not just approval rights on the registry. Azure rejected creation without it.
# Source: https://aka.ms/azureaipeapproval, accessed 2026-10-15.
resource "azurerm_role_assignment" "foundry_acr_network_reader" {
  scope                = azurerm_resource_group.this.id
  role_definition_name = "Reader"
  principal_id         = azapi_resource.foundry.output.identity.principalId
}

resource "azapi_resource" "foundry_acr_pe_rule" {
  type                      = "Microsoft.CognitiveServices/accounts/managednetworks/outboundrules@2025-10-01-preview"
  name                      = "acr-pe"
  parent_id                 = azapi_resource.managed_network.id
  schema_validation_enabled = false

  body = {
    properties = {
      type     = "PrivateEndpoint"
      category = "UserDefined"
      destination = {
        serviceResourceId = azurerm_container_registry.main.id
        subresourceTarget = "registry"
      }
    }
  }

  depends_on = [
    azurerm_role_assignment.foundry_acr_network_approver,
    azurerm_role_assignment.foundry_acr_network_reader,
  ]
  locks = [azapi_resource.foundry.id]
  # The first retry after assigning approval rights still failed while RBAC propagated.
  retry = merge(local.foundry_operation_retry, {
    error_message_regex = concat(local.foundry_operation_retry.error_message_regex, [
      "Foundry account managed identity don't have required permissions to read and approve private endpoint connections",
    ])
  })
}

#############################################
# ISOLATION MODE: AllowOnlyApprovedOutbound (ONE-WAY)
#
# Declared as the Learn accounts/managedNetworks resource ("default"), with isolationMode set in
# the body, not as a post-create flip. The platform creates "default" with the account, so every
# environment needs `task cloud:network-import` once, including on a fresh account.
# `task cloud:bootstrap` creates the account and imports the network before the full apply.
# The service can answer with a TransientError timeout while the change lands (2026-10-09), so
# the call retries; the same PUT again is idempotent.
#
# Experimental design: the two controlled hosts are allowed at the NETWORK layer for BOTH agents,
# so the egress RAI policy stays the only variable between audit and enforced. See
# test_endpoints_public in variables.tf. Hosts derive from the live ingress, never hardcoded.
#############################################
resource "azapi_resource" "managed_network" {
  type                      = "Microsoft.CognitiveServices/accounts/managednetworks@2025-10-01-preview"
  name                      = "default"
  parent_id                 = azapi_resource.foundry.id
  schema_validation_enabled = false

  body = {
    properties = {
      managedNetwork = {
        isolationMode      = var.managed_network_isolation_mode
        managedNetworkKind = "V2"
        firewallSku        = "Standard"
      }
    }
  }

  depends_on = [azapi_resource.project]
  locks      = [azapi_resource.foundry.id]
  retry      = local.foundry_operation_retry
}

locals {
  approved_only = var.managed_network_isolation_mode == "AllowOnlyApprovedOutbound"

  network_fqdn_rules = local.approved_only ? merge(
    {
      "fqdn-policy-api"    = local.policy_api_host
      "fqdn-test-receiver" = local.test_receiver_host
      "fqdn-appinsights"   = "*.in.applicationinsights.azure.com"
    },
    { for i, h in var.managed_network_extra_fqdns : "fqdn-extra-${i}" => h }
  ) : {}
}

resource "azapi_resource" "network_fqdn_rule" {
  for_each                  = local.network_fqdn_rules
  type                      = "Microsoft.CognitiveServices/accounts/managednetworks/outboundrules@2025-10-01-preview"
  name                      = each.key
  parent_id                 = azapi_resource.managed_network.id
  schema_validation_enabled = false

  body = {
    properties = {
      type        = "FQDN"
      category    = "UserDefined"
      destination = each.value
    }
  }

  locks = [azapi_resource.foundry.id]
  retry = local.foundry_operation_retry

  depends_on = [azapi_resource.managed_network]
}
