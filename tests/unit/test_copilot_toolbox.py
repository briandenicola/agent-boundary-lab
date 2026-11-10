from __future__ import annotations

import copy
import io
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from scripts.copilot_toolbox_plan import check_grants, check_plan

from containment_demo import copilot_toolbox as isolated
from containment_demo.deploy import DeploymentError, DriftError
from tests.unit.test_deploy import ARM_PREFIX, FakeModels
from tests.unit.test_governance_hosted import Operations, config, settings

ACCOUNT = ARM_PREFIX.rsplit("/raiPolicies", 1)[0]


def configuration(**changes: Any) -> isolated.Configuration:
    baseline = config()
    project = "synthetic-copilot"
    return isolated.Configuration.model_validate(
        {
            "project_name": project,
            "project_id": f"{ACCOUNT}/projects/{project}",
            "agent_name": "synthetic-copilot-agent",
            "mcp_url": "https://separate-mcp.example.com/mcp",
            "mcp_app_name": "synthetic-copilot-mcp",
            "rai_policy_id": f"{ARM_PREFIX}/copilot-toolbox",
            "agent_image": "example.azurecr.io/containment-demo-copilot-toolbox-agent@sha256:"
            + "c" * 64,
            "toolbox_endpoint": (
                baseline.endpoint.replace(baseline.foundry_project_name, project)
                + "/toolboxes/servicing/versions/1/mcp?api-version=v1"
            ),
            "toolbox_policy_tool": "servicing___get_servicing_policy",
            **changes,
        }
    )


def test_isolated_deployment_is_idempotent_and_does_not_change_baseline(tmp_path: Path) -> None:
    baseline, runtime, item = config(), settings(), configuration()
    original = copy.deepcopy(baseline)
    cfg = item.deployment_settings(baseline)
    client = SimpleNamespace(agents=Operations())
    journal = tmp_path / "deployment.json"
    first = isolated.deploy(client, FakeModels, cfg, runtime, item, journal)
    second = isolated.deploy(client, FakeModels, cfg, runtime, item, journal)
    assert first == second
    assert first["phase"] == "ready"
    assert first["facts"]["runtime_result"] == "unverified"
    assert client.agents.created == [item.agent_name]
    assert baseline == original
    assert cfg.endpoint != baseline.endpoint
    assert journal.stat().st_mode & 0o777 == 0o600
    actual = client.agents.get_version(item.agent_name, first["version"])
    env = actual.definition.environment_variables
    assert env["TOOLBOX_ENDPOINT"] == str(item.toolbox_endpoint)
    assert env["DEMO_TOOLBOX_POLICY_TOOL"] == item.toolbox_policy_tool
    assert env["DEMO_GOVERNANCE_MODE"] == "enforced"
    assert env["DEMO_POLICY_API_URL"] == str(runtime.policy_api_url)
    assert env["DEMO_TEST_RECEIVER_URL"] == str(runtime.test_receiver_url)
    assert actual.metadata == {"demo_track": isolated.TRACK}


