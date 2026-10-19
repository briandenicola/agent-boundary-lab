"""Offline guards for diagnostic routing without payload or environment inventory."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MONITORING = ROOT / "infra/cloud/monitoring.tf"


def block(source: str, kind: str, resource_type: str, name: str) -> str:
    match = re.search(rf'(?ms)^{kind} "{resource_type}" "{name}" \{{\n(.*?)^\}}', source)
    assert match, name
    return match[1]


def test_foundry_account_and_project_use_the_same_workspace_and_live_categories() -> None:
    source = MONITORING.read_text()
    assert "account = azapi_resource.foundry.id" in source
    assert "project = azapi_resource.project.id" in source
    categories = block(source, "data", "azurerm_monitor_diagnostic_categories", "foundry")
    settings = block(source, "resource", "azurerm_monitor_diagnostic_setting", "foundry")
    for body in (categories, settings):
        assert "for_each = local.foundry_diagnostic_targets" in body
    assert "resource_id = each.value" in categories
    assert "target_resource_id             = each.value" in settings
    assert "log_analytics_workspace_id     = azurerm_log_analytics_workspace.main.id" in settings
    assert (
        "data.azurerm_monitor_diagnostic_categories.foundry[each.key].log_category_types"
        in settings
    )
    assert "data.azurerm_monitor_diagnostic_categories.foundry[each.key].metrics" in settings
    insights = block(source, "resource", "azurerm_application_insights", "main")
    assert "workspace_id        = azurerm_log_analytics_workspace.main.id" in insights
    assert "setByPolicy" not in settings


def test_container_collection_is_bound_to_aks_and_keeps_environment_inventory_off() -> None:
    source = MONITORING.read_text()
    streams = re.search(r"(?s)container_log_streams = \[(.*?)\]", source)
    assert streams
    assert set(re.findall(r'"([^"]+)"', streams[1])) == {
        "Microsoft-ContainerLogV2",
        "Microsoft-KubeEvents",
        "Microsoft-KubePodInventory",
    }
    rule = block(source, "resource", "azurerm_monitor_data_collection_rule", "containers")
    assert "workspace_resource_id = azurerm_log_analytics_workspace.main.id" in rule
    assert rule.count("local.container_log_streams") == 2
    assert 'extension_name = "ContainerInsights"' in rule
    assert "enableContainerLogV2   = true" in rule
    assert 'namespaceFilteringMode = "Off"' in rule
    binding = block(
        source, "resource", "azurerm_monitor_data_collection_rule_association", "containers"
    )
    assert "target_resource_id      = azurerm_kubernetes_cluster.main.id" in binding
    assert "data_collection_rule_id = azurerm_monitor_data_collection_rule.containers.id" in binding
    cluster = (ROOT / "infra/cloud/aks.tf").read_text()
    assert "msi_auth_for_monitoring_enabled = true" in cluster


def test_logging_status_is_read_only_and_labels_missing_rows_inconclusive() -> None:
    source = (ROOT / "tasks/Taskfile.cloud.yml").read_text()
    match = re.search(r"(?ms)^  logging-status:\n(.*?)(?=^  (?:[\w-]+:|#)|\Z)", source)
    assert match
    status = match[1]
    assert "- task: target-check" in status
    assert "diagnostic-settings list" in status
    assert "data-collection rule association list" in status
    assert "log-analytics query" in status
    assert '"inconclusive"' in status
    assert "LogMessage" not in status
    assert not re.search(r"\b(create|update|delete|apply|import)\b", status)


def test_agent_image_checks_the_lazily_imported_runtime_stack() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "from mcp.types import CacheableResult" in dockerfile
    assert "import litellm.responses.mcp.chat_completions_handler" in dockerfile
