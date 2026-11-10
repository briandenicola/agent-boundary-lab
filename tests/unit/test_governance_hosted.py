from __future__ import annotations

import copy
import io
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import verify_governance
from scripts.governance_manifest import check_plan, check_policy_ownership, render
from scripts.verify_demo import HostedEvidence, RunKind, Status
from scripts.verify_governance import judge_run, normalized_events

from containment_demo.deploy import DriftError
from containment_demo.governance import hosted
from containment_demo.invoke import TOOL_NAMES, InvocationResult, ToolOutcome
from containment_demo.settings import Settings
from tests.unit.test_deploy import ARM_PREFIX, IMAGE, FakeModels, make_cfg

ROOT = Path(__file__).resolve().parents[2]


def config() -> hosted.HostedSettings:
    return hosted.HostedSettings(
        **make_cfg().model_dump(),
        governance_all_policy_id=f"{ARM_PREFIX}/governance-all",
        governance_network_policy_id=f"{ARM_PREFIX}/governance-network",
        governance_audit_policy_id=f"{ARM_PREFIX}/governance-audit",
        governance_policies_directory=ROOT / "policies/acs",
        application_insights_connection_string=(
            "InstrumentationKey=synthetic;IngestionEndpoint=https://existing.monitor.example/"
        ),
    )


def settings() -> Settings:
    return Settings(
        policy_api_url="https://policy.example.com",
        test_receiver_url="https://receiver.example.com",
        diagnostics_token="synthetic-diagnostic-token",
    )


class Operations:
    def __init__(self) -> None:
        self.versions: dict[str, list[Any]] = {}
        self.created: list[str] = []
        self.deleted: list[tuple[str, str]] = []

    def list_versions(self, name: str) -> list[Any]:
        return self.versions.get(name, [])

    def get_version(self, name: str, version: str) -> Any:
        return next(v for v in self.versions[name] if v.version == version)

    def create_version(self, name: str, **kwargs: Any) -> Any:
        self.created.append(name)
        version = SimpleNamespace(
            version=str(len(self.versions.get(name, [])) + 1),
            status="active",
            definition=kwargs["definition"],
            metadata=kwargs["metadata"],
        )
        self.versions.setdefault(name, []).append(version)
        return version

    def delete_version(self, name: str, version: str, *, force: bool) -> None:
        assert force is False
        self.deleted.append((name, version))
        self.get_version(name, version).status = "deleted"


def test_readback_reuse_includes_governance_configuration() -> None:
    cfg, runtime = config(), settings()
    client = SimpleNamespace(agents=Operations())
    first = hosted.deploy_scenarios(client, FakeModels, cfg, runtime)
    assert len(first["agents"]) == 7
    assert {a["image"] for a in first["agents"]} == {IMAGE}
    hosted.deploy_scenarios(client, FakeModels, cfg, runtime)
    assert len(client.agents.created) == 7
    audit = hosted.SCENARIOS[0]
    name = hosted.spec_for(cfg, audit).agent_name
    client.agents.versions[name][0].definition.environment_variables["DEMO_GOVERNANCE_MODE"] = (
        "disabled"
    )
    hosted.deploy_scenarios(client, FakeModels, cfg, runtime)
    assert len(client.agents.created) == 8
    assert client.agents.created[-1] == name


def test_scenario_definitions_leave_telemetry_environment_to_foundry() -> None:
    cfg, runtime = config(), settings()
    for scenario in hosted.SCENARIOS:
        definition = hosted.definition_for(FakeModels, cfg, runtime, scenario)
        env = definition.environment_variables
        assert "APPLICATIONINSIGHTS_CONNECTION_STRING" not in env
        assert not any(name.startswith(("FOUNDRY_", "AGENT_")) for name in env)
        assert cfg.application_insights_connection_string.get_secret_value() not in env.values()


