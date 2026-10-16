# Proposed owner-run setup, not a tested tenant deployment. Graph/API references and
# prerequisite grants are recorded in docs/identity-probe.md (accessed 2026-10-16).
resource "random_pet" "this" {
  length = 2
}

resource "random_id" "this" {
  byte_length = 2
}

resource "random_uuid" "incoming_scope" {}

locals {
  name  = "${random_pet.this.id}-${random_id.this.hex}-identity-probe"
  users = { allowed = var.allowed_user_id, denied = var.denied_user_id }
}

data "msgraph_resource" "foundry_api" {
  url = "servicePrincipals/${var.foundry_api_service_principal_id}"
  response_export_values = {
    app_id = "appId"
    names  = "servicePrincipalNames"
    scopes = "oauth2PermissionScopes"
  }
}

resource "msgraph_resource" "browser" {
  depends_on = [terraform_data.agent_id_provider_gate]
  url        = "applications"
  body = {
    displayName            = "${local.name}-browser"
    signInAudience         = "AzureADMyOrg"
    isFallbackPublicClient = true
    publicClient           = { redirectUris = ["http://localhost:8400"] }
  }
  response_export_values = { app_id = "appId" }
}

resource "msgraph_resource" "browser_principal" {
  url  = "servicePrincipals"
  body = { appId = msgraph_resource.browser.output.app_id }
}

resource "msgraph_resource" "blueprint" {
  depends_on = [terraform_data.agent_id_provider_gate]
  url        = local.blueprint_create_url
  body = {
    displayName           = "${local.name}-blueprint"
    "sponsors@odata.bind" = ["https://graph.microsoft.com/v1.0/users/${var.sponsor_user_id}"]
    api = {
      requestedAccessTokenVersion = 2
      oauth2PermissionScopes = [{
        id                      = random_uuid.incoming_scope.result
        value                   = "access_as_user"
        type                    = "Admin"
        isEnabled               = true
        adminConsentDisplayName = "Invoke the private identity compatibility probe"
        adminConsentDescription = "Allow only the probe's consented test users to invoke its private API."
      }]
    }
  }
  response_export_values = { app_id = "appId" }
}

resource "msgraph_resource_action" "blueprint_audience" {
  resource_url = "applications/${msgraph_resource.blueprint.id}/microsoft.graph.agentIdentityBlueprint"
  method       = "PATCH"
  body = {
    identifierUris = ["api://${msgraph_resource.blueprint.output.app_id}"]
  }
}

resource "msgraph_resource" "blueprint_principal" {
  url        = "servicePrincipals/microsoft.graph.agentIdentityBlueprintPrincipal"
  body       = { appId = msgraph_resource.blueprint.output.app_id }
  depends_on = [msgraph_resource_action.blueprint_audience]
}

resource "msgraph_resource" "agent" {
  url = "servicePrincipals/microsoft.graph.agentIdentity"
  body = {
    displayName              = "${local.name}-agent"
    agentIdentityBlueprintId = msgraph_resource.blueprint.output.app_id
    "sponsors@odata.bind"    = ["https://graph.microsoft.com/v1.0/users/${var.sponsor_user_id}"]
  }
  response_export_values = { app_id = "appId" }
  depends_on             = [msgraph_resource.blueprint_principal]
}

resource "msgraph_resource" "federation" {
  url = "applications/${msgraph_resource.blueprint.id}/microsoft.graph.agentIdentityBlueprint/federatedIdentityCredentials"
  body = {
    name      = "${local.name}-aks"
    issuer    = var.aks_oidc_issuer_url
    subject   = "system:serviceaccount:${var.namespace}:${local.name}"
    audiences = ["api://AzureADTokenExchange"]
  }
}

resource "msgraph_resource" "incoming_consent" {
  for_each = toset(["allowed", "denied"])
  url      = "oauth2PermissionGrants"
  body = {
    clientId    = msgraph_resource.browser_principal.id
    resourceId  = msgraph_resource.blueprint_principal.id
    consentType = "Principal"
    principalId = local.users[each.key]
    scope       = "access_as_user"
  }
}

resource "msgraph_resource" "foundry_consent" {
  for_each = toset(["allowed", "denied"])
  url      = "oauth2PermissionGrants"
  body = {
    clientId    = msgraph_resource.agent.id
    resourceId  = var.foundry_api_service_principal_id
    consentType = "Principal"
    principalId = local.users[each.key]
    scope       = var.foundry_delegated_scope
  }
  lifecycle {
    precondition {
      condition = length([
        for scope in data.msgraph_resource.foundry_api.output.scopes :
        scope if scope.value == var.foundry_delegated_scope && scope.isEnabled
      ]) == 1
      error_message = "BLOCKED: the actual Foundry resource does not publish this enabled delegated scope. Do not substitute workload authentication."
    }
    precondition {
      condition     = contains(data.msgraph_resource.foundry_api.output.names, "https://ai.azure.com")
      error_message = "BLOCKED: this service principal is not the SDK's https://ai.azure.com resource."
    }
    precondition {
      condition     = contains(concat(data.msgraph_resource.foundry_api.output.names, [data.msgraph_resource.foundry_api.output.app_id]), var.foundry_audience)
      error_message = "BLOCKED: the expected token audience does not identify the verified Foundry resource."
    }
  }
}

# No role for the denied user or the intermediary agent. Which identity Foundry evaluates
# for an OBO bearer is part of the probe, not a reason to pregrant both.
resource "azurerm_role_assignment" "allowed_user_invoke" {
  depends_on           = [terraform_data.agent_id_provider_gate]
  scope                = var.foundry_project_resource_id
  role_definition_name = "Foundry Agent Consumer"
  principal_id         = var.allowed_user_id
  principal_type       = "User"
}
