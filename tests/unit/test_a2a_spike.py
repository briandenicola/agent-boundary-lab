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


def card_ok(base: str, timeout: float) -> tuple[int, dict[str, Any] | None]:
    return 200, {"protocolVersion": "1.0"}


def send_ok(base: str, timeout: float) -> int:
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
    result = run(send_fn=lambda b, t: calls.append(b) or 1)
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
    def send(base: str, timeout: float) -> int:
        raise StatusError(404)

    s = step(run(send=True, send_fn=send), "send")
    assert s.status == "failed"


def test_card_declaring_another_version_is_a_failure() -> None:
    s = step(run(card_fn=lambda b, t: (200, {"protocolVersion": "0.3"})), "card")
    assert s.status == "failed"
    assert s.observed["card_protocol_version"] == "0.3"


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
