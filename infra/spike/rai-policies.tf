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
  # Copied VERBATIM from the Microsoft.DefaultV2 system policy on this account, read with
  # `task spike:show-base` on 2026-10-07.
  #
  # Content filtering is NOT the variable under test. A custom policy is required to
  # supply its own contentFilters - the create fails with "Content filters cannot be null"
  # otherwise - so the safest filters to supply are the platform's own defaults,
  # unmodified. Shared by both policies through this one local, so Audit and Enforced are
  # identical by construction rather than by review, and no difference in content
  # filtering can be mistaken for a difference in egress behaviour.
  #
  # Do not hand-edit. Re-read it from the account if the base policy changes.
  content_filters = [
    {
      name              = "Hate"
      source            = "Prompt"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name              = "Hate"
      source            = "Completion"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name              = "Sexual"
      source            = "Prompt"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name              = "Sexual"
      source            = "Completion"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name              = "Violence"
      source            = "Prompt"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name              = "Violence"
      source            = "Completion"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name              = "Selfharm"
      source            = "Prompt"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name              = "Selfharm"
      source            = "Completion"
      severityThreshold = "Medium"
      blocking          = true
      enabled           = true
      action            = "NONE"
    },
    {
      name     = "Jailbreak"
      source   = "Prompt"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "Protected Material Text"
      source   = "Completion"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "Protected Material Code"
      source   = "Completion"
      blocking = false
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "DefenderForAI"
      source   = "Prompt"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "DefenderForAI"
      source   = "Completion"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "DefenderForAI"
      source   = "PostRun"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "DefenderForAI"
      source   = "PostToolCall"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "DefenderForAI"
      source   = "PreRun"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "DefenderForAI"
      source   = "PreToolCall"
      blocking = true
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "Indirect Attack"
      source   = "Prompt"
      blocking = false
      enabled  = true
      action   = "NONE"
    },
    {
      name     = "Indirect Attack"
      source   = "PostToolCall"
      blocking = false
      enabled  = true
      action   = "NONE"
    },
  ]

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
      # A custom RAI policy must derive from a base policy. Omitting this fails the
      # create with "Resource has invalid base policy", which is how we found out.
      basePolicyName = var.rai_base_policy_name
      type           = "UserManaged"

      # CONTENT SAFETY behaviour, not network behaviour. Held constant across both
      # policies precisely so it cannot be mistaken for the variable under test.
      # "Blocking" is the value the system policies report on this account and API
      # version, so it is known-good rather than guessed.
      mode = "Blocking"

      contentFilters = local.content_filters

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
      basePolicyName = var.rai_base_policy_name
      type           = "UserManaged"

      mode = "Blocking"

      contentFilters = local.content_filters

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
