output "probe_config" {
  sensitive = true
  value = {
    tenant_id               = var.tenant_id
    blueprint_client_id     = msgraph_resource.blueprint.output.app_id
    browser_client_id       = msgraph_resource.browser.output.app_id
    agent_client_id         = msgraph_resource.agent.output.app_id
    allowed_user_id         = var.allowed_user_id
    denied_user_id          = var.denied_user_id
    foundry_endpoint        = var.foundry_endpoint
    foundry_audience        = var.foundry_audience
    foundry_delegated_scope = var.foundry_delegated_scope
    agent_name              = var.agent_name
    probe_name              = local.name
    namespace               = var.namespace
    image                   = var.probe_image
    sidecar_image           = var.sidecar_image
  }
}
