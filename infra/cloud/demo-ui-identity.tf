# Identity for the demo UI (issue #1). It is a SEPARATE identity from the workflow's so the
# UI's Foundry rights can be granted and revoked on their own, and from the agents' identities
# (which are minted by the platform, see compatibility.md B9f).
#
# The UI only INVOKES agents, so it gets "Foundry Agent Consumer", whose single dataAction is
# Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action (read-only az,
# 2026-10-09; role id eed3b665-ab3a-47b6-8f48-c9382fb1dad6). That is narrower than the Cognitive
# Services User the workflow identity holds. Scoped to the PROJECT, as the reference repo does.
# Whether interact/action alone covers every call the UI makes (e.g. a version read-back) is
# unverified; a 403 on such a call would name the missing action.
resource "azurerm_user_assigned_identity" "demo_ui" {
  name                = "${local.resource_name}-demo-ui-identity"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.common_tags
}

resource "azurerm_federated_identity_credential" "demo_ui" {
  name      = "${local.resource_name}-demo-ui-fic"
  parent_id = azurerm_user_assigned_identity.demo_ui.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = azurerm_kubernetes_cluster.main.oidc_issuer_url
  subject   = "system:serviceaccount:${var.kubernetes_namespace}:${var.demo_ui_service_account}"
}

resource "azurerm_role_assignment" "demo_ui_agent_consumer" {
  scope                = azapi_resource.project.id
  role_definition_name = "Foundry Agent Consumer"
  principal_id         = azurerm_user_assigned_identity.demo_ui.principal_id
}
