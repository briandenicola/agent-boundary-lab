#############################################
# STAGE 1 — COMPOSABILITY PROBE
#
# This module exists to answer one question, and only one:
#
#   Will ARM accept a Foundry account that has BOTH a Microsoft-managed VNet
#   (networkInjections) AND RAI policies carrying a network egress policy?
#
# Why it matters. The egress-controls documentation never mentions VNets,
# networkInjections, publicNetworkAccess or isolation modes, and the official sample
# cross-links to a page that 404s. That is a confirmed documentation gap, not a failed
# search (docs/compatibility.md, Blocker 1). If the two features cannot be configured
# together, the demo has to choose one, and the whole network design changes. If they
# can, we still do not know which layer enforces when both apply.
#
# WHAT A SUCCESSFUL APPLY DOES AND DOES NOT PROVE
#
#   Proves:        ARM accepted the configuration.
#   Does NOT prove: the egress policy is enforced, that it is enforced in preference to
#                   the managed network, or that a denied request is attributable to it.
#
# Control-plane acceptance is not data-plane enforcement. Record the stage 1 result as
# "ARM accepted the configuration" and nothing stronger. Stage 2 — an actual deployed
# agent making actual calls — is what tests enforcement.
#
# Deliberately minimal: no storage, Cosmos, Search, ACR, or capability host. Those are
# needed to RUN an agent, not to find out whether this configuration is accepted, and
# each one adds provisioning time and cost to a probe that should be cheap and quick.
#############################################

resource "azapi_resource" "foundry" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-10-01-preview"
  name                      = local.foundry_name
  parent_id                 = azurerm_resource_group.this.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = false

  # The response is read back so the outputs can report what ARM actually stored rather
  # than what we asked for. On a preview API those can differ, and the difference is the
  # interesting part.
  response_export_values = ["*"]

  body = {
    kind = "AIServices"
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }
    properties = {
      disableLocalAuth       = true
      allowProjectManagement = true
      apiProperties          = {}
      customSubDomainName    = local.foundry_name

      # Public access stays disabled, matching the posture of the real environment. A
      # probe that passes only because the account was wide open would not tell us
      # anything useful about the configuration we intend to ship.
      publicNetworkAccess = "Disabled"
      networkAcls = {
        defaultAction       = "Deny"
        virtualNetworkRules = []
        ipRules             = []
      }

      # The managed VNet half of the question.
      networkInjections = [
        {
          scenario                   = "agent"
          subnetArmId                = ""
          useMicrosoftManagedNetwork = true
        }
      ]
    }
  }

  tags = azurerm_resource_group.this.tags
}
