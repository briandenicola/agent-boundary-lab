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
  description = <<-EOT
    Chat model backing the agent. The agent's reasoning quality is not what is being
    measured, so the cheapest capable model is the right default -- it only has to be able
    to call two tools.

    gpt-5.4-mini, not a GPT-4 model: the 4 family is being retired. Note that gpt-5.5 has
    no mini variant, so the smallest current option is one minor version behind the
    newest full model.

    Verified in canadacentral on 2026-10-08. Check the SKU before changing this: gpt-5-mini
    and gpt-5 are GlobalProvisionedManaged ONLY in this region and would fail against the
    GlobalStandard deployment below.
  EOT
  type        = string
  default     = "gpt-5.4-mini"
}

variable "model_version" {
  description = "Pinned model version. Pinned rather than floating so a model change cannot silently become an extra variable between two runs that are supposed to differ only in egress policy."
  type        = string
  default     = "2026-03-17"
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

variable "demo_ui_service_account" {
  description = "Kubernetes service account bound to the demo UI workload identity. Must match deploy/kustomize/demo-ui/serviceaccount.yaml."
  type        = string
  default     = "demo-ui"
}

variable "workflow_service_account" {
  description = "Kubernetes service account bound to the workflow workload identity."
  type        = string
  default     = "workflow-workload-identity"
}

variable "endpoint_image_tag" {
  description = <<-EOT
    Tag of the two controlled-endpoint images in ACR, published by `task build:services`.

    Leave EMPTY on a first apply. The images do not exist yet at that point, and a
    Container App pointed at an absent image fails to provision a revision. Empty means
    "run the placeholder image"; `task build:deploy-endpoints` then applies the real tag.

    Once you have deployed real images, put ENDPOINT_IMAGE_TAG=latest in your .env.
    The root Taskfile loads it, so `task cloud:up` will keep the endpoints on their real
    images instead of rolling them back to the placeholder.

    ONE TAG FOR BOTH ENDPOINTS, deliberately. Both images come out of one
    services/Dockerfile in one `build:services` run. The policy API's success is only a
    usable control for the receiver's silence if the two cannot drift apart in base layer
    or dependency version, and a single tag makes that divergence impossible to express.

    These two images are the demo's WITNESSES, not its subject — the agent image is the
    thing that must be digest-pinned (infra/k8s var.agent_image_digest). A tag is
    acceptable here.
  EOT
  type        = string
  default     = ""
}

variable "agent_deployer_service_account" {
  description = "Kubernetes service account used by the one-shot Job that creates agent versions. Separate from the workflow account so deploy rights and invoke rights are independently revocable."
  type        = string
  default     = "agent-deployer"
}

variable "agent_name_audit" {
  description = "Hosted agent carrying the Audit egress policy. Audit and Enforced are deployed as two separately named agents rather than two versions of one, so both can be invoked without a switchover step that could be forgotten mid-demo."
  type        = string
  default     = "containment-demo-audit"
}

variable "agent_name_enforced" {
  description = "Hosted agent carrying the Enforced egress policy. Must run the SAME image digest as the Audit agent."
  type        = string
  default     = "containment-demo-enforced"
}

#############################################
# POSTGRES — Dapr workflow state store (Phase 8)
#############################################

variable "enable_state_store" {
  description = <<-EOT
    Create the PostgreSQL Flexible Server that backs Dapr Workflow state.

    Defaults to false because no phase before 8 reads from it. The server would sit idle
    and billing, and it adds a resource to every teardown, so it is created when it is
    needed rather than kept warm for a future phase. Set this to true when Phase 8 begins.

    The default region (canadacentral) permits Flexible Server, so this flag is now purely
    about cost and lifecycle, not availability. It began as an availability workaround:
    the subscription is restricted from provisioning Flexible Server in eastus2, where the
    containment environment previously ran, and Flexible Server uses VNet injection rather
    than a private endpoint, so the server is pinned to its subnet's region and could not
    simply live elsewhere. That conflict was resolved by moving the whole environment to
    canadacentral.

    If the region ever changes again, check availability first. Surveyed 2026-10-08:
    swedencentral, centralus, westus3, northcentralus and canadacentral were unrestricted;
    eastus, eastus2, westus2, southcentralus and canadaeast were not. A restricted region
    reports "The value of the 'Version' should be in: []", which names the wrong cause --
    check the capabilities API for restricted: Enabled. Neighbouring regions do not share
    the restriction: canadacentral is clear while canadaeast is not.
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

#############################################
# MANAGED NETWORK ISOLATION (PROPOSED, ONE-WAY)
#############################################

variable "managed_network_isolation_mode" {
  description = <<-EOT
    Outbound isolation mode of the Foundry managed network (hosted agents run in it).

    AllowOnlyApprovedOutbound is deny-by-default at the NETWORK layer. Learn
    (managed-virtual-network, read 2026-10-09): switching to it cannot be undone
    (no return to AllowInternetOutbound; reverting means redeploying the account), and any FQDN rule
    creates a managed Azure Firewall (billable). Managed-network outbound traffic is not logged
    yet, so a network-layer block will NOT appear in our evidence queries.

    The account was created as AllowInternetOutbound (compatibility.md B9g); nothing set it.
  EOT
  type        = string
  default     = "AllowOnlyApprovedOutbound"

  validation {
    condition     = contains(["AllowInternetOutbound", "AllowOnlyApprovedOutbound"], var.managed_network_isolation_mode)
    error_message = "Use AllowInternetOutbound or AllowOnlyApprovedOutbound."
  }
}

variable "managed_network_firewall_sku" {
  description = <<-EOT
    SKU of the managed Azure Firewall that FQDN rules create. Learn: cannot be changed after the
    firewall exists. Basic is cheaper; Standard is the documented default. OWNER DECISION before apply.
  EOT
  type        = string
  default     = "Basic"

  validation {
    condition     = contains(["Basic", "Standard"], var.managed_network_firewall_sku)
    error_message = "Use Basic or Standard."
  }
}

variable "managed_network_extra_fqdns" {
  description = <<-EOT
    Extra FQDNs (ports 80/443 only) allowed at the network layer, beyond the two controlled
    endpoints and Application Insights. Learn lists identity and mcr.microsoft.com hosts for Agents;
    add only what testing shows is needed, so the allow list stays minimal.
  EOT
  type        = list(string)
  default     = []
}
