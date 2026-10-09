#############################################
# MONITORING — Log Analytics and Application Insights
#
# This is where the demo's evidence lands, and it is the only place the three layers can
# be correlated. Application traces, platform egress decisions and endpoint receipts all
# arrive here and are joined on `demo_run_id`.
#
# The platform emits its egress decisions into the `traces` table with
# `message == "Network egress decision"`. The sub-field names inside that record are
# undocumented; docs/telemetry-map.md records the real ones once observed, and until it
# does, a missing decision record is INCONCLUSIVE and never a pass.
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
