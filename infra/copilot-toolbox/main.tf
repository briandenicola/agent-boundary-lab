terraform {
  required_version = ">= 1.5"
  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2"
    }
  }
}

data "terraform_remote_state" "cloud" {
  backend = "local"
  config = {
    path = "${path.module}/../cloud/terraform.tfstate"
  }
}

variable "mcp_image" {
  type = string
  validation {
    condition     = can(regex("/containment-demo-copilot-policy-mcp@sha256:[0-9a-f]{64}$", var.mcp_image))
    error_message = "Use the dedicated MCP repository with an immutable digest."
  }
}

variable "oauth_client_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$", var.oauth_client_id))
    error_message = "Supply the dedicated toolbox OAuth application's client ID."
  }
}

locals {
  cloud        = data.terraform_remote_state.cloud.outputs
  group_id     = split("/providers/", local.cloud.foundry_account_id)[0]
  subscription = split("/", local.cloud.foundry_account_id)[2]
  project_name = "${local.cloud.resource_name}-copilot"
  app_name     = "${substr(local.cloud.resource_name, 0, 20)}-copilot-mcp"
  policy_name  = "${local.cloud.resource_name}-copilot-toolbox"
  acr_id       = "${local.group_id}/providers/Microsoft.ContainerRegistry/registries/${local.cloud.acr_name}"
  policy_env = {
    for item in data.azapi_resource.baseline_api.output.properties.template.containers[0].env :
    item.name => try(item.value, "")
  }
  auth_env = {
    POLICY_API_AUTH_MODE           = "delegated"
    POLICY_API_TENANT_ID           = local.policy_env["POLICY_API_TENANT_ID"]
    POLICY_API_AUDIENCE            = local.policy_env["POLICY_API_AUDIENCE"]
    POLICY_API_SCOPE               = local.policy_env["POLICY_API_SCOPE"]
    POLICY_API_AUTHORIZED_USER_IDS = local.policy_env["POLICY_API_AUTHORIZED_USER_IDS"]
    POLICY_API_CLIENT_IDS          = var.oauth_client_id
    POLICY_API_MCP_ENABLED         = "true"
  }
  registry_identity = one(keys(data.azapi_resource.baseline_api.output.identity.userAssignedIdentities))
  deployer_principal = one([
    for identity in data.azapi_resource_list.identities.output.value :
    identity.properties.principalId
    if identity.properties.clientId == local.cloud.agent_deployer_client_id
  ])
}

data "azapi_resource" "baseline_api" {
  type                   = "Microsoft.App/containerApps@2025-01-01"
  name                   = local.cloud.policy_api_app_name
  parent_id              = local.group_id
  response_export_values = ["*"]
}

data "azapi_resource" "baseline_policy" {
  type                   = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                   = local.cloud.rai_policy_enforced_name
  parent_id              = local.cloud.foundry_account_id
  response_export_values = ["*"]
}

data "azapi_resource" "baseline_insights" {
  type                   = "Microsoft.CognitiveServices/accounts/projects/connections@2026-05-15-preview"
  name                   = "appinsights-connection"
  parent_id              = "${local.cloud.foundry_account_id}/projects/${local.cloud.project_name}"
  response_export_values = ["properties.category", "properties.authType", "properties.target", "properties.metadata"]
}

data "azapi_resource_list" "account_hosts" {
  type                   = "Microsoft.CognitiveServices/accounts/capabilityHosts@2025-06-01"
  parent_id              = local.cloud.foundry_account_id
  response_export_values = ["*"]
}

data "azapi_resource_list" "identities" {
  type                   = "Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31"
  parent_id              = local.group_id
  response_export_values = ["*"]
}

resource "azapi_resource" "project" {
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-10-01-preview"
  name                      = local.project_name
  parent_id                 = local.cloud.foundry_account_id
  location                  = data.azapi_resource.baseline_api.output.location
  schema_validation_enabled = false
  response_export_values    = ["identity.principalId"]
  locks                     = [local.cloud.foundry_account_id]
  body = {
    identity = { type = "SystemAssigned" }
    properties = {
      displayName = local.project_name
      description = "Isolated Copilot toolbox demo. Not the AKS/Web UI baseline project."
    }
  }
  lifecycle {
    precondition {
      condition = (
        local.project_name != local.cloud.project_name &&
        length(data.azapi_resource_list.account_hosts.output.value) == 1 &&
        alltrue([for host in data.azapi_resource_list.account_hosts.output.value :
          host.properties.provisioningState == "Succeeded" &&
          host.properties.capabilityHostKind == "Agents" &&
          try(length(host.properties.storageConnections), 0) == 0 &&
          try(length(host.properties.threadStorageConnections), 0) == 0 &&
          try(length(host.properties.vectorStoreConnections), 0) == 0
        ])
      )
      error_message = "Require the existing ready platform-managed account host; do not modify account routing or BYO storage."
    }
  }
}

resource "azapi_resource" "project_host" {
  type                      = "Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2025-06-01"
  name                      = "agents"
  parent_id                 = azapi_resource.project.id
  schema_validation_enabled = false
  response_export_values    = ["properties.provisioningState"]
  locks                     = [local.cloud.foundry_account_id]
  body = {
    properties = { capabilityHostKind = "Agents" }
  }
}

