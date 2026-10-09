#############################################
# FOUNDRY — AI Services account and project
#
# THIS IS THE LAYER THE DEMO IS ABOUT.
#
# `networkInjections` with `useMicrosoftManagedNetwork = true` puts agent egress inside a
# Microsoft-managed VNet. That network is NOT the VNet in networking.tf and is not
# reachable or configurable from it. No NSG, route table or firewall rule in this
# repository can affect what the agent can reach, which is exactly what makes a denial
# attributable to the platform rather than to our own plumbing.
#
# Stage 1 of the Phase 0 spike confirmed on 2026-10-07 that this block COEXISTS with RAI
# policies carrying an `egressPolicy` - ARM stores both verbatim, neither is dropped. See
# docs/compatibility.md.
#
# WHAT THAT DOES NOT SETTLE. Control-plane acceptance is not data-plane enforcement. It
# remains unproven which layer actually denies when both apply, and therefore whether a
# denied call is attributable to the egress policy rather than to managed-network
# routing. Resolving that is the job of a real run, not of this file.
#############################################

resource "azapi_resource" "foundry" {
  type                      = "Microsoft.CognitiveServices/accounts@2025-10-01-preview"
  name                      = local.foundry_name
  parent_id                 = azurerm_resource_group.this.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = false

  body = {
    kind = "AIServices"
    sku = {
      name = "S0"
    }
    identity = {
      type = "SystemAssigned"
    }
    properties = {
      # Entra ID only. A key on this account would be a credential capable of invoking the
      # agent, and the demo claims there are no credentials in the application.
      disableLocalAuth = true

      allowProjectManagement = true
      apiProperties          = {}
      customSubDomainName    = local.foundry_name

      # Governs INBOUND reach only, and is Disabled. The harness that calls this account
      # is the client, and it runs on AKS inside this VNet to mimic an on-premises
      # environment, so it arrives over the private endpoint in private-endpoints.tf.
      #
      # This does NOT contain the agent's outbound traffic. A private endpoint never has.
      # Egress is governed by networkInjections plus the egress policy in rai-policies.tf.
      publicNetworkAccess = var.foundry_public_network_access

      networkAcls = {
        defaultAction       = "Deny"
        virtualNetworkRules = []
        ipRules             = []
      }

      networkInjections = [
        {
          scenario                   = "agent"
          subnetArmId                = ""
          useMicrosoftManagedNetwork = true
        }
      ]
    }
  }

  response_export_values = [
    "properties.endpoint",
    "identity.principalId",
  ]

  tags = local.common_tags
}

#############################################
# Project — the container the hosted agent is published into
#############################################

resource "azapi_resource" "project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-10-01-preview"
  name                      = local.project_name
  parent_id                 = azapi_resource.foundry.id
  location                  = azurerm_resource_group.this.location
  schema_validation_enabled = false

  body = {
    identity = {
      type = "SystemAssigned"
    }
    properties = {
      displayName = local.project_name
      description = "Agent Boundary Lab. Hosts the two agent versions that differ only in RAI egress policy."
    }
  }

  # identity.principalId is exported for the AcrPull grant in acr.tf. Exporting it only
  # adds a read-back; it changes nothing on the resource.
  response_export_values = ["properties.endpoints", "identity.principalId"]
}

#############################################
# HOSTED AGENT VERSIONS — deliberately NOT managed here.
#
# The two agent versions are published by `task cloud:deploy-agent` after an image exists
# in ACR, for two reasons:
#
#   1. The hosted-agent version API is preview and not reliably expressible in Terraform
#      today. Guessing at its shape here would be inventing an API, which this repository
#      forbids.
#   2. Publishing must pin an image DIGEST read back from ACR after the build. Terraform
#      cannot know that digest at plan time, and a tag would silently permit the two
#      versions to run different code - destroying the single-variable design.
#############################################
