locals {
  blueprint_create_url              = "applications/microsoft.graph.agentIdentityBlueprint"
  provider_blueprint_instance_url   = "${local.blueprint_create_url}/{id}"
  documented_blueprint_instance_url = "applications/{id}/microsoft.graph.agentIdentityBlueprint"
}

# This draft still uses typed creation URLs. Base /applications + @odata.type is
# documented for blueprints, so this mismatch is not a blanket Agent ID limitation.
# The separate SDK-backed directory check uses canonical typed instance URLs.
resource "terraform_data" "agent_id_provider_gate" {
  lifecycle {
    precondition {
      condition     = local.provider_blueprint_instance_url == local.documented_blueprint_instance_url
      error_message = "BLOCKED: this Terraform draft still generates unverified typed Agent ID lifecycle URLs. Base-API blueprint support does not establish the complete Agent Identity lifecycle. Use the separate owner-approved identity:directory-probe to check canonical Graph APIs; full setup and Foundry delegation remain gated. See docs/identity-probe.md."
    }
  }
}
