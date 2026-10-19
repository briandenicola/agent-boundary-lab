output "setup_config" {
  sensitive = true
  value = {
    tenant_id                        = var.tenant_id
    allowed_user_id                  = var.allowed_user_id
    denied_user_id                   = var.denied_user_id
    foundry_endpoint                 = var.foundry_endpoint
    foundry_audience                 = var.foundry_audience
    foundry_delegated_scope          = var.foundry_delegated_scope
    foundry_api_service_principal_id = var.foundry_api_service_principal_id
    aks_oidc_issuer_url              = var.aks_oidc_issuer_url
    incoming_scope_id                = random_uuid.incoming_scope.result
    agent_name                       = var.agent_name
    probe_name                       = local.name
    namespace                        = var.namespace
    image                            = var.probe_image
    sidecar_image                    = var.sidecar_image
  }
}
