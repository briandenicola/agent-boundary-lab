#############################################
# VARIABLES
#
# Names are not configurable. Every resource name derives from the generated random name
# in locals.tf, which keeps naming a convention rather than a decision and makes
# teardown-by-tag reliable.
#
# There are no hardcoded addresses either: every CIDR derives from the randomly chosen
# VNet range in locals.tf.
#############################################

variable "region" {
  description = "Azure region for the demo environment."
  type        = string
  default     = "eastus2"
}

variable "tags" {
  description = <<-EOT
    Application tag applied to every resource.

    Deliberately distinct from the spike's tag. `task spike:down` deletes resource groups
    by the spike tag, and sharing a tag would make a routine spike teardown capable of
    destroying this environment.
  EOT
  type        = string
  default     = "Agent Boundary Lab"
}

#############################################
# THE EXPERIMENTAL VARIABLE
#############################################

variable "rai_base_policy_name" {
  description = <<-EOT
    The RAI policy the two custom policies derive from.

    A custom RAI policy must name a base policy; omitting it fails the create with
    "Resource has invalid base policy". Valid names are account- and
    API-version-specific, so confirm the real value for your account with
    `task cloud:base-policies` rather than trusting this default.
  EOT
  type        = string
  default     = "Microsoft.DefaultV2"
}

variable "test_endpoints_public" {
  description = <<-EOT
    Whether the two controlled endpoints accept traffic from the public internet.

    DEFAULT TRUE, AND THAT IS A DELIBERATE EXPERIMENTAL CHOICE, NOT LAZINESS.

    The claim under test is that the PLATFORM EGRESS POLICY denies the un-allowlisted
    call. If the test receiver were also unreachable at the network layer, a failed call
    would have two sufficient explanations and the result would be attributable to
    neither. Public endpoints keep the egress policy as the only thing standing between
    the agent and the destination, which is the entire point of the demo.

    Set false only to demonstrate the defence-in-depth posture, and when you do, expect
    and label the result as inconclusive for attribution purposes.
  EOT
  type        = bool
  default     = true
}

variable "foundry_public_network_access" {
  description = <<-EOT
    Inbound public access to the Foundry account's control and data plane.

    DEFAULT ENABLED. Inbound reachability is not the control under test: the demo is
    about OUTBOUND containment from the agent, which is governed by the managed network
    injection and the egress policy regardless of this setting. Disabling it means the
    agent can only be invoked and its evidence only collected from inside the VNet, which
    impedes evidence collection without strengthening the claim.

    Set to "Disabled" only if the environment's own policy requires it, and plan to drive
    the demo from a jumpbox.
  EOT
  type        = string
  default     = "Enabled"

  validation {
    condition     = contains(["Enabled", "Disabled"], var.foundry_public_network_access)
    error_message = "foundry_public_network_access must be exactly \"Enabled\" or \"Disabled\"."
  }
}

#############################################
# MODEL
#############################################

variable "model_name" {
  description = "Chat model backing the agent. The agent's reasoning quality is not what is being measured, so the cheapest capable model is the right default."
  type        = string
  default     = "gpt-4o-mini"
}

variable "model_version" {
  description = "Pinned model version. Pinned rather than floating so a model change cannot silently become an extra variable between two runs that are supposed to differ only in egress policy."
  type        = string
  default     = "2024-07-18"
}

variable "model_capacity" {
  description = "Thousands of tokens per minute for the model deployment."
  type        = number
  default     = 30
}

#############################################
# AKS — host for the Phase 8/9 Dapr workflow app
#############################################

variable "aks_node_count" {
  description = "Number of AKS nodes."
  type        = number
  default     = 2
}

variable "aks_node_size" {
  description = "VM size for AKS nodes."
  type        = string
  default     = "Standard_D4s_v3"
}

variable "kubernetes_version" {
  description = "Kubernetes version."
  type        = string
  default     = "1.32"
}

variable "kubernetes_namespace" {
  description = "Namespace the Dapr workflow app is deployed into. Used to build the workload-identity federated credential subject."
  type        = string
  default     = "agent-boundary-lab"
}

variable "workflow_service_account" {
  description = "Kubernetes service account bound to the workflow workload identity."
  type        = string
  default     = "workflow-workload-identity"
}

#############################################
# POSTGRES — Dapr workflow state store
#############################################

variable "postgres_sku_name" {
  description = "Flexible Server SKU. The workflow state store holds a handful of orchestration rows, so the smallest burstable tier is sufficient."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "Flexible Server storage in MB."
  type        = number
  default     = 32768
}

variable "postgres_version" {
  description = "PostgreSQL major version."
  type        = string
  default     = "16"
}

variable "postgres_admin_username" {
  description = "Administrator login for the Flexible Server. The password is generated, never supplied."
  type        = string
  default     = "pgadmin"
}