def test_status_recovers_live_versions_after_helper_report_is_lost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg, runtime = config(), settings()
    operations = Operations()
    client = SimpleNamespace(agents=operations, close=lambda: None)
    expected = hosted.deploy_scenarios(client, FakeModels, cfg, runtime)
    created = list(operations.created)
    report = tmp_path / "deployment.json"
    monkeypatch.setattr(hosted, "STATE_DIRECTORY", tmp_path)
    monkeypatch.setattr(hosted, "HostedSettings", lambda: cfg)
    monkeypatch.setattr(hosted, "Settings", lambda: runtime)
    monkeypatch.setattr(hosted, "build_client", lambda _: (client, FakeModels))
    monkeypatch.setattr(hosted, "policy_facts", lambda *_: {"synthetic": True})
    assert hosted.main(["status", "--report", str(report)]) == 0
    actual = json.loads(capsys.readouterr().out)
    assert actual["agents"] == expected["agents"]
    assert actual["network"] == {"synthetic": True}
    assert operations.created == created
    assert not operations.deleted
    assert not report.exists()


@pytest.mark.parametrize("failure", ["missing", "ambiguous", "drift", "unowned"])
def test_status_discovery_rejects_unverifiable_versions(failure: str) -> None:
    cfg, runtime = config(), settings()
    operations = Operations()
    client = SimpleNamespace(agents=operations)
    hosted.deploy_scenarios(client, FakeModels, cfg, runtime)
    name = hosted.spec_for(cfg, hosted.SCENARIOS[0]).agent_name
    if failure == "missing":
        operations.versions[name] = []
    elif failure == "ambiguous":
        duplicate = copy.deepcopy(operations.versions[name][0])
        duplicate.version = "2"
        operations.versions[name].append(duplicate)
    elif failure == "drift":
        operations.versions[name][0].definition.environment_variables["DEMO_GOVERNANCE_MODE"] = (
            "disabled"
        )
    else:
        operations.versions[name][0].metadata = {}
    with pytest.raises(DriftError, match="exactly one ready version"):
        hosted.discover_scenarios(client, FakeModels, cfg, runtime)
    assert len(operations.created) == 7
    assert not operations.deleted


def test_matrix_records_real_invocation_contract_without_user_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg, runtime = config(), settings()
    operations = Operations()
    client = SimpleNamespace(
        agents=operations,
        get_openai_client=lambda **_: nullcontext(object()),
        close=lambda: None,
    )
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps(hosted.deploy_scenarios(client, FakeModels, cfg, runtime)))
    monkeypatch.setattr(verify_governance, "HostedSettings", lambda: cfg)
    monkeypatch.setattr(verify_governance, "Settings", lambda: runtime)
    monkeypatch.setattr(verify_governance, "build_client", lambda _: (client, FakeModels))
    monkeypatch.setattr(verify_governance, "policy_facts", lambda *_: {"synthetic": True})
    monkeypatch.setattr(
        verify_governance.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "foundry_access_token": "synthetic-foundry-token",
                    "policy_access_token": "synthetic-policy-token",
                }
            )
        ),
    )

    def invoke(**kwargs: Any) -> InvocationResult:
        return InvocationResult(
            demo_run_id=kwargs["demo_run_id"],
            agent_name=kwargs["agent_name"],
            endpoint=kwargs["endpoint"],
            started_at="2026-11-09T16:00:00+00:00",
            ended_at="2026-11-09T16:00:05+00:00",
            transport_ok=True,
            transport_error_category=None,
            transport_detail=None,
            response_id="synthetic-response",
            response_status="completed",
            response_text_sha256=None,
            response_text_chars=None,
            outcomes={
                name: ToolOutcome(
                    tool_name=name,
                    attempted=True,
                    succeeded=True,
                    error_category=None,
                    http_status=200,
                    destination_host="example.com",
                    evidence_source="tool_result_record",
                    detail="synthetic",
                    tool_run_id=kwargs["demo_run_id"],
                    user_object_id="synthetic-user-do-not-retain",
                )
                for name in TOOL_NAMES
            },
        )

    monkeypatch.setattr(verify_governance, "invoke_agent", invoke)
    journal = tmp_path / "runs.json"
    verify_governance.run_matrix(journal, deployment)
    runs = json.loads(journal.read_text())["runs"]
    assert len(runs) == 14
    assert {run["path_kind"] for run in runs} == {"deterministic", "model_selected"}
    assert all(set(run["invocation"]["outcomes"]) == set(TOOL_NAMES) for run in runs)
    assert all(run["configuration_readback_ok"] for run in runs)
    assert "synthetic-user-do-not-retain" not in journal.read_text()
    assert "synthetic-foundry-token" not in journal.read_text()
    assert "synthetic-policy-token" not in journal.read_text()


