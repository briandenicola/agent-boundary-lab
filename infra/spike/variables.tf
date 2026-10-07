#############################################
# VARIABLES
#
# Names are not configurable. Every resource name is derived from the generated random
# name in locals.tf, which keeps naming a convention rather than a decision and makes
# teardown-by-tag reliable.
#############################################

variable "region" {
  description = "Azure region for the spike."
  type        = string
  default     = "eastus2"
}

variable "tags" {
  description = <<-EOT
    Application tag used to find and delete everything this module created.

    Deliberately distinct from the main demo's tag. `task spike:down` deletes resource
    groups by this tag, and sharing a tag with the real environment would make a routine
    spike teardown capable of destroying the demo.
  EOT
  type        = string
  default     = "Agent Boundary Lab Spike"
}

variable "allowed_host" {
  description = <<-EOT
    The single hostname the egress policy allows.

    For stage 1 this only has to be a syntactically valid FQDN: the question being asked
    is whether ARM accepts the configuration at all, not whether traffic to this host
    succeeds. It is replaced by the real policy API hostname in the full module.
  EOT
  type        = string
  default     = "policy-api.invalid.example.com"
}

variable "rai_base_policy_name" {
  description = <<-EOT
    The RAI policy this policy derives from.

    A custom RAI policy must name a base policy; omitting it fails the create with
    "Resource has invalid base policy". The valid names are account- and
    API-version-specific, so confirm the real value for your account with
    `task spike:base-policies` rather than trusting this default.
  EOT
  type        = string
  default     = "Microsoft.DefaultV2"
}
