"""A2A spike logic. Offline: every live operation is injected or its SDK is faked."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from containment_demo import a2a_spike


class StatusError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status


# The card exactly as observed from the platform on 2026-10-09 (shape only, trimmed).
OBSERVED_CARD: dict[str, Any] = {
    "name": "containment-demo-audit",
    "version": "1.0",
    "supportedInterfaces": [
        {"url": "https://h.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
        {"url": "https://h.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "0.3"},
        {"url": "https://h.example/a2a", "protocolBinding": "HTTP+JSON", "protocolVersion": "0.3"},
    ],
    "capabilities": {"streaming": False},
}


def card_ok(base: str, timeout: float) -> tuple[int, dict[str, Any] | None]:
    return 200, OBSERVED_CARD


def send_ok(base: str, timeout: float, option: Any, wire: list[Any]) -> int:
    return 1


def noop_enable(endpoint: str, agent: str) -> None:
    return None


def run(**over: Any) -> a2a_spike.SpikeResult:
    kw: dict[str, Any] = {
        "endpoint": "https://a.services.ai.azure.com/api/projects/p",
        "agent_name": "agent-a",
        "enable": False,
        "send": False,
        "enable_fn": noop_enable,
        "card_fn": card_ok,
        "send_fn": send_ok,
    }
    kw.update(over)
    return a2a_spike.run_spike(**kw)


def step(result: a2a_spike.SpikeResult, name: str) -> a2a_spike.StepResult:
    return next(s for s in result.steps if s.name == name)


def test_determination_is_never_a_pass_even_when_everything_succeeds() -> None:
    result = run(enable=True, send=True)
    assert [s.status for s in result.steps] == ["ok", "ok", "ok"]
    assert result.determination == a2a_spike.DETERMINATION
    assert result.as_dict()["determination"] == "inconclusive-a2a-unverified"
    assert "pass" not in result.as_dict()["determination"]


def test_enable_does_not_run_without_the_flag() -> None:
    calls: list[str] = []
    result = run(enable_fn=lambda e, a: calls.append(a))
    assert calls == []
    assert step(result, "enable").status == "skipped"


def test_send_does_not_run_without_the_flag() -> None:
    calls: list[str] = []
    result = run(send_fn=lambda b, t, o, w: calls.append(b) or 1)
    assert calls == []
    assert step(result, "send").status == "skipped"


def test_platform_404_on_card_is_a_signal_not_a_conclusion() -> None:
    def card(base: str, timeout: float) -> tuple[int, None]:
        raise StatusError(404)

    result = run(card_fn=card)
    s = step(result, "card")
    assert (s.status, s.origin, s.http_status) == ("unsupported-signal", "platform", 404)
    assert result.determination == a2a_spike.DETERMINATION
    assert result.as_dict()["unsupported_signals"] == ["card"]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_and_network_denials_are_our_call_not_unsupported(status: int) -> None:
    def card(base: str, timeout: float) -> tuple[int, None]:
        raise StatusError(status)

    s = step(run(card_fn=card), "card")
    assert (s.status, s.origin) == ("failed", "our_call")


def test_transport_failure_is_our_call_with_a_category() -> None:
    class ConnectTimeout(Exception):
        pass

    def card(base: str, timeout: float) -> tuple[int, None]:
        raise ConnectTimeout("timed out")

    s = step(run(card_fn=card), "card")
    assert (s.status, s.origin, s.error_category) == ("failed", "our_call", "timeout")


def test_platform_500_is_failed_not_unsupported() -> None:
    def card(base: str, timeout: float) -> tuple[int, None]:
        raise StatusError(500)

    s = step(run(card_fn=card), "card")
    assert (s.status, s.origin) == ("failed", "platform")


def test_send_failure_is_never_an_unsupported_signal() -> None:
    def send(base: str, timeout: float, option: Any, wire: list[Any]) -> int:
        raise StatusError(404)

    s = step(run(send=True, send_fn=send), "send:jsonrpc-1.0")
    assert s.status == "failed"


def _card(*versions: str, top: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": "a",
        **(top or {}),
        "supportedInterfaces": [
            {"url": "https://x.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": v}
            for v in versions
        ],
    }


def test_card_with_a_1_0_interface_is_ok_like_the_observed_card() -> None:
    s = step(run(card_fn=lambda b, t: (200, OBSERVED_CARD)), "card")
    assert s.status == "ok"
    assert s.observed["card_protocol_versions"] == ["1.0", "0.3", "0.3"]
    assert "supportedInterfaces" in s.observed["card_keys"]


def test_card_declaring_only_another_version_is_a_failure() -> None:
    s = step(run(card_fn=lambda b, t: (200, _card("0.3"))), "card")
    assert s.status == "failed"
    assert s.observed["card_protocol_versions"] == ["0.3"]


def test_top_level_version_is_not_the_protocol_version() -> None:
    card = _card("0.3", top={"version": "1.0", "protocolVersion": "1.0"})
    assert step(run(card_fn=lambda b, t: (200, card)), "card").status == "failed"


def test_card_without_interfaces_is_a_failure_not_a_crash() -> None:
    assert step(run(card_fn=lambda b, t: (200, {"name": "a"})), "card").status == "failed"


def test_raw_card_is_recorded_bounded_and_redacted() -> None:
    card = _card("1.0", top={"description": "Bearer abc.def-123_xyz " + "x" * 9000})
    s = step(run(card_fn=lambda b, t: (200, card)), "card")
    raw = s.observed["card_raw"]
    assert len(raw) <= a2a_spike.CARD_CAP == 4096
    assert "abc.def-123_xyz" not in raw
    assert "supportedInterfaces[0].protocolVersion" in s.observed["card_version_fields"]


def test_one_step_failing_does_not_hide_the_others() -> None:
    def enable(endpoint: str, agent: str) -> None:
        raise StatusError(400)

    result = run(enable=True, send=True, enable_fn=enable)
    assert [s.status for s in result.steps] == ["unsupported-signal", "ok", "ok"]


def test_card_url_uses_v1_0_path_and_pins_version() -> None:
    assert a2a_spike.CARD_PATH == "agentCard/v1.0"
    assert a2a_spike.A2A_VERSION == "1.0"
    base = a2a_spike.a2a_base("https://x/api/projects/p", "agent-a")
    assert base == "https://x/api/projects/p/agents/agent-a/endpoint/protocols/a2a"


@pytest.mark.parametrize("name", ["a/../b", "https://evil", "", "a b"])
def test_agent_name_is_validated(name: str) -> None:
    with pytest.raises(ValueError):
        a2a_spike.a2a_base("https://x", name)


def test_account_and_project_are_validated() -> None:
    with pytest.raises(ValueError):
        a2a_spike.project_endpoint("evil.example.com/x", "p")


def test_result_records_no_response_text_or_token() -> None:
    blob = str(run(enable=True, send=True).as_dict())
    assert a2a_spike._PROBE_TEXT not in blob
    assert "Bearer" not in blob


def _fake_azure(monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]) -> None:
    models = types.ModuleType("azure.ai.projects.models")
    for name in (
        "A2AProtocolConfiguration",
        "AgentCard",
        "AgentCardSkill",
        "AgentEndpointConfig",
        "ProtocolConfiguration",
        "ResponsesProtocolConfiguration",
    ):
        setattr(models, name, type(name, (), {"__init__": lambda s, **kw: s.__dict__.update(kw)}))

    class Agents:
        def update_details(self, **kw: Any) -> None:
            calls.append(kw)

    class Client:
        agents = Agents()

        def __init__(self, **kw: Any) -> None:
            calls.append({"client": kw})

    projects = types.ModuleType("azure.ai.projects")
    projects.AIProjectClient = Client  # type: ignore[attr-defined]
    projects.models = models  # type: ignore[attr-defined]
    ident = types.ModuleType("azure.identity")
    ident.DefaultAzureCredential = lambda: object()  # type: ignore[attr-defined]
    for dotted, mod in {
        "azure": types.ModuleType("azure"),
        "azure.ai": types.ModuleType("azure.ai"),
        "azure.ai.projects": projects,
        "azure.ai.projects.models": models,
        "azure.identity": ident,
    }.items():
        monkeypatch.setitem(sys.modules, dotted, mod)


def test_live_enable_patches_responses_and_a2a_with_a_card(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    _fake_azure(monkeypatch, calls)
    a2a_spike.live_enable("https://x/api/projects/p", "agent-a")
    patch = calls[-1]
    assert patch["agent_name"] == "agent-a"
    proto = patch["agent_endpoint"].protocol_configuration
    assert proto.responses is not None and proto.a2a is not None
    assert patch["agent_card"].version == "1.0"
    assert patch["agent_card"].skills


def test_main_defaults_to_read_only(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    seen: dict[str, Any] = {}

    def fake(**kw: Any) -> a2a_spike.SpikeResult:
        seen.update(kw)
        return a2a_spike.SpikeResult(agent_name="a", a2a_base="b")

    monkeypatch.setattr(a2a_spike, "run_spike", fake)
    assert a2a_spike.main(["--account", "acct", "--project", "proj", "--agent", "agent-a"]) == 0
    assert seen["enable"] is False and seen["send"] is False
    assert "inconclusive-a2a-unverified" in capsys.readouterr().out


class TestHttpStatusErrorClassification:
    """Regression: httpx puts the status on exc.response, so a platform 400 was 'our_call'."""

    @staticmethod
    def _status_error(status: int, text: str) -> Exception:
        import httpx

        request = httpx.Request("GET", "https://x.example/agentCard/v1.0")
        response = httpx.Response(status, text=text, request=request)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return exc
        raise AssertionError("expected a status error")

    def test_a_platform_400_on_the_card_is_platform_with_status_and_body(self) -> None:
        exc = self._status_error(400, '{"error":{"message":"A2A is not enabled for this agent"}}')
        step = a2a_spike.classify_failure("card", exc, may_signal_unsupported=True)
        assert step.origin == "platform"
        assert step.http_status == 400
        assert step.error_category == "http_error"
        assert "A2A is not enabled" in step.observed["response_body"]

    def test_a_401_is_still_our_call(self) -> None:
        step = a2a_spike.classify_failure(
            "card", self._status_error(401, "nope"), may_signal_unsupported=True
        )
        assert step.origin == "our_call"
        assert step.http_status == 401

    def test_body_is_capped(self) -> None:
        step = a2a_spike.classify_failure(
            "card", self._status_error(400, "x" * 10_000), may_signal_unsupported=True
        )
        assert len(step.observed["response_body"]) == a2a_spike.BODY_CAP == 2048

    @pytest.mark.parametrize(
        "secret",
        [
            "Bearer abc.def-123_xyz",
            "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl",
            "Authorization: topsecretvalue",
            '"access_token": "topsecretvalue"',
        ],
    )
    def test_tokens_never_survive_in_the_body(self, secret: str) -> None:
        step = a2a_spike.classify_failure(
            "card",
            self._status_error(400, f"bad request {secret} end"),
            may_signal_unsupported=True,
        )
        body = step.observed["response_body"]
        assert "topsecretvalue" not in body
        assert "abc.def-123_xyz" not in body
        assert "eyJhbGci" not in body
        assert "bad request" in body

    def test_a_transport_failure_has_no_body_and_stays_our_call(self) -> None:
        step = a2a_spike.classify_failure("card", TimeoutError("slow"), may_signal_unsupported=True)
        assert step.origin == "our_call"
        assert "response_body" not in step.observed


RPC_32099 = (
    "JSON-RPC Error -32099: The requested A2A operation is not supported "
    "for this hosted-agent target."
)
WIRE = [
    {
        "kind": "request",
        "http_method": "POST",
        "url_path": "/a2a",
        "a2a_version_header": "1.0",
        "jsonrpc_method": "SendMessage",
    },
    {"kind": "response", "status": 200, "response_body": "{}"},
]


def _send_raising(exc: Exception, wire: list[Any] | None = None) -> a2a_spike.StepResult:
    def send(base: str, timeout: float, option: Any, w: list[Any]) -> int:
        w.extend(wire or [])
        raise exc

    return step(run(send=True, send_fn=send), "send:jsonrpc-1.0")


class TestJsonRpcPlatformError:
    def test_32099_not_supported_is_platform_and_unsupported_signal(self) -> None:
        s = _send_raising(RuntimeError(RPC_32099), WIRE)
        assert (s.status, s.origin) == ("unsupported-signal", "platform")
        assert s.observed["jsonrpc_code"] == -32099
        assert "not supported" in s.observed["jsonrpc_message"]

    def test_unrelated_jsonrpc_code_is_platform_but_only_failed(self) -> None:
        s = _send_raising(RuntimeError("JSON-RPC Error -32603: Internal error"), WIRE)
        assert (s.status, s.origin) == ("failed", "platform")
        assert s.observed["jsonrpc_code"] == -32603

    def test_code_is_read_from_the_wire_body_when_text_has_none(self) -> None:
        body = '{"jsonrpc":"2.0","error":{"code":-32601,"message":"Method not found"}}'
        wire = [*WIRE[:1], {"kind": "response", "status": 200, "response_body": body}]
        s = _send_raising(RuntimeError("boom"), wire)
        assert (s.status, s.origin, s.observed["jsonrpc_code"]) == (
            "unsupported-signal",
            "platform",
            -32601,
        )

    def test_transport_failure_without_a_platform_answer_stays_our_call(self) -> None:
        class ConnectTimeout(Exception):
            pass

        s = _send_raising(ConnectTimeout("timed out"))
        assert (s.status, s.origin) == ("failed", "our_call")


class TestSendRecordsWire:
    def test_exact_binding_version_header_and_method_are_recorded(self) -> None:
        s = _send_raising(RuntimeError(RPC_32099), WIRE)
        o = s.observed
        assert (o["binding"], o["protocolVersion"]) == ("JSONRPC", "1.0")
        assert (o["a2a_version_header"], o["jsonrpc_method"]) == ("1.0", "SendMessage")

    def test_success_records_the_wire_too(self) -> None:
        def send(base: str, timeout: float, option: Any, w: list[Any]) -> int:
            w.extend(WIRE)
            return 1

        s = step(run(send=True, send_fn=send), "send:jsonrpc-1.0")
        assert (s.status, s.observed["jsonrpc_method"]) == ("ok", "SendMessage")


class TestSendOptions:
    def test_all_three_advertised_options_exist(self) -> None:
        got = {(o.binding, o.version) for o in a2a_spike.SEND_OPTIONS.values()}
        assert got == {("JSONRPC", "1.0"), ("JSONRPC", "0.3"), ("HTTP+JSON", "0.3")}

    def test_each_option_is_tried_exactly_once_with_no_retry(self) -> None:
        calls: list[str] = []

        def send(base: str, timeout: float, option: Any, w: list[Any]) -> int:
            calls.append(option.label)
            raise RuntimeError(RPC_32099)

        result = run(send=True, send_fn=send, send_options=list(a2a_spike.SEND_OPTIONS))
        assert calls == ["jsonrpc-1.0", "jsonrpc-0.3", "http-0.3"]
        assert all(s.origin == "platform" for s in result.steps if s.name.startswith("send:"))

    def test_one_option_failing_does_not_hide_the_next(self) -> None:
        def send(base: str, timeout: float, option: Any, w: list[Any]) -> int:
            if option.label == "jsonrpc-1.0":
                raise RuntimeError(RPC_32099)
            return 1

        result = run(send=True, send_fn=send, send_options=["jsonrpc-1.0", "jsonrpc-0.3"])
        assert [s.status for s in result.steps if s.name.startswith("send:")] == [
            "unsupported-signal",
            "ok",
        ]