def test_readiness_retry_resumes_the_recorded_version_without_creating_another(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, baseline, runtime = configuration(), config(), settings()
    cfg = item.deployment_settings(baseline)
    client = SimpleNamespace(agents=Operations())
    journal = tmp_path / "deployment.json"
    original_wait = isolated.wait_until_ready

    def timeout(*_: Any, **__: Any) -> None:
        raise DeploymentError("synthetic readiness timeout")

    monkeypatch.setattr(isolated, "wait_until_ready", timeout)
    with pytest.raises(DeploymentError, match="timeout"):
        isolated.deploy(client, FakeModels, cfg, runtime, item, journal)
    assert json.loads(journal.read_text())["phase"] == "waiting"
    monkeypatch.setattr(isolated, "wait_until_ready", original_wait)
    assert isolated.deploy(client, FakeModels, cfg, runtime, item, journal)["phase"] == "ready"
    assert client.agents.created == [item.agent_name]


@pytest.mark.parametrize(
    "failure", ["same-project", "wrong-account", "baseline-policy", "wrong-toolbox"]
)
def test_configuration_rejects_baseline_and_cross_project_targets(failure: str) -> None:
    baseline, item = config(), configuration()
    if failure == "same-project":
        item = configuration(
            project_name=baseline.foundry_project_name,
            project_id=f"{ACCOUNT}/projects/{baseline.foundry_project_name}",
            toolbox_endpoint=baseline.endpoint + "/toolboxes/t/versions/1/mcp?api-version=v1",
        )
    elif failure == "wrong-account":
        item = configuration(project_id="/subscriptions/foreign/projects/copilot")
    elif failure == "baseline-policy":
        item = configuration(rai_policy_id=baseline.rai_policy_enforced_id)
    else:
        item = configuration(
            toolbox_endpoint=baseline.endpoint + "/toolboxes/t/versions/1/mcp?api-version=v1"
        )
    with pytest.raises(DriftError):
        item.deployment_settings(baseline)


@pytest.mark.parametrize(
    "changes",
    [
        {"toolbox_endpoint": config().endpoint + "/toolboxes/t/mcp?api-version=v1"},
        {"toolbox_endpoint": str(configuration().toolbox_endpoint) + "&extra="},
        {"agent_image": "example.azurecr.io/containment-demo-agent@sha256:" + "c" * 64},
        {"mcp_url": "http://separate-mcp.example.com/mcp"},
    ],
)
def test_configuration_requires_pinned_isolated_transport(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        configuration(**changes)


@pytest.mark.parametrize("failure", ["foreign-version", "uncertain-write", "foreign-journal"])
def test_deployment_stops_before_creating_on_ownership_or_uncertain_write(
    tmp_path: Path,
    failure: str,
) -> None:
    item, baseline, runtime = configuration(), config(), settings()
    cfg = item.deployment_settings(baseline)
    client = SimpleNamespace(agents=Operations())
    journal = tmp_path / "deployment.json"
    if failure == "foreign-version":
        client.agents.create_version(
            item.agent_name,
            definition=isolated.definition_for(FakeModels, cfg, runtime, item),
            metadata={"demo_track": "someone-else"},
        )
        client.agents.created.clear()
    else:
        journal.write_text(
            json.dumps(
                {
                    "endpoint": cfg.endpoint if failure == "uncertain-write" else baseline.endpoint,
                    "phase": "create_requested" if failure == "uncertain-write" else "ready",
                }
            )
        )
    with pytest.raises((DriftError, DeploymentError)):
        isolated.deploy(client, FakeModels, cfg, runtime, item, journal)
    assert client.agents.created == []


def test_drifted_version_cannot_be_used_for_publication(tmp_path: Path) -> None:
    item, baseline, runtime = configuration(), config(), settings()
    cfg = item.deployment_settings(baseline)
    client = SimpleNamespace(agents=Operations())
    record = isolated.deploy(client, FakeModels, cfg, runtime, item, tmp_path / "deployment.json")
    actual = client.agents.get_version(item.agent_name, record["version"])
    actual.definition.environment_variables["DEMO_GOVERNANCE_MODE"] = "disabled"
    with pytest.raises(DriftError):
        isolated.read_version(client, FakeModels, cfg, runtime, item, record["version"])


def plan_for(
    address: str = "azapi_resource.policy", actions: list[str] | None = None
) -> dict[str, Any]:
    cloud = {
        "resource_name": "synthetic",
        "foundry_account_id": ACCOUNT,
        "acr_name": "syntheticacr",
    }
    return {
        "format_version": "1.2",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "data.terraform_remote_state.cloud",
                        "values": {"outputs": cloud},
                    }
                ]
            }
        },
        "resource_changes": [
            {
                "address": address,
                "mode": "managed",
                "change": {
                    "actions": actions if actions is not None else ["create"],
                    "before": None,
                    "after": {
                        "type": (
                            "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
                        ),
                        "parent_id": ACCOUNT,
                        "name": "synthetic-copilot-toolbox",
                    },
                },
            }
        ],
    }


def test_plan_guard_accepts_only_dedicated_policy_scope() -> None:
    check_plan(plan_for())
    plan = plan_for()
    plan["resource_changes"][0]["change"]["after"]["name"] = "baseline"
    with pytest.raises(ValueError, match="isolated scope"):
        check_plan(plan)


def test_plan_guard_requires_a_distinct_telemetry_connection_name() -> None:
    plan = plan_for("azapi_resource.project_insights")
    connection = plan["resource_changes"][0]["change"]["after"]
    connection.update(
        type="Microsoft.CognitiveServices/accounts/projects/connections@2026-05-15-preview",
        parent_id=ACCOUNT + "/projects/synthetic-copilot",
        name="copilot-appinsights-connection",
    )
    check_plan(plan)
    connection["name"] = "appinsights-connection"
    with pytest.raises(ValueError, match="isolated scope"):
        check_plan(plan)


def test_plan_guard_validates_created_mcp_resource_provider_scope() -> None:
    plan = plan_for("azapi_resource.mcp", ["update"])
    app = plan["resource_changes"][0]["change"]["after"]
    group = ACCOUNT.split("/providers/")[0]
    app.update(
        type="Microsoft.App/containerApps@2025-01-01",
        parent_id=group,
        name="synthetic-copilot-mcp",
        id=group + "/providers/Microsoft.App/containerApps/synthetic-copilot-mcp",
    )
    check_plan(plan)
    app["id"] = group + "/providers/Microsoft.App/containerApps/baseline"
    with pytest.raises(ValueError, match="resource ID"):
        check_plan(plan)


