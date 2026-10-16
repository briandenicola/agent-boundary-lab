locals {
  blueprint_create_url              = "applications/microsoft.graph.agentIdentityBlueprint"
  provider_blueprint_instance_url   = "${local.blueprint_create_url}/{id}"
  documented_blueprint_instance_url = "applications/{id}/microsoft.graph.agentIdentityBlueprint"
}

# msgraph 0.5.0 appends /{id} to the creation collection for its entire lifecycle.
# Do not issue a POST until a supported lifecycle for these typed resources is verified.
resource "terraform_data" "agent_id_provider_gate" {
  lifecycle {
    precondition {
      condition     = local.provider_blueprint_instance_url == local.documented_blueprint_instance_url
      error_message = "BLOCKED: msgraph 0.5.0 generates a different Agent ID instance URL than the documented API. Creation, refresh, update and destruction need a verified provider lifecycle before provisioning. See docs/identity-probe.md."
    }
  }
}
