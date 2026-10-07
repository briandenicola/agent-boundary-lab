#############################################
# RANDOM — the source of every name and address in this module
#
# Convention over configuration: nothing here is a variable, so two applies cannot
# collide and no name has to be chosen, reviewed or remembered.
#############################################

resource "random_pet" "this" {}

resource "random_id" "this" {
  byte_length = 2
}

resource "random_uuid" "guid" {}

# The VNet's second octet. Randomised so repeated applies in one subscription do not
# produce overlapping address space, which would make peering or a shared jumpbox fail in
# ways that look like a platform problem rather than a collision.
resource "random_integer" "vnet_cidr" {
  min = 10
  max = 250
}

# AKS service and pod CIDRs must not overlap the VNet, so they are drawn from ranges the
# VNet octet above can never take.
resource "random_integer" "services_cidr" {
  min = 64
  max = 99
}

resource "random_integer" "pod_cidr" {
  min = 100
  max = 127
}

# Bearer token for the agent's authenticated diagnostic route.
#
# Generated, never supplied, and never defaulted: settings.py refuses to start with
# diagnostics enabled and a token shorter than 16 characters, so an operator cannot leave
# a deterministic evidence-producing endpoint open by forgetting to set this.
resource "random_password" "diagnostics_token" {
  length  = 48
  special = false
}

# PostgreSQL administrator password for the Dapr workflow state store.
resource "random_password" "postgres_admin" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}
