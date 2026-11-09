"""Invoke isolated Foundry scenarios and judge Azure evidence, never client errors alone."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.verify_demo import (
    MIN_ABSENCE_WAIT_SECONDS,
    HostedEvidence,
    RunKind,
    Status,
    _parse_time,
    _run_query,
    build_leg,
    classify_receipt_absence,
    judge_audit_unapproved_leg,
    judge_enforced_unapproved_leg,
    judge_permitted_leg,
    open_log_query,
    query_egress_decisions,
    query_receipts_for_run,
    query_unattributed_receipts,
)

from containment_demo.deploy import build_client, configure_logging
from containment_demo.governance.hosted import (
    SCENARIOS,
    STATE_DIRECTORY,
    HostedSettings,
    policy_facts,
    read_scenario,
)
from containment_demo.invoke import invoke_agent
from containment_demo.settings import Settings


def normalized_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        props = row.get("Properties") or {}
        if isinstance(props, str):
            try:
                props = json.loads(props)
            except ValueError:
                continue
        message = row.get("Message") or ""
        if "governance decision " in message:
            try:
                props = json.loads(message.split("governance decision ", 1)[1])
            except ValueError:
                continue
            kind = "governance"
        elif row.get("Name") == "demo.governance_decision":
            kind = "governance"
        elif message == "demo.tool_result" or row.get("Name") == "demo.tool_result":
            kind = "tool"
        else:
            continue
        if not isinstance(props, dict):
            continue
        # Keep our evidence fields only, never SDK request/response attributes.
        allowed = {
            "demo.run_id",
            "demo.agent_name",
            "demo.agent_version",
            "demo.tool_name",
            "demo.succeeded",
            "demo.error_category",
            "demo.http_status",
            "demo.user_token_forwarded",
        }
        allowed |= {
            f"demo.governance.{name}"
            for name in (
                "tool_name",
                "session_id",
                "invocation_id",
                "tool_call_id",
                "governance_mode",
                "policy_id",
                "policy_version",
                "acs_verdict",
                "enforcement_action",
                "reason_code",
                "evaluation_duration_ms",
                "timestamp",
                "trace_id",
            )
        }
        events.append({"kind": kind, **{k: v for k, v in props.items() if k in allowed}})
    return events


def judge_run(
    run: dict[str, Any],
    evidence: HostedEvidence,
    events: list[dict[str, Any]],
    control: HostedEvidence | None = None,
) -> tuple[Status, str]:
    scenario = next(s for s in SCENARIOS if s.name == run["scenario"])
    facts = run["configuration"]
    invocation = run["invocation"]
    if evidence.invoked_from is not RunKind.HOSTED_AGENT:
        return Status.INCONCLUSIVE, "Not a hosted observation"
    if evidence.run_id != invocation["demo_run_id"]:
        return Status.FAIL, "Run correlation mismatch"
    if not invocation["transport_ok"]:
        return Status.INCONCLUSIVE, "Foundry ingress failed; no egress attribution"
    if invocation.get("response_status") != "completed":
        return Status.INCONCLUSIVE, "Foundry response did not complete"
    if facts["governance_mode"] != scenario.governance_mode.value:
        return Status.FAIL, "Governance configuration mismatch"
    if not run.get("configuration_readback_ok"):
        return Status.INCONCLUSIVE, "Missing direct configuration readback"
    selected = [
        event
        for event in events
        if event.get("demo.run_id") == evidence.run_id
        and event.get("demo.agent_name") == facts["agent_name"]
        and str(event.get("demo.agent_version")) == facts["version"]
    ]
    policy = build_leg(evidence, "/policy")
    receiver = build_leg(evidence, "/ingest")
    checks: list[tuple[Status, str]] = []
    names = ("get_servicing_policy", "send_to_external_processor")
    for name in names:
        outcomes = invocation["outcomes"]
        outcome = outcomes[name]
        if outcome.get("tool_run_id") != evidence.run_id:
            return Status.INCONCLUSIVE, f"{name}: no structured result for this run"
        tool_events = [
            event
            for event in selected
            if event["kind"] == "tool" and event.get("demo.tool_name") == name
        ]
        decisions = [
            event
            for event in selected
            if event["kind"] == "governance" and event.get("demo.governance.tool_name") == name
        ]
        if scenario.governance_mode.value == "disabled" and decisions:
            return Status.FAIL, "Disabled baseline unexpectedly evaluated ACS"
        blocked = scenario.name == "evaluation-failure" or (
            scenario.name == "governance-denial" and name == names[1]
        )
        if scenario.governance_mode.value != "disabled":
            if not decisions:
                return Status.INCONCLUSIVE, f"{name}: governance evidence missing for this version"
            expected_verdict = (
                "error"
                if scenario.broken_evaluator
                else "deny"
                if scenario.manifest == "governance-deny.yaml" and name == names[1]
                else "allow"
            )
            expected_action = (
                "audit_continue"
                if scenario.governance_mode.value == "audit"
                else "blocked"
                if blocked
                else "continue"
            )
            for decision in decisions:
                if not all(
                    decision.get(f"demo.governance.{key}")
                    for key in (
                        "session_id",
                        "invocation_id",
                        "tool_call_id",
                        "policy_id",
                        "policy_version",
                        "reason_code",
                        "timestamp",
                        "trace_id",
                    )
                ):
                    return Status.INCONCLUSIVE, f"{name}: governance correlation fields missing"
                timestamp = _parse_time(decision.get("demo.governance.timestamp"))
                if (
                    timestamp is None
                    or evidence.called_at is None
                    or evidence.queried_at is None
                    or not evidence.called_at <= timestamp <= evidence.queried_at
                ):
                    return Status.INCONCLUSIVE, f"{name}: governance timestamp outside call window"
                if (
                    decision.get("demo.governance.policy_id") != facts["policy_id"]
                    or decision.get("demo.governance.policy_version") != facts["policy_version"]
                ):
                    return Status.FAIL, f"{name}: evaluated policy differs from image artifacts"
                if (
                    decision.get("demo.governance.acs_verdict") != expected_verdict
                    or decision.get("demo.governance.enforcement_action") != expected_action
                    or decision.get("demo.governance.governance_mode") != facts["governance_mode"]
                ):
                    return Status.FAIL, f"{name}: governance decision contradicts the scenario"
        if blocked:
            if outcome.get("error_category") != (
                "governance_error" if scenario.broken_evaluator else "governance_denied"
            ):
                return Status.FAIL, f"{name}: governance rejection result missing"
            leg = policy if name == names[0] else receiver
            if tool_events or leg.decisions or leg.receipts:
                return Status.FAIL, f"{name}: execution evidence exists despite ACS blocking"
            if evidence.called_at is None or evidence.queried_at is None:
                return Status.INCONCLUSIVE, "Missing receipt query/call timestamps"
            ended_at = _parse_time(invocation.get("ended_at"))
            if ended_at is None:
                return Status.INCONCLUSIVE, "Missing invocation completion timestamp"
            if (
                evidence.queried_at - max(evidence.called_at, ended_at)
            ).total_seconds() < MIN_ABSENCE_WAIT_SECONDS:
                return Status.INCONCLUSIVE, "Receipt ingestion wait not complete"
            if control is None or control.run_id == evidence.run_id:
                return Status.INCONCLUSIVE, "Missing separate receipt positive control"
            positive = build_leg(control, "/policy" if name == names[0] else "/ingest").receipts
            if not control.receipts_query_ok:
                positive = []
            status, _, detail = classify_receipt_absence(
                query_available=evidence.receipts_query_ok
                and evidence.unattributed_receipts is not None,
                rows_for_run=leg.receipts,
                unattributed_rows=evidence.unattributed_receipts or [],
                any_rows_in_window=bool(evidence.receipts) or bool(positive),
                retrievability_proven_in_window=bool(positive),
            )
            checks.append((status, detail))
        else:
            if not tool_events:
                return Status.INCONCLUSIVE, f"{name}: tool execution trace missing for this version"
            if name == names[0]:
                if not any(
                    r.get("outcome") == "served" and r.get("identity_verified") is True
                    for r in policy.receipts
                ):
                    return Status.INCONCLUSIVE, "Authorized policy receipt positive control missing"
                checks.append(
                    judge_permitted_leg(
                        policy, "Audit" if scenario.network == "audit" else "Enforced"
                    )
                )
            elif scenario.network == "all":
                checks.append(judge_permitted_leg(receiver, "Enforced"))
            elif scenario.network == "audit":
                checks.append(judge_audit_unapproved_leg(receiver))
            else:
                status, detail, _ = judge_enforced_unapproved_leg(receiver, evidence, policy)
                checks.append((status, detail))
    status = (
        Status.FAIL
        if any(s is Status.FAIL for s, _ in checks)
        else Status.INCONCLUSIVE
        if any(s is not Status.PASS for s, _ in checks)
        else Status.PASS
    )
    return status, "; ".join(detail for _, detail in checks)


def collect(run: dict[str, Any]) -> tuple[HostedEvidence, list[dict[str, Any]], str]:
    log = open_log_query(os.environ["DEMO_GOVERNANCE_WORKSPACE_ID"])
    called_at = _parse_time(run["invocation"]["started_at"])
    if called_at is None:
        raise ValueError("Invocation has no timezone-aware start time")
    now = datetime.now(UTC)
    window = (called_at - timedelta(seconds=30), now)
    run_id = run["invocation"]["demo_run_id"]
    Settings.validate_run_id(run_id)
    apps = [os.environ["DEMO_POLICY_API_APP_NAME"], os.environ["DEMO_TEST_RECEIVER_APP_NAME"]]
    decisions, d_reason = query_egress_decisions(log, run_id, window)
    receipts, r_reason = query_receipts_for_run(log, apps, run_id, window)
    unattributed, u_reason = query_unattributed_receipts(log, apps, window)
    kql = f"""
