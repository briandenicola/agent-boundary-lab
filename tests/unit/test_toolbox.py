from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from azure.ai.agentserver.core._request_context import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)
from azure.core.credentials import AccessToken
from pydantic import ValidationError

from containment_demo import toolbox, tools
from containment_demo.agent import REQUIRED_TOOL_NAMES, build_tool_functions
from containment_demo.settings import Settings

ENDPOINT = "https://foundry.example.com/api/projects/demo/toolboxes/servicing/versions/1/mcp?api-version=v1"
TOOL = "servicing___get_servicing_policy"
CONSENT = "https://logic-test.consent.azure-apihub.net/login?data=private-oauth-state"


def settings(**overrides: Any) -> Settings:
    return Settings(
        **{
            "policy_api_url": "https://policy.example.com",
            "test_receiver_url": "https://receiver.example.com",
            "diagnostics_enabled": False,
            "toolbox_endpoint": ENDPOINT,
            "toolbox_policy_tool": TOOL,
            "demo_run_id": "chat-synthetic-toolbox",
            **overrides,
        }
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"toolbox_endpoint": None},
        {"toolbox_policy_tool": None},
        {"toolbox_endpoint": ENDPOINT.replace("https:", "http:")},
        {"toolbox_endpoint": ENDPOINT + "&unexpected="},
        {"toolbox_policy_tool": "servicing___arbitrary_tool"},
    ],
)
def test_invalid_or_partial_toolbox_configuration_fails_at_startup(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        settings(**overrides)


@pytest.fixture
def caller() -> Iterator[None]:
    token = set_request_context(FoundryAgentRequestContext(call_id="call-user-a", user_id="user-a"))
    try:
        yield
    finally:
        reset_request_context(token)


@pytest.fixture
def credential(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    scopes: list[str] = []

    class Credential:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs["retry_total"] == 0
            assert kwargs["connection_timeout"] > 0
            assert kwargs["read_timeout"] > 0

        def __enter__(self) -> Credential:
            return self

        def __exit__(self, *_: Any) -> None:
            pass

        def get_token(self, scope: str) -> AccessToken:
            scopes.append(scope)
            return AccessToken(f"workload-token-{len(scopes)}", int(time.time()) + 300)

    monkeypatch.setattr(toolbox, "ManagedIdentityCredential", Credential)
    return scopes


def response(request: httpx.Request) -> httpx.Response:
    rpc = json.loads(request.content)
    if rpc["method"] == "tools/list":
        result = {
            "tools": [
                {"name": TOOL, "_meta": {"tool_configuration": {"require_approval": "never"}}}
            ]
        }
    else:
        assert rpc["method"] == "tools/call"
        assert rpc["params"]["name"] == TOOL
        assert set(rpc["params"]["arguments"]) == {"demo_run_id"}
        result = {
            "structuredContent": {
                "demo_run_id": rpc["params"]["arguments"]["demo_run_id"],
                "policy": {"policy_id": "SVC-DEMO-0001"},
                "user_object_id": "authorized-synthetic-user",
            },
            "isError": False,
        }
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": rpc["id"], "result": result})


def install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Any = response
) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    monkeypatch.setattr(
        tools,
        "_build_client",
        lambda _: httpx.Client(
            transport=httpx.MockTransport(handle), timeout=1, follow_redirects=False
        ),
    )
    return requests


def test_toolbox_uses_platform_context_and_workload_tokens_only(
    caller: None, credential: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = install_transport(monkeypatch)
    result = tools.get_servicing_policy(settings(), user_token="must-not-forward-this-token")
    assert result["succeeded"] is True
    assert result["transport"] == "toolbox"
    assert result["destination_host"] == "foundry.example.com"
    assert result["http_status"] is None
    assert credential == ["https://ai.azure.com/.default"] * 2
    assert [r.headers["authorization"] for r in requests] == [
        "Bearer workload-token-1",
        "Bearer workload-token-2",
    ]
    assert all(r.headers["x-agent-foundry-call-id"] == "call-user-a" for r in requests)
    assert all("x-agent-user-id" not in r.headers for r in requests)
    assert "must-not-forward" not in str(requests) + json.dumps(result)
    assert {fn.__name__ for fn in build_tool_functions(settings())} == REQUIRED_TOOL_NAMES


def test_missing_caller_context_never_uses_an_app_only_fallback(
    credential: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = install_transport(monkeypatch)
    result = tools.get_servicing_policy(settings())
    assert result["succeeded"] is False
    assert result["error_detail"] == "toolbox_user_context_missing"
    assert not requests
    assert not credential


def test_consent_is_request_scoped_and_excluded_from_tool_results(
    caller: None, credential: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def consent(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": json.loads(request.content)["id"],
                "error": {
                    "code": -32006,
                    "message": "tools/list failed for 1 tool source(s) "
                    + json.dumps(
                        {"errors": [{"error": {"code": "CONSENT_REQUIRED", "message": CONSENT}}]}
                    ),
                },
            },
        )

    requests = install_transport(monkeypatch, consent)
    with toolbox.capture_consent() as turn:
        result = tools.get_servicing_policy(settings())
        assert turn.consent_links == [CONSENT]
    with toolbox.capture_consent() as other_turn:
        assert other_turn.consent_links == []
    assert result["error_category"] == "consent_required"
    assert CONSENT not in json.dumps(result)
    assert len(requests) == 1


def test_streaming_toolbox_results_are_consumed_without_waiting_for_disconnect(
    caller: None, credential: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def streaming(request: httpx.Request) -> httpx.Response:
        body = response(request).json()
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream; charset=utf-8"},
            content=b": keepalive\r\n\r\ndata: " + json.dumps(body).encode() + b"\r\n\r\n",
        )

    install_transport(monkeypatch, streaming)
    assert tools.get_servicing_policy(settings())["succeeded"] is True


@pytest.mark.parametrize(
    "failure", ["approval", "missing-tool", "invalid-result", "redirect", "rpc"]
)
def test_toolbox_failures_never_fall_back_to_direct_http(
    caller: None,
    credential: list[str],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://unrelated.example/"})
        body = response(request).json()
        if failure == "approval":
            body["result"]["tools"][0]["_meta"]["tool_configuration"]["require_approval"] = "always"
        elif failure == "missing-tool":
            body["result"]["tools"] = []
        elif failure == "invalid-result" and json.loads(request.content)["method"] == "tools/call":
            body["result"]["structuredContent"]["demo_run_id"] = "another-run"
        elif failure == "rpc":
            body.pop("result")
            body["error"] = {"code": -32006, "message": "private-upstream-secret"}
        return httpx.Response(200, json=body)

    requests = install_transport(monkeypatch, fail)
    result = tools.get_servicing_policy(settings())
    assert result["succeeded"] is False
    assert all(str(request.url) == ENDPOINT for request in requests)
    assert "private-upstream-secret" not in json.dumps(result)


async def test_concurrent_users_do_not_share_platform_call_context(
    credential: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    requests = install_transport(monkeypatch)

    async def invoke(user: str) -> dict[str, Any]:
        token = set_request_context(
            FoundryAgentRequestContext(call_id=f"call-{user}", user_id=user)
        )
        try:
            return await asyncio.to_thread(
                tools.get_servicing_policy, settings(demo_run_id=f"chat-{user}")
            )
        finally:
            reset_request_context(token)

    results = await asyncio.gather(invoke("a"), invoke("b"))
    assert all(result["succeeded"] for result in results)
    for request in requests:
        rpc = json.loads(request.content)
        if rpc["method"] == "tools/call":
            user = rpc["params"]["arguments"]["demo_run_id"].removeprefix("chat-")
            assert request.headers["x-agent-foundry-call-id"] == f"call-{user}"


@pytest.mark.parametrize("broken_evaluator", [False, True])
async def test_real_adk_runs_acs_before_toolbox_or_receiver(
    caller: None,
    credential: list[str],
    monkeypatch: pytest.MonkeyPatch,
    broken_evaluator: bool,
) -> None:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from containment_demo.agent import build_agent
    from containment_demo.governance import runtime
    from tests.unit.test_governance import ToolCallModel, make_settings

    requests = install_transport(monkeypatch)
    cfg = Settings.model_validate(
        {
            **make_settings().model_dump(),
            "toolbox_endpoint": ENDPOINT,
            "toolbox_policy_tool": TOOL,
        }
    )
    if broken_evaluator:

        def broken(_: Settings) -> Any:
            raise RuntimeError("synthetic-evaluator-failure")

        monkeypatch.setattr(runtime, "_load_control", broken)
    built = build_agent(cfg, model=ToolCallModel(model="offline-toolbox"))
    assert {fn.__name__ for fn in built.tools} == REQUIRED_TOOL_NAMES
    runner = InMemoryRunner(agent=built, app_name="offline-toolbox")
    session = await runner.session_service.create_session(
        app_name="offline-toolbox",
        user_id="synthetic-user",
    )
    outcomes = {}
    async for event in runner.run_async(
        user_id="synthetic-user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text="Run both tools.")]),
    ):
        for part in event.content.parts if event.content and event.content.parts else []:
            if part.function_response:
                outcomes[part.function_response.name] = part.function_response.response
    assert len(outcomes) == 2
    if broken_evaluator:
        assert not requests
        assert not credential
        assert all(result["error_category"] == "governance_error" for result in outcomes.values())
    else:
        assert len(requests) == 2
        assert all(str(request.url) == ENDPOINT for request in requests)
        assert outcomes["get_servicing_policy"]["succeeded"] is True
        assert outcomes["send_to_external_processor"]["error_category"] == "governance_denied"
