"""Guards on the diagnostic route.

The route exists to trigger deterministic runs. It must never become a way to reach an
arbitrary destination, and it must never be reachable without authentication.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import respx
from starlette.requests import Request

from containment_demo import diagnostics, tools
from containment_demo.settings import Settings

POLICY_BASE = "https://policy.example.com/"
RECEIVER_BASE = "https://receiver.example.net/"
POLICY_URL = "https://policy.example.com/policy"
RECEIVER_URL = "https://receiver.example.net/ingest"
TOKEN = "test-diagnostics-token-value"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        policy_api_url=POLICY_BASE,  # type: ignore[arg-type]
        test_receiver_url=RECEIVER_BASE,  # type: ignore[arg-type]
        diagnostics_token=TOKEN,  # type: ignore[arg-type]
    )


def make_request(*, query: str = "", auth: str | None = f"Bearer {TOKEN}") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if auth is not None:
        headers.append((b"authorization", auth.encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": diagnostics.DIAGNOSTICS_PATH,
            "query_string": query.encode(),
            "headers": headers,
        }
    )


def call(request: Request, settings: Settings) -> tuple[int, dict[str, Any]]:
    response = asyncio.run(diagnostics.diagnostics_handler(request, settings))
    return response.status_code, json.loads(bytes(response.body))


class TestAuthentication:
    def test_missing_header_is_rejected(self, settings: Settings) -> None:
        status, _ = call(make_request(auth=None), settings)
        assert status == 401

    def test_wrong_token_is_rejected(self, settings: Settings) -> None:
        status, _ = call(make_request(auth="Bearer wrong-token-value-here"), settings)
        assert status == 401

    def test_wrong_scheme_is_rejected(self, settings: Settings) -> None:
        status, _ = call(make_request(auth=f"Basic {TOKEN}"), settings)
        assert status == 401

    def test_empty_bearer_is_rejected(self, settings: Settings) -> None:
        status, _ = call(make_request(auth="Bearer "), settings)
        assert status == 401

    @respx.mock
    def test_correct_token_is_accepted(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={"tier": "standard"}))
        respx.post(RECEIVER_URL).mock(return_value=httpx.Response(202, json={"received": True}))
        status, _ = call(make_request(), settings)
        assert status == 200

    def test_unauthenticated_request_makes_no_outbound_call(self, settings: Settings) -> None:
        """Rejection must happen before any tool runs, not after."""
        with respx.mock:
            policy = respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={}))
            receiver = respx.post(RECEIVER_URL).mock(return_value=httpx.Response(202, json={}))
            call(make_request(auth=None), settings)
            assert not policy.called
            assert not receiver.called


class TestNoArbitraryDestination:
    def test_handler_accepts_no_destination_parameter(self) -> None:
        """A url/host/path parameter would defeat the fixed-destination guarantee."""
        import inspect

        params = set(inspect.signature(diagnostics.diagnostics_handler).parameters)
        assert params == {"request", "settings"}

    def test_runner_table_is_exactly_the_two_business_tools(self) -> None:
        assert set(diagnostics._RUNNERS) == {
            "get_servicing_policy",
            "send_to_external_processor",
        }

    def test_runners_are_the_same_objects_the_agent_uses(self) -> None:
        """Not a copy, not a re-implementation — the identical callables."""
        assert diagnostics._RUNNERS["get_servicing_policy"] is tools.get_servicing_policy
        assert (
            diagnostics._RUNNERS["send_to_external_processor"] is tools.send_to_external_processor
        )

    @respx.mock
    def test_unknown_tool_name_is_rejected(self, settings: Settings) -> None:
        policy = respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={}))
        status, _ = call(make_request(query="tool=https://evil.example.com"), settings)
        assert status == 400
        assert not policy.called, "an unknown tool name must not fall through to a real call"

    def test_source_contains_no_url_construction(self) -> None:
        import inspect

        source = inspect.getsource(diagnostics)
        body = source.split('"""', 2)[-1]
        assert "http://" not in body
        assert "https://" not in body


class TestResults:
    @respx.mock
    def test_both_tools_run_by_default(self, settings: Settings) -> None:
        policy = respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={"a": 1}))
        receiver = respx.post(RECEIVER_URL).mock(return_value=httpx.Response(202, json={"b": 2}))
        status, body = call(make_request(), settings)
        assert status == 200
        assert policy.called and receiver.called
        assert [r["tool_name"] for r in body["results"]] == [
            "get_servicing_policy",
            "send_to_external_processor",
        ]

    @respx.mock
    def test_a_single_tool_can_be_selected(self, settings: Settings) -> None:
        policy = respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={}))
        receiver = respx.post(RECEIVER_URL).mock(return_value=httpx.Response(202, json={}))
        status, body = call(make_request(query="tool=get_servicing_policy"), settings)
        assert status == 200
        assert policy.called
        assert not receiver.called
        assert len(body["results"]) == 1

    @respx.mock
    def test_one_tool_failing_does_not_suppress_the_other(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(side_effect=httpx.ConnectError("boom"))
        respx.post(RECEIVER_URL).mock(return_value=httpx.Response(202, json={}))
        status, body = call(make_request(), settings)
        assert status == 200
        assert len(body["results"]) == 2
        assert body["results"][0]["succeeded"] is False
        assert body["results"][1]["succeeded"] is True

    @respx.mock
    def test_response_makes_no_allow_or_deny_determination(self, settings: Settings) -> None:
        """Missing platform evidence is inconclusive, never a pass or a proven denial."""
        respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={}))
        respx.post(RECEIVER_URL).mock(return_value=httpx.Response(403))
        _, body = call(make_request(), settings)

        assert body["determination"] == "inconclusive-without-platform-evidence"
        rendered = json.dumps(body).lower()
        for forbidden in ("denied", "blocked", "contained", "allowed_by_policy"):
            assert forbidden not in rendered, (
                f"diagnostic response claimed {forbidden!r}; the application cannot observe "
                "a platform decision and must not imply one"
            )

    @respx.mock
    def test_response_carries_the_run_correlation_marker(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={}))
        respx.post(RECEIVER_URL).mock(return_value=httpx.Response(202, json={}))
        _, body = call(make_request(), settings)
        assert body["demo_run_id"] == settings.demo_run_id
        assert all(r["demo_run_id"] == settings.demo_run_id for r in body["results"])