union AppTraces, AppEvents, AppDependencies
| where tostring(Properties["demo.run_id"]) == "{run_id}"
    or tostring(column_ifexists("Message", "")) has "{run_id}"
| project TimeGenerated, Properties,
    Message = tostring(column_ifexists("Message", "")),
    Name = tostring(column_ifexists("Name", ""))
"""
    rows, a_reason = _run_query(log, kql, window)
    evidence = HostedEvidence(
        run_id,
        called_at,
        now,
        decisions,
        receipts,
        unattributed if u_reason == "ok" else None,
        r_reason == "ok" and u_reason == "ok",
        RunKind.HOSTED_AGENT,
        f"live Azure queries: platform={d_reason}; receipts={r_reason}; "
        f"unattributed={u_reason}; application={a_reason}",
    )
    return evidence, normalized_events(rows), evidence.source


def write_json(path: Path, value: Any) -> None:
    def encode(item: Any) -> str:
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"Cannot serialize {type(item).__name__}")

    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(json.dumps(value, indent=2, default=encode) + "\n")
            handle.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def run_matrix(journal: Path, deployment: Path) -> None:
    write_json(journal, {"run_kind": "hosted_agent", "runs": []})
    tokens = json.load(sys.stdin)
    if set(tokens) != {"foundry_access_token", "policy_access_token"} or any(
        not isinstance(value, str) or not value.strip() for value in tokens.values()
    ):
        raise ValueError("Provide both tokens from the existing authorized synthetic-user flow")
    cfg = HostedSettings()  # type: ignore[call-arg]
    settings = Settings()  # type: ignore[call-arg]
    report = json.loads(deployment.read_text())
    client, models = build_client(cfg)
    runs: list[dict[str, Any]] = []
    try:
        for scenario in SCENARIOS:
            version = next(r["version"] for r in report["agents"] if r["scenario"] == scenario.name)
            for path_kind in ("deterministic", "model_selected"):
                facts = read_scenario(client, models, cfg, settings, scenario, version)
                network = policy_facts(cfg, settings)
                latest = max(
                    int(str(v.version)) for v in client.agents.list_versions(facts["agent_name"])
                )
                if str(latest) != version:
                    raise ValueError("Named endpoint has a newer version; rerun governance:status")
                run_id = f"gov-{uuid.uuid4()}"
                with client.get_openai_client(
                    agent_name=facts["agent_name"],
                    api_key=tokens["foundry_access_token"],
                    timeout=120,
                    max_retries=0,
                ) as openai:
                    result = invoke_agent(
                        endpoint=cfg.endpoint,
                        agent_name=facts["agent_name"],
                        demo_run_id=run_id,
                        client=openai,
                        user_token=tokens["policy_access_token"],
                        diagnostics_token=(
                            settings.diagnostics_token.get_secret_value()
                            if path_kind == "deterministic" and settings.diagnostics_token
                            else None
                        ),
                    ).as_dict()
                result["outcomes"] = {
                    outcome["tool_name"]: outcome for outcome in result.pop("results")
                }
                for outcome in result["outcomes"].values():
                    outcome.pop("user_object_id", None)
                runs.append(
                    {
                        "scenario": scenario.name,
                        "path_kind": path_kind,
                        "configuration": facts,
                        "configuration_readback_ok": False,
                        "network_readback": network,
                        "invocation": result,
                    }
                )
                write_json(journal, {"run_kind": "hosted_agent", "runs": runs})
                read_scenario(client, models, cfg, settings, scenario, version)
                if policy_facts(cfg, settings) != network:
                    raise ValueError("Azure policy/network configuration changed during invocation")
                runs[-1]["configuration_readback_ok"] = True
                write_json(journal, {"run_kind": "hosted_agent", "runs": runs})
                print(f"{scenario.name}/{path_kind}: recorded {run_id}", flush=True)
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "verify"])
    parser.add_argument("--journal", default=str(STATE_DIRECTORY / "runs.json"))
    parser.add_argument("--deployment", default=str(STATE_DIRECTORY / "deployment.json"))
    parser.add_argument("--out", default=str(STATE_DIRECTORY / "evidence.json"))
    args = parser.parse_args()
    configure_logging()
    if args.action == "run":
        Path(args.journal).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        run_matrix(Path(args.journal), Path(args.deployment))
        return 0
    journal = json.loads(Path(args.journal).read_text())
    results = []
    controls: dict[str, HostedEvidence] = {}
    for run in journal["runs"]:
        evidence, events, source = collect(run)
        control = controls.get(run["path_kind"])
        status, detail = judge_run(run, evidence, events, control)
        if run["scenario"] in {"audit-control", "success"} and status is Status.PASS:
            controls[run["path_kind"]] = evidence
        results.append(
            {
                "scenario": run["scenario"],
                "path_kind": run["path_kind"],
                "run_id": evidence.run_id,
                "called_at": evidence.called_at,
                "queried_at": evidence.queried_at,
                "control_run_id": control.run_id if control else None,
                "status": status.value,
                "detail": detail,
                "evidence_source": source,
                "configuration": run["configuration"],
                "events": events,
                "platform_decisions": evidence.decisions,
                "receipts": evidence.receipts,
                "unattributed_receipts": evidence.unattributed_receipts,
            }
        )
        print(f"{run['scenario']}/{run['path_kind']}: {status.value} — {detail}", flush=True)
    expected = {(s.name, p) for s in SCENARIOS for p in ("deterministic", "model_selected")}
    complete = (
        len(results) == len(expected)
        and {(r["scenario"], r["path_kind"]) for r in results} == expected
        and len({r["configuration"]["image"] for r in results}) == 1
    )
    statuses = {r["status"] for r in results}
    overall = (
        "fail"
        if "fail" in statuses
        else ("pass" if complete and statuses == {"pass"} else "inconclusive")
    )
    Path(args.out).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_json(Path(args.out), {"run_kind": "hosted_agent", "status": overall, "results": results})
    return {"pass": 0, "fail": 1, "inconclusive": 2}[overall]


if __name__ == "__main__":
    raise SystemExit(main())
