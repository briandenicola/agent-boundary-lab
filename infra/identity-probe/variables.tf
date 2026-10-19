variable "tenant_id" {
  type = string
}

variable "allowed_user_id" {
  type      = string
  sensitive = true
}

variable "denied_user_id" {
  type      = string
  sensitive = true
  validation {
    condition     = var.denied_user_id != var.allowed_user_id
    error_message = "Use distinct existing test users."
  }
}

variable "foundry_project_resource_id" {
  type = string
  validation {
    condition     = can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft.CognitiveServices/accounts/[^/]+/projects/[^/]+$", var.foundry_project_resource_id))
    error_message = "Provide the existing Foundry project ARM ID."
  }
}

variable "foundry_endpoint" {
  type = string
}

variable "foundry_api_service_principal_id" {
  type        = string
  description = "Existing tenant service-principal OBJECT ID for the actual https://ai.azure.com resource, not its application/client ID."
}

variable "foundry_delegated_scope" {
  type        = string
  description = "Verified enabled delegated scope VALUE published by that resource. No default is guessed."
}

variable "foundry_audience" {
  type        = string
  description = "Verified expected access-token aud for the resource; must match its appId or servicePrincipalNames."
}

variable "aks_oidc_issuer_url" {
  type = string
}

variable "namespace" {
  type    = string
  default = "agent-boundary-lab"
}

variable "agent_name" {
  type    = string
  default = "containment-demo-audit"
}

variable "probe_image" {
  type        = string
  description = "Existing digest-pinned agent/publisher image containing /opt/deploy-venv; this probe mounts its own script and does not modify hosted versions."
  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.probe_image))
    error_message = "Use the existing immutable image digest, not a tag."
  }
}

variable "sidecar_image" {
  type        = string
  description = "Owner-verified digest for mcr.microsoft.com/entra-sdk/auth-sidecar:1.0.0-azurelinux3.0-distroless."
  validation {
    condition     = can(regex("^mcr.microsoft.com/entra-sdk/auth-sidecar@sha256:[0-9a-f]{64}$", var.sidecar_image))
    error_message = "Resolve and verify the documented sidecar tag, then provide its immutable digest."
  }
}
