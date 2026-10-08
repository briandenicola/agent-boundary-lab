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

    DEFAULT DISABLED, and it should stay that way. A containment demo whose Foundry
    account answers from the public internet undercuts its own claim before the first
    tool call: a reviewer is entitled to ask why they should believe the outbound story
    from a platform left inbound-open.

    Nothing needs it to be Enabled. The agentic harness runs on AKS, inside this VNet,
    deliberately mimicking an on-premises environment, so it reaches the account over the
    private endpoint. The only public surface in the environment is the harness's own
    ingress.

    Note that this setting governs INBOUND reach only, and the distinction is load-bearing
    rather than pedantic: disabling it does NOT contain the agent's outbound traffic, and
    a private endpoint never has. Egress is governed by the managed network injection and
    the egress policy. Presenting a private endpoint as outbound containment is exactly
    the confusion this repository exists to correct.
  EOT
  type        = string
  default     = "Disabled"

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
  description = <<-EOT
    Kubernetes version. NULL BY DEFAULT, which resolves to the region's latest
    non-preview version at plan time.

    Left unpinned on purpose. A pinned version silently rots: AKS eventually moves it to
    Long-Term-Support-only and the apply fails with K8sVersionNotSupported on a
    configuration that worked the month before. The cluster is not an experimental
    variable in this demo, so there is nothing to gain from freezing it. Set it only to
    reproduce a specific historical run.
  EOT
  type        = string
  default     = null
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
# POSTGRES — Dapr workflow state store (Phase 8)
#############################################

variable "enable_state_store" {
  description = <<-EOT
    Create the PostgreSQL Flexible Server that backs Dapr Workflow state.

    Defaults to false, and that default is deliberate. No phase before 8 reads from this
    server, and Flexible Server is restricted in several regions including eastus2, where
    the containment environment runs. VNet injection pins the server to its subnet's
    region, so provisioning it unconditionally would force the containment demo to
    relocate for a database nothing queries.

    Set this to true when Phase 8 begins, and deploy that environment in a region where
    Flexible Server is available. Surveyed 2026-10-08: centralus, westus3, northcentralus
    and canadacentral were unrestricted; eastus, eastus2, westus2 and southcentralus were
    not. A restricted region reports "The value of the 'Version' should be in: []", which
    names the wrong cause -- check the capabilities API for restricted: Enabled.
  EOT
  type        = bool
  default     = false
}

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
