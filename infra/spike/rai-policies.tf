#############################################
# RAI POLICIES WITH NETWORK EGRESS — the other half of the probe
#
# Two policies, identical in every respect except the egress mode. That is the entire
# experimental design: the same image digest runs under both, so the policy is the only
# variable between an allowed run and a denied one.
#
# THE TWO `mode` PROPERTIES ARE NOT THE SAME THING. Confusing them silently invalidates
# the demo, so note the distinction carefully:
#
#   properties.mode               -> CONTENT SAFETY filtering behaviour.
#                                    Values: Default | Deferred | Blocking | Asynchronous_filter
#   properties.egressPolicy.mode  -> NETWORK egress behaviour. This is the one we vary.
#                                    Values: Audit | Enforced
#
# `properties.mode` is held constant at "Default" in both policies below precisely so
# that it cannot be mistaken for the variable under test.
#
# egressPolicy.defaultAction defaults to "Deny" and is stated explicitly anyway. Relying
# on an undocumented-in-our-code default for a fail-closed control is how a demo ends up
# accidentally proving nothing.
#
# Rule matching is on host (FQDN) and optional path only. There is no port matching and
# no IP matching in the preview, so the allowlist cannot be expressed any more narrowly
# than a hostname.
#############################################

locals {
  # Shared by both policies so they cannot drift apart. If the allow rule differed
  # between Audit and Enforced, a difference in outcome would no longer be attributable
  # to the mode.
  egress_allow_rules = [
    {
      name     = "allow-policy-api"
      ruleType = "Fqdn"
      match = {
        host = var.allowed_host
      }
      action = {
        actionType = "Allow"
      }
    }
  ]
}

resource "azapi_resource" "rai_policy_audit" {
  type                      = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                      = "egress-audit"
  parent_id                 = azapi_resource.foundry.id
  schema_validation_enabled = false
  response_export_values    = ["*"]

  body = {
    properties = {
      # Content safety behaviour. Held constant; not the variable under test.
      mode = "Default"

      egressPolicy = {
        # Network behaviour. Audit observes and records without blocking, which gives us
        # a baseline run proving the un-allowlisted call genuinely reaches its
        # destination when nothing is stopping it.
        mode          = "Audit"
        defaultAction = "Deny"
        rules         = local.egress_allow_rules
      }
    }
  }
}

resource "azapi_resource" "rai_policy_enforced" {
  type                      = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                      = "egress-enforced"
  parent_id                 = azapi_resource.foundry.id
  schema_validation_enabled = false
  response_export_values    = ["*"]

  body = {
    properties = {
      mode = "Default"

      egressPolicy = {
        mode          = "Enforced"
        defaultAction = "Deny"
        rules         = local.egress_allow_rules
      }
    }
  }

  # Created after the Audit policy rather than in parallel. Two preview resources of the
  # same type racing on one account produced no benefit worth the risk of an ambiguous
  # failure, and a serialised apply makes it obvious which one ARM objected to.
  depends_on = [azapi_resource.rai_policy_audit]
}
