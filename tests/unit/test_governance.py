"""Real ACS/Rego evaluation and both execution boundaries, without Azure or a live model."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.genai import types
from opentelemetry import trace
from opentelemetry.trace import SpanContext, TraceFlags
from pydantic import ValidationError
from starlette.requests import Request

from containment_demo import agent, diagnostics, telemetry
from containment_demo.governance import runtime
from containment_demo.settings import GovernanceMode, Settings

ROOT = Path(__file__).resolve().parents[2]
OPA = Path(os.environ.get("GOVERNANCE_TEST_OPA", ROOT / ".task/governance/bin/opa"))
TOKEN = "synthetic-diagnostic-token"


def make_settings(
    mode: GovernanceMode = GovernanceMode.ENFORCED, manifest: str = "governance-deny"
) -> Settings:
    return Settings(
        _env_file=None,
        policy_api_url="https://policy.example.com/",  # type: ignore[arg-type]
        test_receiver_url="https://receiver.example.net/",  # type: ignore[arg-type]
        diagnostics_token=TOKEN,  # type: ignore[arg-type]
        demo_run_id="governance-unit",
        governance_mode=mode,
        governance_manifest=ROOT / f"policies/acs/{manifest}.yaml",
        governance_opa_path=OPA,
    )


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def destinations() -> Any:
    with respx.mock(assert_all_called=False) as mock:
        policy = mock.get(
            "https://policy.example.com/policy/governance-unit",
            params={"demo_run_id": "governance-unit"},
        ).mock(return_value=httpx.Response(200, json={"tier": "synthetic"}))
        receiver = mock.post(
            "https://receiver.example.net/ingest/governance-unit",
            params={"demo_run_id": "governance-unit"},
        ).mock(return_value=httpx.Response(202, json={"received": True}))
        yield policy, receiver


async def diagnostic_results(settings: Settings, *, authorized: bool = True) -> dict[str, Any]:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": diagnostics.DIAGNOSTICS_PATH,
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {TOKEN if authorized else 'wrong'}".encode())],
        }
    )
    response = await diagnostics.diagnostics_handler(request, settings)
    return json.loads(bytes(response.body))


async def evaluate(governance: runtime.Governance, name: str) -> dict[str, Any] | None:
    return await governance.before_tool(
        name,
        {},
        session_id="session-unit",
        invocation_id="invocation-unit",
        tool_call_id="call-unit",
    )


async def test_enforced_deny_never_executes(settings: Settings, destinations: Any) -> None:
    body = await diagnostic_results(settings)
    policy, receiver = destinations
    assert policy.call_count == 1
    assert receiver.call_count == 0
    assert body["results"][0]["succeeded"] is True
    assert body["results"][1]["error_category"] == "governance_denied"
    assert body["results"][1]["governance"]["enforcement_action"] == "blocked"
    assert body["determination"] == "inconclusive-without-platform-evidence"


async def test_network_comparison_policy_allows_both_tools(destinations: Any) -> None:
    body = await diagnostic_results(make_settings(manifest="network-allow"))
    assert all(result["succeeded"] for result in body["results"])
    assert all(route.call_count == 1 for route in destinations)


async def test_audit_records_deny_but_executes(destinations: Any) -> None:
    body = await diagnostic_results(make_settings(GovernanceMode.AUDIT))
    assert all(result["succeeded"] for result in body["results"])
    assert all(route.call_count == 1 for route in destinations)


async def test_disabled_needs_no_sdk_manifest_or_opa(
    destinations: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = make_settings(GovernanceMode.DISABLED)
    settings.governance_manifest = None
    settings.governance_opa_path = Path("/missing/opa")

    def forbidden_load(_: Settings) -> Any:
        raise AssertionError("Disabled must not load ACS")

    monkeypatch.setattr(runtime, "_load_control", forbidden_load)
    body = await diagnostic_results(settings)
    assert all(result["succeeded"] for result in body["results"])
    assert all(route.call_count == 1 for route in destinations)


@pytest.mark.parametrize("missing", ["manifest", "opa"])
async def test_missing_runtime_artifacts_fail_closed(
    settings: Settings, destinations: Any, missing: str
) -> None:
    if missing == "manifest":
        settings.governance_manifest = ROOT / "missing-manifest.yaml"
    else:
        settings.governance_opa_path = ROOT / "missing-opa"
    body = await diagnostic_results(settings)
    assert all(result["error_category"] == "governance_error" for result in body["results"])
    assert not any(route.called for route in destinations)


async def test_evaluator_exception_fail_closed(
    settings: Settings, destinations: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_load(_: Settings) -> Any:
        raise RuntimeError("synthetic-secret-do-not-log")

    monkeypatch.setattr(runtime, "_load_control", broken_load)
    body = await diagnostic_results(settings)
    assert all(result["error_category"] == "governance_error" for result in body["results"])
    assert not any(route.called for route in destinations)
    assert "synthetic-secret" not in json.dumps(body)


async def test_audit_evaluation_failure_is_explicit_and_non_enforcing(
    destinations: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken_load(_: Settings) -> Any:
        raise RuntimeError("synthetic-secret-do-not-log")

    monkeypatch.setattr(runtime, "_load_control", broken_load)
    with caplog.at_level("INFO"):
        body = await diagnostic_results(make_settings(GovernanceMode.AUDIT))
    assert all(result["succeeded"] for result in body["results"])
    assert all(route.called for route in destinations)
    assert '"demo.governance.acs_verdict": "error"' in caplog.text
    assert '"demo.governance.enforcement_action": "audit_continue"' in caplog.text
    assert "synthetic-secret" not in caplog.text


async def test_authentication_precedes_governance(
    settings: Settings, destinations: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_load(_: Settings) -> Any:
        raise AssertionError("Unauthorized requests must not initialize ACS")

    monkeypatch.setattr(runtime, "_load_control", forbidden_load)
    assert await diagnostic_results(settings, authorized=False) == {"error": "unauthorized"}
    assert not any(route.called for route in destinations)


async def test_unknown_operation_and_unexpected_arguments_are_blocked(settings: Settings) -> None:
    governance = runtime.Governance(settings)
    assert await evaluate(governance, "unknown_operation") is not None
    rejection = await governance.before_tool(
        "get_servicing_policy",
        {"user_token": "synthetic-secret"},
        session_id="session-unit",
        invocation_id="invocation-unit",
    )
    assert rejection is not None
    assert rejection["error_category"] == "governance_error"
    assert "synthetic-secret" not in json.dumps(rejection)


def raw_result(
    decision: str = "allow",
    *,
    reason: str = "synthetic_reason",
    transformed: object = None,
    applied: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        verdict=SimpleNamespace(
            decision=SimpleNamespace(value=decision),
            reason=reason,
            transform=SimpleNamespace() if decision == "transform" else None,
        ),
        transformed_policy_target=transformed,
        transformed_policy_target_applied=applied,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (raw_result("escalate"), "approval_required"),
        (raw_result("deny", reason="runtime_error:policy_invocation_failed"), "evaluation_failed"),
        (
            raw_result("transform", transformed={"url": "https://untrusted.example"}, applied=True),
            "unsupported_transform",
        ),
        (raw_result("transform", transformed={}, applied=False), "unsupported_transform"),
    ],
)
async def test_approval_and_invalid_transform_never_execute(
    settings: Settings,
    destinations: Any,
    monkeypatch: pytest.MonkeyPatch,
    raw: SimpleNamespace,
    expected: str,
) -> None:
    class FakeControl:
        async def evaluate_intervention_point(self, *_: Any) -> object:
            return raw

    monkeypatch.setattr(runtime, "_load_control", lambda _: (FakeControl(), "test", "test"))
    body = await diagnostic_results(settings)
    assert not any(route.called for route in destinations)
    assert all(result["error_detail"] == expected for result in body["results"])


@pytest.mark.parametrize(
    ("decision", "transformed", "expected"),
    [
        ("warn", None, None),
        ("transform", {}, None),
        ("transform", {"url": "https://untrusted.example"}, "unsupported_transform"),
        ("escalate", None, "approval_required"),
    ],
)
async def test_real_sdk_warning_transform_and_approval(
    settings: Settings, tmp_path: Path, decision: str, transformed: object, expected: str | None
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    verdict: dict[str, object] = {"decision": decision, "reason": "synthetic_reason"}
    if decision == "transform":
        verdict["transform"] = {"path": "$policy_target", "value": transformed}
    (bundle / "policy.rego").write_text(
        "package containment\nimport rego.v1\ngovernance_deny := " + json.dumps(verdict) + "\n"
    )
    manifest = tmp_path / "manifest.yaml"
    source_manifest = settings.governance_manifest
    assert source_manifest is not None
    manifest.write_text(source_manifest.read_text())
    settings.governance_manifest = manifest
    rejection = await evaluate(runtime.Governance(settings), "get_servicing_policy")
    if expected is None:
        assert rejection is None
    else:
        assert rejection is not None
        assert rejection["error_detail"] == expected


async def test_real_opa_evaluation_error_is_not_policy_denial(
    settings: Settings, tmp_path: Path, destinations: Any
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "policy.rego").write_text("package containment\nimport rego.v1\nunrelated := true\n")
    manifest = tmp_path / "manifest.yaml"
    source_manifest = settings.governance_manifest
    assert source_manifest is not None
    manifest.write_text(source_manifest.read_text())
    settings.governance_manifest = manifest
    body = await diagnostic_results(settings)
    assert all(result["error_category"] == "governance_error" for result in body["results"])
    assert all(result["error_detail"] == "evaluation_failed" for result in body["results"])
    assert not any(route.called for route in destinations)


async def test_timeout_and_malformed_result_fail_closed(settings: Settings) -> None:
    class BrokenControl:
        async def evaluate_intervention_point(self, *_: Any) -> object:
            await asyncio.sleep(0.1)
            return raw_result()

    settings.governance_timeout_seconds = 0.01
    governance = runtime.Governance(settings)
    governance.control = BrokenControl()
    rejection = await evaluate(governance, "get_servicing_policy")
    assert rejection is not None
    assert rejection["error_detail"] == "evaluation_timeout"

    class MalformedControl:
        async def evaluate_intervention_point(self, *_: Any) -> object:
            return object()

    governance.control = MalformedControl()
    rejection = await evaluate(governance, "get_servicing_policy")
    assert rejection is not None
    assert rejection["error_detail"] == "invalid_verdict"


class RecordingSpan:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def get_span_context(self) -> SpanContext:
        return SpanContext(trace_id=123, span_id=456, is_remote=False, trace_flags=TraceFlags(1))

    def is_recording(self) -> bool:
        return True

    def add_event(self, name: str, attributes: dict[str, Any]) -> None:
        self.events.append((name, attributes))


async def test_governance_evidence_is_correlated_and_private(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    span = RecordingSpan()
    monkeypatch.setattr(trace, "get_current_span", lambda: span)
    rejection = await evaluate(runtime.Governance(settings), "send_to_external_processor")
    assert rejection is not None
    assert len(span.events) == 1
    name, attributes = span.events[0]
    assert name == "demo.governance_decision"
    assert attributes["demo.run_id"] == settings.demo_run_id
    assert attributes["demo.governance.session_id"] == "session-unit"
    assert attributes["demo.governance.tool_call_id"] == "call-unit"
    assert attributes["demo.governance.trace_id"] == format(123, "032x")
    assert attributes["demo.governance.acs_verdict"] == "deny"
    assert attributes["demo.governance.policy_version"].startswith("sha256:")
    telemetry.emit_governance_evidence(
        settings, {"tool_name": "test", "authorization": TOKEN, "snapshot": {"secret": TOKEN}}
    )
    assert TOKEN not in repr(span.events)
    assert "snapshot" not in repr(span.events)


class ToolCallModel(BaseLlm):
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        if any(
            part.function_response
            for content in llm_request.contents
            for part in (content.parts or [])
        ):
            yield LlmResponse(content=types.Content(parts=[types.Part(text="Completed.")]))
        else:
            yield LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(id=f"call-{name}", name=name, args={})
                        )
                        for name in sorted(agent.REQUIRED_TOOL_NAMES)
                    ],
                )
            )


@pytest.mark.parametrize(
    ("mode", "evaluation_failure"),
    [
        (GovernanceMode.DISABLED, False),
        (GovernanceMode.AUDIT, False),
        (GovernanceMode.ENFORCED, False),
        (GovernanceMode.ENFORCED, True),
    ],
    ids=["disabled", "audit", "enforced", "evaluation-failure"],
)
async def test_real_adk_dispatch_preserves_registration_and_delegated_token(
    mode: GovernanceMode,
    evaluation_failure: bool,
    destinations: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_load(_: Settings) -> Any:
        raise RuntimeError("synthetic-evaluation-failure")

    if evaluation_failure:
        monkeypatch.setattr(runtime, "_load_control", broken_load)
    settings = make_settings(mode)
    built = agent.build_agent(settings, model=ToolCallModel(model="offline-governance-test"))
    assert {tool.__name__ for tool in built.tools} == agent.REQUIRED_TOOL_NAMES
    runner = InMemoryRunner(agent=built, app_name="governance-test")
    session = await runner.session_service.create_session(
        app_name="governance-test",
        user_id="synthetic-user",
        state={agent.USER_TOKEN_STATE_KEY: "synthetic-delegated-token"},
    )
    outcomes = []
    async for event in runner.run_async(
        user_id="synthetic-user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="Run both tools.")]),
    ):
        for part in event.content.parts if event.content and event.content.parts else []:
            if part.function_response:
                outcomes.append(part.function_response.response)
    policy, receiver = destinations
    assert policy.call_count == (0 if evaluation_failure else 1)
    if not evaluation_failure:
        assert (
            policy.calls[0].request.headers["authorization"] == "Bearer synthetic-delegated-token"
        )
    assert receiver.call_count == (0 if mode is GovernanceMode.ENFORCED else 1)
    assert len(outcomes) == 2
    if evaluation_failure:
        assert all(result["error_category"] == "governance_error" for result in outcomes)
    assert all("synthetic-delegated-token" not in json.dumps(result) for result in outcomes)


def test_governance_configuration_requires_manifest_and_bounded_timeout() -> None:
    for changes in (
        {"governance_manifest": None},
        {"governance_timeout_seconds": 0},
        {"governance_timeout_seconds": 31},
        {"governance_mode": "enforcedish"},
    ):
        values = make_settings().model_dump()
        values.update(changes)
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **values)
