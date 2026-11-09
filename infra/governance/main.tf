terraform {
  required_version = ">= 1.5"
  required_providers {
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2"
    }
  }
}

# Separate state: this track cannot plan changes to the tested baseline.
data "terraform_remote_state" "cloud" {
  backend = "local"
  config = {
    path = "${path.module}/../cloud/terraform.tfstate"
  }
}

locals {
  cloud = data.terraform_remote_state.cloud.outputs
  names = {
    all     = "containment-demo-governance-all"
    network = "containment-demo-governance-network"
    audit   = "containment-demo-governance-audit"
  }
  policy_host    = regex("^https://([^/]+)", local.cloud.policy_api_url)[0]
  receiver_host  = regex("^https://([^/]+)", local.cloud.test_receiver_url)[0]
  telemetry_host = regex("IngestionEndpoint=https://([^/;]+)", local.cloud.application_insights_connection_string)[0]
}

data "azapi_resource" "baseline_policy" {
  type                   = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                   = local.cloud.rai_policy_enforced_name
  parent_id              = local.cloud.foundry_account_id
  response_export_values = ["*"]
}

resource "azapi_resource" "policy" {
  for_each                  = local.names
  type                      = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                      = each.value
  parent_id                 = local.cloud.foundry_account_id
  schema_validation_enabled = false
  response_export_values    = ["*"]
  locks                     = [local.cloud.foundry_account_id]
  body = {
    properties = {
      basePolicyName = data.azapi_resource.baseline_policy.output.properties.basePolicyName
      type           = "UserManaged"
      mode           = data.azapi_resource.baseline_policy.output.properties.mode
      contentFilters = data.azapi_resource.baseline_policy.output.properties.contentFilters
      egressPolicy = {
        mode          = each.key == "audit" ? "Audit" : "Enforced"
        defaultAction = "Deny"
        rules = [for name, host in merge(
          { policy = local.policy_host, telemetry = local.telemetry_host },
          each.key == "all" ? { receiver = local.receiver_host } : {}
          ) : {
          name     = "allow-${name}"
          ruleType = "Fqdn"
          match    = { host = host }
          action   = { actionType = "Allow" }
        }]
      }
    }
  }
  lifecycle {
    precondition {
      condition = !contains(
        [local.cloud.rai_policy_audit_name, local.cloud.rai_policy_enforced_name], each.value
      )
      error_message = "Never overwrite either baseline policy."
    }
  }
}

output "policies" {
  value = { for name, policy in azapi_resource.policy : name => policy.id }
}
