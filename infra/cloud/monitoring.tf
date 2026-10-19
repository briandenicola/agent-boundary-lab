#############################################
# MONITORING — Log Analytics and Application Insights
#
# This is where the demo's evidence lands, and it is the only place the three layers can
# be correlated. Application traces, platform egress decisions and endpoint receipts all
# arrive here. docs/telemetry-map.md records the observed run-id join and platform
# egress decisions in AppDependencies, separate from managed-network events.
#############################################

resource "azurerm_log_analytics_workspace" "main" {
  name                = local.loganalytics_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"

  # Long enough to compare runs across a few days of iteration, short enough that a
  # forgotten environment is not an open-ended bill.
  retention_in_days = 30

  tags = local.common_tags
}

resource "azurerm_application_insights" "main" {
  name                = local.appinsights_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  application_type    = "web"
  workspace_id        = azurerm_log_analytics_workspace.main.id

  tags = local.common_tags
}

locals {
  foundry_diagnostic_targets = {
    account = azapi_resource.foundry.id
    project = azapi_resource.project.id
  }
  container_log_streams = [
    "Microsoft-ContainerLogV2",
    "Microsoft-KubeEvents",
    "Microsoft-KubePodInventory",
  ]
}

data "azurerm_monitor_diagnostic_categories" "foundry" {
  for_each = local.foundry_diagnostic_targets

  resource_id = each.value
}

# Add our destination without taking ownership of governance-managed settings.
resource "azurerm_monitor_diagnostic_setting" "foundry" {
  for_each = local.foundry_diagnostic_targets

  name                           = "${local.resource_name}-diagnostics"
  target_resource_id             = each.value
  log_analytics_workspace_id     = azurerm_log_analytics_workspace.main.id
  log_analytics_destination_type = "Dedicated"

  dynamic "enabled_log" {
    for_each = data.azurerm_monitor_diagnostic_categories.foundry[each.key].log_category_types
    content {
      category = enabled_log.value
    }
  }

  dynamic "enabled_metric" {
    for_each = data.azurerm_monitor_diagnostic_categories.foundry[each.key].metrics
    content {
      category = enabled_metric.value
    }
  }
}

# The monitoring add-on alone did not create a DCR or association on the rebuild.
# Logs/events avoid ContainerInventory's environment-variable inventory.
resource "azurerm_monitor_data_collection_rule" "containers" {
  name                = "${local.resource_name}-container-logs"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_log_analytics_workspace.main.location

  destinations {
    log_analytics {
      name                  = "workspace"
      workspace_resource_id = azurerm_log_analytics_workspace.main.id
    }
  }

  data_flow {
    streams      = local.container_log_streams
    destinations = ["workspace"]
  }

  data_sources {
    extension {
      name           = "ContainerInsightsExtension"
      extension_name = "ContainerInsights"
      streams        = local.container_log_streams
      extension_json = jsonencode({
        dataCollectionSettings = {
          interval               = "1m"
          namespaceFilteringMode = "Off"
          namespaces             = []
          enableContainerLogV2   = true
        }
      })
    }
  }

  tags = local.common_tags
}

resource "azurerm_monitor_data_collection_rule_association" "containers" {
  name                    = "ContainerInsightsExtension"
  target_resource_id      = azurerm_kubernetes_cluster.main.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.containers.id
}

# PROPOSED, not applied. Evidence dashboard built from docs/kql-queries.md. The queries
# target the Log Analytics workspace so one workbook reads both AppDependencies and
# ContainerAppConsoleLogs_CL. Workbook names must be GUIDs, so it is derived from a
# random_uuid, never from a variable.
resource "random_uuid" "evidence_workbook" {}

resource "azurerm_application_insights_workbook" "egress_evidence" {
  name                = random_uuid.evidence_workbook.result
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  display_name        = "${local.resource_name} egress evidence"
  source_id           = lower(azurerm_log_analytics_workspace.main.id)
  category            = "workbook"

  data_json = jsonencode(jsondecode(templatefile("${path.module}/workbooks/egress-evidence.workbook.json", {
    workspace_id = azurerm_log_analytics_workspace.main.id
  })))

  tags = local.common_tags
}