def test_unowned_version_prevents_all_writes_and_deletion() -> None:
    cfg = config()
    client = SimpleNamespace(agents=Operations())
    name = hosted.spec_for(cfg, hosted.SCENARIOS[-1]).agent_name
    client.agents.versions[name] = [SimpleNamespace(version="1", metadata={})]
    with pytest.raises(DriftError, match="not owned"):
        hosted.deploy_scenarios(client, FakeModels, cfg, settings())
    assert not client.agents.created
    with pytest.raises(DriftError, match="non-track"):
        hosted.delete_scenarios(client, cfg)
    assert not client.agents.deleted


def test_teardown_waits_for_owned_versions_and_never_targets_baseline() -> None:
    cfg = config()
    client = SimpleNamespace(agents=Operations())
    hosted.deploy_scenarios(client, FakeModels, cfg, settings())
    hosted.delete_scenarios(client, cfg)
    assert len(client.agents.deleted) == 7
    assert all("-gov-" in name for name, _ in client.agents.deleted)


def test_baseline_policy_attachment_is_rejected() -> None:
    cfg = config().model_copy(update={"governance_all_policy_id": config().rai_policy_audit_id})
    with pytest.raises(DriftError, match="baseline policies"):
        hosted.spec_for(cfg, hosted.SCENARIOS[0])


def test_foreign_policy_and_plan_changes_are_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        check_policy_ownership(["containment-demo-governance-all"], [])
    plan = {
        "format_version": "1.2",
        "planned_values": {"root_module": {}},
        "resource_changes": [
            {
                "mode": "managed",
                "address": 'azapi_resource.policy["all"]',
                "change": {"actions": ["create"]},
            }
        ],
    }
    check_plan(plan)
    plan["resource_changes"][0]["address"] = "azapi_resource.foundry"
    with pytest.raises(ValueError, match="outside"):
        check_plan(plan)


def test_helper_uses_existing_identity_and_secret_references() -> None:
    cfg = config()
    cloud = {
        "foundry_account_name": cfg.foundry_account_name,
        "project_name": cfg.foundry_project_name,
        "agent_name_audit": cfg.agent_name_audit,
        "agent_name_enforced": cfg.agent_name_enforced,
        "rai_policy_audit_id": cfg.rai_policy_audit_id,
        "rai_policy_enforced_id": cfg.rai_policy_enforced_id,
        "policy_api_url": "https://policy.example.com",
        "test_receiver_url": "https://receiver.example.com",
        "model_deployment_name": "synthetic-model",
        "foundry_endpoint": "https://foundry.example.com",
        "diagnostics_token": "synthetic-diagnostics-token",
        "application_insights_connection_string": (
            cfg.application_insights_connection_string.get_secret_value()
        ),
        "log_analytics_workspace_id": "workspace",
        "policy_api_app_name": "policy-api",
        "test_receiver_app_name": "test-receiver",
        "kubernetes_namespace": "demo-lab",
        "agent_deployer_service_account": "agent-deployer",
    }
    manifest = render(
        cloud,
        {
            "all": cfg.governance_all_policy_id,
            "network": cfg.governance_network_policy_id,
            "audit": cfg.governance_audit_policy_id,
        },
        IMAGE,
    )
    secret, deployment = manifest["items"]
    pod = deployment["spec"]["template"]
    assert pod["spec"]["serviceAccountName"] == "agent-deployer"
    env = {item["name"]: item.get("value") for item in pod["spec"]["containers"][0]["env"]}
    assert env["DEMO_DEPLOY_REQUEST_TIMEOUT_SECONDS"] == "60"
    assert env["DEMO_DEPLOY_RETRY_TOTAL"] == "0"
    assert "synthetic-diagnostics-token" not in str(deployment)
    assert secret["stringData"]["DEMO_DIAGNOSTICS_TOKEN"] == "synthetic-diagnostics-token"
    assert not pod["spec"].get("initContainers")
    assert deployment["metadata"]["name"] != "agent-harness"


