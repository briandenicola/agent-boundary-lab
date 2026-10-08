#############################################
# PROJECT CONNECTION — APPLICATION INSIGHTS
#
# WITHOUT THIS RESOURCE THE DEMO CANNOT BE OBSERVED.
#
# docs/compatibility.md C1 and C4: a project connection to Application Insights is the
# only path platform egress decision records take. There is no diagnostic-settings
# category for them and no confirmation they reach a custom OTLP endpoint. With no
# connection the platform layer is silent, every run is INCONCLUSIVE by construction,
# and the one thing this repository exists to observe is unobservable.
#
# The failure mode is the nasty kind: the agent runs, the tools behave, the application
# traces look fine, and only the platform evidence is missing. That reads exactly like
# "the policy did nothing".
#
#############################################
# VERIFIED SCHEMA — read from installed SDK source on 2026-10-08
#
# Everything below was read out of the packages at
# /opt/az/lib/python3.14/site-packages, not from documentation prose:
#
#   Resource type   Microsoft.CognitiveServices/accounts/projects/connections
#                   azure/mgmt/cognitiveservices/operations/_operations.py:2510
#   API version     2026-05-15-preview
#                   azure/mgmt/cognitiveservices/_configuration.py:51
#   category        "AppInsights"
#                   models/_enums.py:481, ConnectionCategory.APP_INSIGHTS
#   authType        "ApiKey", the model discriminator on
#                   ApiKeyAuthConnectionProperties (models/_models.py:1563)
#   credentials     { "key": ... }, ConnectionApiKey (models/_models.py:3207)
#
# And critically, what the CONSUMER requires. azure/ai/projects/operations/
# _patch_telemetry.py:44-66 — the SDK call that resolves a project's Application
# Insights — lists connections of type AppInsights, takes the first, and then:
#
#     if isinstance(connection.credentials, ApiKeyCredentials): ...
#     else: raise ValueError("... does not use API Key credentials.")
#     self._connection_string = connection.credentials.api_key
#
# with `api_key` serialised as the wire field `key`
# (azure/ai/projects/models/_models.py:66).
#
# So: the "API key" of an AppInsights connection IS the Application Insights connection
# string. Not an instrumentation key, not a resource id. An AAD or ManagedIdentity
# connection would be accepted by ARM and then rejected by the consumer.
#
# The same file notes "there can't be more than one AppInsights connection." One
# resource, no count, no loop.
#
# Live shape of a project connection confirmed by reading an existing one back from
# ARM on a sibling account on the same date (upright-ape-41734-project).
#
# NOT VERIFIED: what `target` should hold for this category. The SDK docstring gives
# target examples for AzureOpenAI, CognitiveService and CognitiveSearch and nothing for
# AppInsights, and no AppInsights connection existed anywhere in the subscription to
# read back. We set the Application Insights ARM resource id, matching how the sibling
# AzureOpenAI connection carries its resource id. The telemetry read path above never
# touches `target`, so a wrong value here cannot silence the evidence — it is metadata.
#############################################

resource "azapi_resource" "project_app_insights_connection" {
  type = "Microsoft.CognitiveServices/accounts/projects/connections@2026-05-15-preview"
  name = "appinsights-connection"

  # A child of the PROJECT, not the account. Agent telemetry resolves through the
  # project, and an account-scoped connection is a different resource path that the
  # telemetry lookup does not read.
  parent_id = azapi_resource.project.id

  schema_validation_enabled = false
  response_export_values    = ["properties.category", "properties.authType", "properties.target"]

  body = {
    properties = {
      category = "AppInsights"
      authType = "ApiKey"

      # See NOT VERIFIED above. Metadata only.
      target = azurerm_application_insights.main.id

      # Scoped to this project. There is only one project on this account, so sharing it
      # account-wide would widen the blast radius for no benefit.
      isSharedToAll = false

      metadata = {
        ResourceId = azurerm_application_insights.main.id
        ApiType    = "Azure"
      }
    }
  }

  # The connection string is a credential. azapi keeps sensitive_body out of plan output
  # and out of the rendered body, which `body` does not do.
  sensitive_body = {
    properties = {
      credentials = {
        key = azurerm_application_insights.main.connection_string
      }
    }
  }

  # The existing Application Insights resource, reused. A second component would split
  # the evidence in two: application traces in one, platform egress decisions in the
  # other, and no way to correlate them.
  depends_on = [azurerm_application_insights.main]
}
