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
}

#############################################
# ISOLATION MODE: AllowOnlyApprovedOutbound (ONE-WAY)
#
# Declared as the Learn accounts/managedNetworks resource ("default"), with isolationMode set in
# the body, not as a post-create flip. The platform creates "default" with the account, so an
# existing environment needs `terraform import azapi_resource.managed_network <id>` once. On a
# fresh account whether azapi's create PUTs over the platform-created resource is UNVERIFIED.
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

  retry = {
    error_message_regex  = ["TransientError", "ongoing operation"]
    interval_seconds     = 20
    max_interval_seconds = 60
  }
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

  # The managed network takes one operation at a time; parallel rule creation returned Conflict.
  retry = {
    error_message_regex = ["ongoing operation"]
    interval_seconds    = 20
  }

  depends_on = [azapi_resource.managed_network]
}