@pytest.mark.parametrize(
    ("address", "actions"),
    [
        ("azurerm_container_app.policy_api", ["update"]),
        ("azapi_resource.project_host", ["update"]),
        ("azapi_resource.policy", ["delete"]),
        ("azapi_resource.policy", ["delete", "create"]),
    ],
)
def test_plan_guard_rejects_shared_or_destructive_changes(
    address: str,
    actions: list[str],
) -> None:
    with pytest.raises(ValueError, match="dedicated"):
        check_plan(plan_for(address, actions))


@pytest.mark.parametrize("deleting", [False, True])
def test_plan_guard_uses_refreshed_prior_state_and_rejects_baseline_addresses(
    deleting: bool,
) -> None:
    plan = plan_for(actions=["delete"] if deleting else ["create"])
    plan["prior_state"] = {"values": plan["planned_values"]}
    plan["planned_values"] = {"root_module": {"resources": []}}
    if deleting:
        plan["resource_changes"][0]["change"]["before"] = plan["resource_changes"][0]["change"][
            "after"
        ]
        plan["resource_changes"][0]["change"]["after"] = None
    check_plan(plan, deleting=deleting)
    plan["resource_changes"][0]["address"] = "azapi_resource.foundry"
    with pytest.raises(ValueError, match="dedicated"):
        check_plan(plan, deleting=deleting)


@pytest.mark.parametrize("count", [0, 2])
def test_plan_guard_refuses_missing_or_ambiguous_refreshed_baseline(count: int) -> None:
    plan = plan_for()
    rows = plan["planned_values"]["root_module"]["resources"]
    plan["prior_state"] = {
        "values": {"root_module": {"resources": rows * count}},
    }
    plan["planned_values"] = {"root_module": {"resources": []}}
    with pytest.raises(ValueError, match="Missing or ambiguous baseline"):
        check_plan(plan)


def test_grant_cleanup_is_limited_to_the_new_agent_and_scopes() -> None:
    item = configuration()
    grant = {
        "agent": item.agent_name,
        "principal": "00000000-0000-4000-8000-000000000001",
        "role": "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd",
        "scope": ACCOUNT,
        "id": ACCOUNT + "/providers/Microsoft.Authorization/roleAssignments/"
        "00000000-0000-4000-8000-000000000002",
    }
    check_grants([grant], item.model_dump(mode="json"))
    with pytest.raises(ValueError, match="outside"):
        check_grants([{**grant, "agent": "baseline-agent"}], item.model_dump(mode="json"))


def test_publication_uses_new_project_and_journal_and_disable_survives_agent_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_copilot import Service

    item, baseline, runtime = configuration(), config(), settings()
    cfg = item.deployment_settings(baseline)
    directory = tmp_path / "isolated"
    client = SimpleNamespace(agents=Operations(), close=lambda: None)
    isolated.deploy(client, FakeModels, cfg, runtime, item, directory / "deployment.json")
    original_publication = tmp_path / "original-publication.json"
    original_publication.write_text("unchanged baseline publication")
    monkeypatch.setattr(isolated, "DIRECTORY", directory)
    monkeypatch.setattr(isolated, "HostedSettings", lambda: baseline)
    monkeypatch.setattr(isolated, "Settings", lambda: runtime)
    monkeypatch.setattr(isolated, "build_client", lambda _: (client, FakeModels))
    monkeypatch.setattr(isolated, "network_facts", lambda *_: {"synthetic": True})
    service = Service()
    constructor = httpx.Client
    monkeypatch.setattr(
        isolated.httpx,
        "Client",
        lambda **_: constructor(transport=httpx.MockTransport(service.handle)),
    )
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential",
        lambda: nullcontext(
            SimpleNamespace(get_token=lambda _: SimpleNamespace(token="synthetic-token"))
        ),
    )
    metadata = {
        "agentDisplayName": "ACS Toolbox Demo",
        "publishScope": "Shared",
        "appVersion": "1.0.0",
        "shortDescription": "Synthetic demo",
        "fullDescription": "Synthetic demo only.",
        "developerName": "Demo owner",
        "developerWebsiteUrl": "https://example.com",
        "privacyUrl": "https://example.com/privacy",
        "termsOfUseUrl": "https://example.com/terms",
    }
    for action in ("plan", "publish"):
        monkeypatch.setattr(isolated.sys, "stdin", io.StringIO("synthetic-token"))
        assert (
            isolated.main(
                [
                    action,
                    "--config",
                    item.model_dump_json(),
                    "--metadata",
                    json.dumps(metadata),
                ]
            )
            == 0
        )
    assert all(
        f"/projects/{item.project_name}/agents/{item.agent_name}" in str(call.url)
        for call in service.calls
    )
    assert len([call for call in service.calls if call.method == "POST"]) == 1
    publication = json.loads((directory / "publication.json").read_text())
    assert publication["phase"] == "published"
    assert isolated.publication_facts(cfg, item)["published_version"] == "1"
    service.endpoint["version_selector"] = {
        "version_selection_rules": [
            {"type": "FixedRatio", "agent_version": "99", "traffic_percentage": 100}
        ]
    }
    with pytest.raises(DriftError, match="publication endpoint"):
        isolated.publication_facts(cfg, item)
    service.endpoint = copy.deepcopy(publication["after"])
    assert original_publication.read_text() == "unchanged baseline publication"
    with pytest.raises(DeploymentError, match="Disable"):
        isolated.delete_versions(client, cfg, item, apply=True)
    assert not client.agents.deleted
    (directory / "deployment.json").unlink()
    monkeypatch.setattr(isolated.sys, "stdin", io.StringIO("synthetic-token"))
    assert isolated.main(["disable", "--config", item.model_dump_json()]) == 0
    assert json.loads((directory / "publication.json").read_text())["phase"] == "disabled"