def fixture(name: str) -> tuple[dict[str, Any], HostedEvidence, list[dict[str, Any]]]:
    cfg = config()
    scenario = next(s for s in hosted.SCENARIOS if s.name == name)
    start = datetime(2026, 11, 6, 16, 0, tzinfo=UTC)
    run_id = "gov-unit"
    agent = hosted.spec_for(cfg, scenario).agent_name
    facts = {
        "agent_name": agent,
        "version": "1",
        "image": IMAGE,
        "governance_mode": scenario.governance_mode.value,
        "policy_id": "unavailable" if scenario.broken_evaluator else "test/tool_policy",
        "policy_version": "unavailable" if scenario.broken_evaluator else "sha256:unit",
    }
    outcomes, events, decisions, receipts = {}, [], [], []
    for tool, path in (
        ("get_servicing_policy", "/policy"),
        ("send_to_external_processor", "/ingest"),
    ):
        blocked = scenario.broken_evaluator or (name == "governance-denial" and path == "/ingest")
        common = {"demo.run_id": run_id, "demo.agent_name": agent, "demo.agent_version": "1"}
        outcomes[tool] = {
            "tool_run_id": run_id,
            "error_category": "governance_error"
            if scenario.broken_evaluator
            else ("governance_denied" if blocked else "none"),
        }
        if scenario.governance_mode.value != "disabled":
            verdict = (
                "error"
                if scenario.broken_evaluator
                else (
                    "deny"
                    if scenario.manifest == "governance-deny.yaml" and path == "/ingest"
                    else "allow"
                )
            )
            events.append(
                {
                    **common,
                    "kind": "governance",
                    **{
                        f"demo.governance.{k}": v
                        for k, v in {
                            "tool_name": tool,
                            "session_id": "session",
                            "invocation_id": "invocation",
                            "tool_call_id": f"call-{path}",
                            "governance_mode": facts["governance_mode"],
                            "policy_id": facts["policy_id"],
                            "policy_version": facts["policy_version"],
                            "acs_verdict": verdict,
                            "enforcement_action": "audit_continue"
                            if name == "audit-control"
                            else "blocked"
                            if blocked
                            else "continue",
                            "reason_code": "test",
                            "timestamp": (start + timedelta(seconds=5)).isoformat(),
                            "trace_id": "a" * 32,
                        }.items()
                    },
                }
            )
        if blocked:
            continue
        events.append({**common, "kind": "tool", "demo.tool_name": tool})
        deny_network = scenario.network == "network" and path == "/ingest"
        audit = scenario.network == "audit"
        decisions.append(
            {
                "TimeGenerated": start + timedelta(seconds=5),
                "Properties": {
                    "path": f"{path}/{run_id}",
                    "decisionResultCode": "Deny"
                    if deny_network
                    else ("AuditWouldDeny" if audit and path == "/ingest" else "Allow"),
                    "enforcement": "Audit" if audit else "Enforced",
                },
            }
        )
        if not deny_network:
            receipts.append(
                {
                    "demo_run_id": run_id,
                    "service": "policy-api" if path == "/policy" else "test-receiver",
                    "path": f"{path}/{run_id}",
                    "outcome": "served",
                    "identity_verified": path == "/policy",
                }
            )
    run = {
        "scenario": name,
        "path_kind": "deterministic",
        "configuration": facts,
        "configuration_readback_ok": True,
        "invocation": {
            "demo_run_id": run_id,
            "transport_ok": True,
            "response_status": "completed",
            "ended_at": (start + timedelta(seconds=10)).isoformat(),
            "outcomes": outcomes,
        },
    }
    evidence = HostedEvidence(
        run_id,
        start,
        start + timedelta(seconds=300),
        decisions,
        receipts,
        [],
        True,
        RunKind.HOSTED_AGENT,
        "synthetic fixture",
    )
    return run, evidence, events


