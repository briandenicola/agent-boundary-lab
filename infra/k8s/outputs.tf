#############################################
# OUTPUTS
#
# These are the strings you need to look at the thing after applying it. They exist so
# the runbook does not reconstruct a namespace or a pod selector by hand.
#############################################

output "namespace" {
  description = "Namespace holding the harness. Also the namespace half of the workload-identity federated credential subject."
  value       = kubernetes_namespace_v1.demo.metadata[0].name
}

output "service_account" {
  description = "ServiceAccount the harness pod runs as. Must match the federated credential subject in infra/cloud/identity.tf."
  value       = kubernetes_service_account_v1.agent_deployer.metadata[0].name
}

output "harness_deployment" {
  description = "Deployment name of the client harness."
  value       = kubernetes_deployment_v1.harness.metadata[0].name
}

output "agent_image" {
  description = "Digest-pinned image the harness and its deploy init container run. Both agent versions must pin this same digest."
  value       = local.agent_image
}

output "deploy_logs_command" {
  description = "Read the deploy init container's output. This is where an agent-version publish succeeds or fails."
  value       = "kubectl -n ${kubernetes_namespace_v1.demo.metadata[0].name} logs deployment/${kubernetes_deployment_v1.harness.metadata[0].name} -c agent-deploy"
}

output "what_this_module_does_not_prove" {
  description = "Read before quoting a result from this module."
  value       = <<-EOT
    A running harness pod proves that a workload inside the VNet can authenticate as the
    agent-deployer identity and pull the agent image. It proves nothing about egress
    containment.

    The init container succeeding proves an agent version was accepted by the Foundry
    control path. It does NOT prove the attached RAI policy is being enforced on that
    version's outbound traffic. Read the version back and confirm rai_config before
    treating any run as attributable.

    The main container currently runs `sleep infinity`. There is no A2A client loop yet,
    so nothing here has called the agent.
  EOT
}
