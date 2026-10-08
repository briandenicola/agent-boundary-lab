#############################################
# IDENTITY — user-assigned identities and federated credentials
#
# No secrets, no connection strings, no service principal passwords. Every component that
# needs to call something authenticates as itself.
#############################################

# Identity for the two Container Apps hosting the controlled endpoints. Used for the ACR
# pull only; neither endpoint calls anything outbound.
resource "azurerm_user_assigned_identity" "apps" {
  name                = "${local.resource_name}-apps-identity"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

#############################################
# Workflow app identity (Phases 8-9)
#
# The Dapr workflow app on AKS invokes the UNCHANGED Foundry agent from an activity. It
# gets its own identity rather than borrowing the cluster's, so the permission to invoke
# the agent is attached to one named workload and is visible as such in an access review.
#############################################

resource "azurerm_user_assigned_identity" "workflow" {
  name                = "${local.resource_name}-workflow-identity"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

resource "azurerm_federated_identity_credential" "workflow" {
  name      = "${local.resource_name}-workflow-fic"
  parent_id = azurerm_user_assigned_identity.workflow.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject   = "system:serviceaccount:${var.kubernetes_namespace}:${var.workflow_service_account}"
}

# Lets the workflow activity call the hosted agent.
resource "azurerm_role_assignment" "workflow_foundry_user" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.workflow.principal_id
}

#############################################
# Agent deployer identity
#
# The Foundry data plane is private (publicNetworkAccess Disabled), so creating an agent
# version has to originate inside the VNet. An init container on the AKS client harness
# pod does it (infra/k8s/harness.tf), authenticating as this identity rather than as the
# operator. No CLI is involved: the deploy module issues the data-plane call itself.
#
# It is deliberately NOT the workflow identity. The workflow invokes the agent; this
# deploys it. Keeping them apart means "may create agent versions" shows up against one
# named workload in an access review, and revoking deployment rights cannot accidentally
# break invocation.
#
# CONSEQUENCE WORTH KNOWING ABOUT: an init container shares its pod's ServiceAccount, and
# a ServiceAccount carries exactly one `azure.workload.identity/client-id` annotation. So
# the whole harness pod currently runs as the deployer. When the A2A client loop lands it
# will need Foundry Agent Consumer to INVOKE the agent, which this identity does not have.
# At that point either grant it here, or move the deploy step to its own pod. Do not
# quietly annotate the service account with a second client ID; there is no such thing.
#
# ROLE CHOICE, AND WHAT WAS ACTUALLY VERIFIED (2026-10-08).
#
# Verified by reading Azure directly, not documentation:
#   - `az provider operation show -n Microsoft.CognitiveServices` registers the data
#     action `Microsoft.CognitiveServices/accounts/AIServices/agents/write`.
#   - `Cognitive Services User` has dataActions `["Microsoft.CognitiveServices/*"]` and
#     notDataActions limited to agents/endpoints/UserIdentityImpersonation/action and the
#     two fine-tune deployment writes. So the wildcard does cover agents/write.
#
# NOT VERIFIED: no primary source states which role is REQUIRED to create a hosted agent
# *version*. `agents/versions` is not separately registered as a resource type, so the
# assumption is that version writes authorise under `agents/write`. That assumption is
# untested until an apply proves it. If the deploy init container gets a 403, this is the
# first thing to suspect — not the federated credential.
#
# Scope is the account, not the project. Projects are child resources, so the assignment
# inherits down to the project data plane where agents actually live.
#############################################

resource "azurerm_user_assigned_identity" "agent_deployer" {
  name                = "${local.resource_name}-agent-deployer-identity"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

resource "azurerm_federated_identity_credential" "agent_deployer" {
  name      = "${local.resource_name}-agent-deployer-fic"
  parent_id = azurerm_user_assigned_identity.agent_deployer.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject   = "system:serviceaccount:${var.kubernetes_namespace}:${var.agent_deployer_service_account}"
}

resource "azurerm_role_assignment" "agent_deployer_foundry" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.agent_deployer.principal_id
}

#############################################
# Operator access
#
# The person running the demo has to be able to invoke the agent and read its evidence.
#############################################

resource "azurerm_role_assignment" "current_user_foundry_user" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "current_user_openai_user" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services OpenAI User"
  principal_id         = data.azurerm_client_config.current.object_id
}