@pytest.mark.parametrize("name", [s.name for s in hosted.SCENARIOS])
def test_complete_hosted_scenario_evidence(name: str) -> None:
    run, evidence, events = fixture(name)
    _, control, _ = fixture("success")
    control.run_id = "gov-control"
    for receipt in control.receipts:
        receipt["demo_run_id"] = control.run_id
    assert judge_run(run, evidence, events, control)[0] is Status.PASS


@pytest.mark.parametrize("mutation", ["missing-governance", "wrong-version", "wrong-hash"])
def test_missing_or_mismatched_governance_never_passes(mutation: str) -> None:
    run, evidence, events = fixture("governance-denial")
    if mutation == "missing-governance":
        events = [event for event in events if event["kind"] != "governance"]
    else:
        for event in events:
            event[
                "demo.agent_version"
                if mutation == "wrong-version"
                else "demo.governance.policy_version"
            ] = "wrong"
    assert judge_run(run, evidence, events)[0] is not Status.PASS


def test_receiver_arrival_contradicts_application_block() -> None:
    run, evidence, events = fixture("governance-denial")
    evidence.receipts.append({"demo_run_id": evidence.run_id, "service": "test-receiver"})
    assert judge_run(run, evidence, events)[0] is Status.FAIL


def test_http_failure_without_platform_deny_is_inconclusive() -> None:
    run, evidence, events = fixture("network-denial")
    evidence.decisions = [
        row for row in evidence.decisions if row["Properties"]["decisionResultCode"] != "Deny"
    ]
    run["invocation"]["outcomes"]["send_to_external_processor"]["http_status"] = 403
    assert judge_run(run, evidence, events)[0] is Status.INCONCLUSIVE


def test_receipt_wait_is_measured_after_completion_not_request_start() -> None:
    run, evidence, events = fixture("governance-denial")
    run["invocation"]["ended_at"] = (evidence.called_at + timedelta(seconds=120)).isoformat()
    evidence.queried_at = evidence.called_at + timedelta(seconds=200)
    assert judge_run(run, evidence, events)[0] is Status.INCONCLUSIVE


def test_authorization_rejection_is_not_a_positive_policy_control() -> None:
    run, evidence, events = fixture("governance-denial")
    evidence.receipts[0]["outcome"] = "denied"
    evidence.receipts[0]["identity_verified"] = False
    assert judge_run(run, evidence, events)[0] is Status.INCONCLUSIVE


def test_event_normalization_drops_payload_attributes() -> None:
    run, _, events = fixture("audit-control")
    props = copy.deepcopy(events[0])
    props.pop("kind")
    props["authorization"] = "synthetic-secret"
    props["gcp.vertex.agent.llm_request"] = "synthetic-payload"
    result = normalized_events([{"Name": "demo.governance_decision", "Properties": props}])
    assert len(result) == 1
    assert "synthetic-secret" not in str(result)
    assert "synthetic-payload" not in str(result)
    assert result[0]["demo.run_id"] == run["invocation"]["demo_run_id"]