@pytest.mark.parametrize("phase", ["published", "publish_requested", "planned", "disabled"])
def test_teardown_checks_publication_journal_even_when_versions_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    item = configuration()
    cfg = item.deployment_settings(config())
    monkeypatch.setattr(isolated, "DIRECTORY", tmp_path)
    (tmp_path / "publication.json").write_text(
        json.dumps(
            {
                "endpoint": cfg.endpoint,
                "agent_name": item.agent_name,
                "phase": phase,
            }
        )
    )
    client = SimpleNamespace(agents=Operations())
    if phase in {"planned", "disabled"}:
        isolated.delete_versions(client, cfg, item, apply=True)
    else:
        with pytest.raises(DeploymentError, match="Disable"):
            isolated.delete_versions(client, cfg, item, apply=True)
    assert not client.agents.deleted


@pytest.mark.parametrize("failure", [None, "host", "policy", "telemetry"])
def test_readback_requires_ready_host_exact_policy_and_existing_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
) -> None:
    from urllib.parse import urlparse

    item, baseline, runtime = configuration(), config(), settings()
    telemetry = next(
        part.split("=", 1)[1]
        for part in baseline.application_insights_connection_string.get_secret_value().split(";")
        if part.startswith("IngestionEndpoint=")
    )
    hosts = [item.toolbox_endpoint.host, runtime.test_receiver_host, urlparse(telemetry).hostname]

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/capabilityHosts"):
            body = {
                "value": [
                    {
                        "properties": {
                            "provisioningState": "Failed" if failure == "host" else "Succeeded",
                            "capabilityHostKind": "Agents",
                        }
                    }
                ]
            }
        elif "/connections/" in path:
            target = "/synthetic/existing-insights"
            if path.startswith(item.project_id + "/") and failure == "telemetry":
                target = "/synthetic/unapproved-insights"
            body = {
                "properties": {
                    "category": "AppInsights",
                    "authType": "ApiKey",
                    "target": target,
                    "metadata": {"ResourceId": target},
                    "isSharedToAll": False,
                }
            }
        else:
            body = {
                "properties": {
                    "basePolicyName": "Microsoft.Default",
                    "mode": "Blocking",
                    "contentFilters": [],
                    "egressPolicy": {
                        "mode": "Enforced",
                        "defaultAction": "Deny",
                        "rules": [
                            {
                                "ruleType": "Fqdn",
                                "match": {"host": host},
                                "action": {"actionType": "Allow"},
                            }
                            for host in hosts
                        ],
                    },
                }
            }
            if path == item.rai_policy_id and failure == "policy":
                body["properties"]["egressPolicy"]["rules"][0]["match"]["host"] = (
                    "unexpected.example"
                )
        return httpx.Response(200, json=body)

    constructor = httpx.Client
    monkeypatch.setattr(
        isolated.httpx, "Client", lambda **_: constructor(transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(
        "azure.identity.DefaultAzureCredential",
        lambda: nullcontext(
            SimpleNamespace(get_token=lambda _: SimpleNamespace(token="synthetic"))
        ),
    )
    if failure is None:
        assert isolated.network_facts(baseline, runtime, item)["hosts"] == sorted(hosts)
    else:
        with pytest.raises((DeploymentError, DriftError)):
            isolated.network_facts(baseline, runtime, item)
