#############################################
# OUTPUTS
#
# These report what ARM actually stored, not what we asked it to store. On a preview API
# the two can differ — a property can be silently dropped, defaulted, or renamed — and
# that difference is the finding, so read these before concluding anything.
#############################################

output "resource_group_name" {
  description = "Delete this to remove everything the spike created."
  value       = azurerm_resource_group.this.name
}

output "foundry_account_id" {
  description = "Full ARM resource ID of the Foundry account."
  value       = azapi_resource.foundry.id
}

output "rai_policy_audit_id" {
  description = <<-EOT
    Full ARM resource ID of the Audit policy.

    Agent definitions reference an RAI policy by its full resource ID, not by its bare
    name, so this is the form the deployment will actually need.
  EOT
  value       = azapi_resource.rai_policy_audit.id
}

output "rai_policy_enforced_id" {
  description = "Full ARM resource ID of the Enforced policy."
  value       = azapi_resource.rai_policy_enforced.id
}

output "stored_network_injections" {
  description = <<-EOT
    The managed-VNet configuration as ARM stored it.

    If this comes back empty or altered while the apply still succeeded, then ARM
    accepted the request but did not keep the configuration, and the spike has found a
    silent drop rather than a success.
  EOT
  value       = try(azapi_resource.foundry.output.properties.networkInjections, null)
}

output "stored_egress_policy_audit" {
  description = "The Audit policy's egressPolicy block as ARM stored it."
  value       = try(azapi_resource.rai_policy_audit.output.properties.egressPolicy, null)
}

output "stored_egress_policy_enforced" {
  description = "The Enforced policy's egressPolicy block as ARM stored it."
  value       = try(azapi_resource.rai_policy_enforced.output.properties.egressPolicy, null)
}

output "finding" {
  description = <<-EOT
    A reminder, not a result.

    A successful apply means ARM accepted the configuration. It does not mean the egress
    policy is enforced, that it takes precedence over the managed network, or that a
    denied request would be attributable to it. Control-plane acceptance is not
    data-plane enforcement.
  EOT
  value = join(" ", [
    "Stage 1 complete: ARM accepted managed VNet and egress policies on one account.",
    "This is NOT evidence of enforcement. Check stored_network_injections and",
    "stored_egress_policy_* above to confirm nothing was silently dropped, then record",
    "the result in docs/compatibility.md as acceptance only.",
  ])
}
