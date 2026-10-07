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
  name                = "${local.resource_name}-workflow-fic"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.workflow.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject             = "system:serviceaccount:${var.kubernetes_namespace}:${var.workflow_service_account}"
}

# Lets the workflow activity call the hosted agent.
resource "azurerm_role_assignment" "workflow_foundry_user" {
  scope                = azapi_resource.foundry.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.workflow.principal_id
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
