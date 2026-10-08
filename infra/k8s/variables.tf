#############################################
# VARIABLES
#
# Everything that is network-addressable, named, or versioned is a variable or an output
# of infra/cloud. There are no literal hostnames, addresses or CIDRs in this module, and
# none should be added: a value that is correct only for one apply is a value that will
# be wrong during the demo.
#############################################

variable "cloud_state_path" {
  description = "Path to the infra/cloud local state file, relative to this module. The cloud module must have been applied first."
  type        = string
  default     = "../cloud/terraform.tfstate"
}

#############################################
# The agent image
#############################################

variable "agent_image_repository" {
  description = "ACR repository holding the hosted-agent image. The deploy init container runs the SAME image with a different entrypoint."
  type        = string
  default     = "containment-demo-agent"
}

variable "agent_image_digest" {
  description = <<-EOT
    Digest of the agent image, including the `sha256:` prefix.

    THIS IS THE EXPERIMENT'S CONTROL. Both agent versions must run this exact digest, or
    Audit and Enforced differ in more than the policy and the result proves nothing.
    Never substitute a tag here. Read the current value with `task build:agent-digest`.
  EOT
  type        = string

  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.agent_image_digest))
    error_message = "agent_image_digest must be a full sha256 digest, e.g. sha256:<64 hex chars>. A tag is not acceptable: tags are mutable and would let the two agent versions run different code."
  }
}

#############################################
# The deploy init container
#############################################

variable "agent_deploy_module" {
  description = <<-EOT
    Python module entrypoint the init container executes, as `python -m <module>`.

    CONTRACT WITH THE AGENT IMAGE. The image's own ENTRYPOINT starts the Foundry protocol
    adapter; the init container overrides it to run the deployment module instead. The
    module exposes `main()` under an `if __name__ == "__main__"` guard and takes no
    arguments — all of its configuration arrives as DEMO_ environment variables.

    If the module is renamed in src/containment_demo, this default must move with it or
    the pod fails in init with ModuleNotFoundError.
  EOT
  type        = string
  default     = "containment_demo.deploy"
}

variable "agent_deploy_enabled" {
  description = "Whether the harness pod runs the deploy init container. Set false to bring the harness up without touching the Foundry data plane."
  type        = bool
  default     = true
}

#############################################
# Harness pod shape
#############################################

variable "harness_name" {
  description = "Name of the harness Deployment and of its pod label selector."
  type        = string
  default     = "agent-harness"
}

variable "harness_replicas" {
  description = "Harness replicas. One. The init container publishes agent versions, and a second replica would race it."
  type        = number
  default     = 1

  validation {
    condition     = var.harness_replicas == 1
    error_message = "The harness must run exactly one replica while the deploy init container is part of the pod."
  }
}

variable "harness_cpu_request" {
  description = "CPU request for the harness and init containers."
  type        = string
  default     = "100m"
}

variable "harness_memory_request" {
  description = "Memory request for the harness and init containers."
  type        = string
  default     = "256Mi"
}

variable "harness_memory_limit" {
  description = "Memory limit for the harness and init containers."
  type        = string
  default     = "1Gi"
}

#############################################
# Cluster access (operator-side)
#############################################

variable "aks_entra_server_application_id" {
  description = "Well-known Entra application ID of the AKS AAD server, used as kubelogin's --server-id. Constant across every AKS cluster in every public-cloud tenant; a variable only so a sovereign cloud can override it."
  type        = string
  default     = "6dae42f8-4368-4678-94ff-3960e28e3630"
}

variable "kubelogin_login_mode" {
  description = "kubelogin credential source for the OPERATOR running terraform. Not used by any workload. `azurecli` reuses the session the azurerm provider already depends on; `devicecode` works without it."
  type        = string
  default     = "azurecli"
}