resource "azapi_resource" "project_insights" {
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2026-05-15-preview"
  name                      = "appinsights-connection"
  parent_id                 = azapi_resource.project.id
  schema_validation_enabled = false
  response_export_values    = ["properties.category", "properties.authType", "properties.target"]
  locks                     = [local.cloud.foundry_account_id]
  body = {
    properties = {
      category      = "AppInsights"
      authType      = "ApiKey"
      target        = data.azapi_resource.baseline_insights.output.properties.target
      isSharedToAll = false
      metadata      = data.azapi_resource.baseline_insights.output.properties.metadata
    }
  }
  sensitive_body = {
    properties = {
      credentials = { key = local.cloud.application_insights_connection_string }
    }
  }
  lifecycle {
    precondition {
      condition = (
        data.azapi_resource.baseline_insights.output.properties.category == "AppInsights" &&
        data.azapi_resource.baseline_insights.output.properties.authType == "ApiKey"
      )
      error_message = "Reuse the existing Application Insights destination and verified connection contract only."
    }
  }
}

resource "azapi_resource" "project_pull" {
  type      = "Microsoft.Authorization/roleAssignments@2022-04-01"
  name      = uuidv5("url", "${local.acr_id}/${azapi_resource.project.output.identity.principalId}/AcrPull")
  parent_id = local.acr_id
  body = {
    properties = {
      principalId      = azapi_resource.project.output.identity.principalId
      principalType    = "ServicePrincipal"
      roleDefinitionId = "/subscriptions/${local.subscription}/providers/Microsoft.Authorization/roleDefinitions/7f951dda-4ed3-4680-a7ca-43fe172d538d"
    }
  }
}

resource "azapi_resource" "project_deployer" {
  type      = "Microsoft.Authorization/roleAssignments@2022-04-01"
  name      = uuidv5("url", "${azapi_resource.project.id}/${local.deployer_principal}/FoundryUser")
  parent_id = azapi_resource.project.id
  body = {
    properties = {
      principalId      = local.deployer_principal
      principalType    = "ServicePrincipal"
      roleDefinitionId = "/subscriptions/${local.subscription}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
    }
  }
}
resource "azapi_resource" "mcp" {
  type                   = "Microsoft.App/containerApps@2025-01-01"
  name                   = local.app_name
  parent_id              = local.group_id
  location               = data.azapi_resource.baseline_api.output.location
  response_export_values = ["properties.configuration.ingress.fqdn"]
  identity {
    type         = "UserAssigned"
    identity_ids = [local.registry_identity]
  }
  body = {
    properties = {
      managedEnvironmentId = data.azapi_resource.baseline_api.output.properties.managedEnvironmentId
      workloadProfileName  = "Consumption"
      configuration = {
        activeRevisionsMode = "Single"
        registries          = [{ server = local.cloud.acr_login_server, identity = local.registry_identity }]
        ingress = {
          external      = true
          allowInsecure = false
          targetPort    = 8080
          transport     = "auto"
          traffic       = [{ latestRevision = true, weight = 100 }]
        }
      }
      template = {
        scale = { minReplicas = 1, maxReplicas = 1 }
        containers = [{
          name      = "policy-mcp"
          image     = var.mcp_image
          resources = { cpu = 0.25, memory = "0.5Gi" }
          env       = [for name, value in local.auth_env : { name = name, value = value }]
        }]
      }
    }
  }
  lifecycle {
    precondition {
      condition = (
        !contains([local.cloud.policy_api_app_name, local.cloud.test_receiver_app_name], local.app_name) &&
        local.policy_env["POLICY_API_AUTH_MODE"] == "delegated" &&
        !contains(split(",", local.policy_env["POLICY_API_CLIENT_IDS"]), var.oauth_client_id)
      )
      error_message = "Require delegated authorization and a separate OAuth client; never reuse the shared API or UI client."
    }
  }
}

resource "azapi_resource" "policy" {
  type                      = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                      = local.policy_name
  parent_id                 = local.cloud.foundry_account_id
  schema_validation_enabled = false
  response_export_values    = ["*"]
  locks                     = [local.cloud.foundry_account_id]
  body = {
    properties = {
      basePolicyName = data.azapi_resource.baseline_policy.output.properties.basePolicyName
      type           = "UserManaged"
      mode           = data.azapi_resource.baseline_policy.output.properties.mode
      contentFilters = data.azapi_resource.baseline_policy.output.properties.contentFilters
      egressPolicy = {
        mode          = "Enforced"
        defaultAction = "Deny"
        rules = [for name, host in {
          toolbox   = "${local.cloud.foundry_account_name}.services.ai.azure.com"
          receiver  = regex("^https://([^/]+)", local.cloud.test_receiver_url)[0]
          telemetry = regex("IngestionEndpoint=https://([^/;]+)", local.cloud.application_insights_connection_string)[0]
          } : {
          name     = "allow-${name}"
          ruleType = "Fqdn"
          match    = { host = host }
          action   = { actionType = "Allow" }
        }]
      }
    }
  }
}

output "deployment" {
  value = {
    project_name  = azapi_resource.project.name
    project_id    = azapi_resource.project.id
    agent_name    = "${local.cloud.resource_name}-copilot-agent"
    mcp_url       = "https://${azapi_resource.mcp.output.properties.configuration.ingress.fqdn}/mcp"
    mcp_app_name  = azapi_resource.mcp.name
    rai_policy_id = azapi_resource.policy.id
  }
}
