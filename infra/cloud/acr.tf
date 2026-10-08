#############################################
# ACR — Azure Container Registry
#
# Holds the single agent image whose digest is deployed to BOTH agent versions. The whole
# experiment rests on that image being byte-identical across the Audit and Enforced runs,
# so deployments reference an immutable digest rather than a tag.
#
# Public network access stays enabled: images are built and pushed with `az acr build`
# from the operator's machine, and the registry is not part of the control under test.
#############################################

resource "azurerm_container_registry" "main" {
  name                          = local.acr_name
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  sku                           = "Premium"
  admin_enabled                 = false
  public_network_access_enabled = true

  tags = local.common_tags
}

# AKS pulls the Dapr workflow app image.
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
}

# The Container Apps hosting the two controlled endpoints pull their own image.
resource "azurerm_role_assignment" "apps_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

# The Foundry account pulls the AGENT image.
#
# This is a DIFFERENT principal from aks_acr_pull above. The kubelet identity pulls the
# harness image onto a node in our cluster; this one is the hosted-agent runtime pulling
# the digest-pinned agent image into Foundry's own compute. Same registry, same image,
# two unrelated pulls by two unrelated identities. Granting one does nothing for the other,
# which is exactly how this was missed: the harness pod pulled fine, so the registry
# looked healthy.
#
# WHY THIS FAILURE IS WORTH THE COMMENT. Without this assignment the control plane still
# ACCEPTS the version — `create_version` returns HTTP 200 and the version exists — and
# then it sits in `creating` indefinitely, because an unauthorised pull is retryable
# rather than fatal. It never reaches `failed`. The symptom is therefore indistinguishable
# from slow provisioning, and the real error is on the backend's side of a
# private-endpoint-only data plane where we cannot read it. If a version ever hangs in
# `creating` again, check this role assignment before anything else.
#
# AcrPull only. The agent runtime reads images; nothing in Foundry writes to this registry.
resource "azurerm_role_assignment" "foundry_acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azapi_resource.foundry.output.identity.principalId
}

# The operator running `az acr build` needs to push.
resource "azurerm_role_assignment" "current_user_acr_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = data.azurerm_client_config.current.object_id
}
