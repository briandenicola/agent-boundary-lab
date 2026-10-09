"""Harness guards. Offline: the A2A sender and the model are fakes."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from containment_demo.harness import agent, chat
from containment_demo.harness.settings import HarnessSettings

TOKEN = "u" * 24
A2A_TOKEN = "a" * 24
RUN_ID = "run-11111111-2222-3333-4444-555555555555"


def make_settings(**over: Any) -> HarnessSettings:
    base: dict[str, Any] = {
        "local_model_base_url": "http://llama.ns.svc.cluster.local:8080/v1",
        "a2a_facade_url_audit": "http://facade-audit.ns.svc.cluster.local",
        "a2a_facade_url_enforced": "http://facade-enforced.ns.svc.cluster.local",
        "a2a_token": A2A_TOKEN,
        "ui_token": TOKEN,
        "run_label": "local",
    }
    base.update(over)
    return HarnessSettings(**base)


def _record_text(run_id: str) -> str:
    return json.dumps(
        {
            "tool": "get_servicing_policy",
            "ok": True,
            "http_status": 200,
            "destination_host": "policy.example.com",
            "run_id": run_id,
        }
    )


class FakeSender:
    def __init__(self, fail_for: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_for = fail_for

    async def __call__(
        self, base: str, token: str, text: str = "", timeout: float = 0.0
    ) -> dict[str, Any]:
        self.calls.append(base)
        if self.fail_for and self.fail_for in base:
            raise RuntimeError("boom")
        return {"task_state": "TASK_STATE_COMPLETED", "text": "", "downstream_response_id": "r1"}


def _tool_map(settings: HarnessSettings, sender: Any) -> dict[str, Any]:
    return {f.__name__: f for f in agent.build_tool_functions(settings, sender)}


class TestSettings:
    def test_model_url_must_not_be_an_ip(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(local_model_base_url="http://10.0.0.4:8080/v1")

    def test_short_tokens_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(ui_token="short")

    def test_timeouts_are_generous_and_configurable(self) -> None:
        s = make_settings()
        assert s.model_timeout_seconds >= 120 and s.tool_timeout_seconds >= 120
        assert make_settings(model_timeout_seconds=300).model_timeout_seconds == 300

    def test_env_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LOCAL_MODEL_BASE_URL", "http://m.ns.svc.cluster.local/v1")
        monkeypatch.setenv("DEMO_A2A_FACADE_URL_AUDIT", "http://a.ns.svc.cluster.local")
        monkeypatch.setenv("DEMO_A2A_FACADE_URL_ENFORCED", "http://e.ns.svc.cluster.local")
        monkeypatch.setenv("DEMO_A2A_TOKEN", A2A_TOKEN)
        monkeypatch.setenv("HARNESS_UI_TOKEN", TOKEN)
        monkeypatch.setenv("DEMO_RUN_LABEL", "hosted")
        assert HarnessSettings().local_model_base_url.endswith("/v1")  # type: ignore[call-arg]


class TestBothToolsAreAlwaysRegistered:
    def test_exactly_two_tools_built(self) -> None:
        names = {f.__name__ for f in agent.build_tool_functions(make_settings())}
        assert names == set(agent.REQUIRED_TOOL_NAMES) and len(names) == 2

    def test_tools_take_no_arguments(self) -> None:
        for fn in agent.build_tool_functions(make_settings()):
            assert not inspect.signature(fn).parameters

    def test_agent_registers_both_tools(self) -> None:
        built = agent.build_agent(make_settings())
        assert {t.__name__ for t in built.tools} == set(agent.REQUIRED_TOOL_NAMES)

    @pytest.mark.parametrize("label", ["local", "hosted"])
    def test_registration_identical_across_labels(self, label: str) -> None:
        names = {f.__name__ for f in agent.build_tool_functions(make_settings(run_label=label))}
        assert names == set(agent.REQUIRED_TOOL_NAMES)

    def test_guard_rejects_a_missing_tool(self) -> None:
        fns = agent.build_tool_functions(make_settings())
        with pytest.raises(RuntimeError):
            agent.assert_both_tools(fns[:1])

    def test_guard_rejects_an_extra_tool(self) -> None:
        def third() -> None: ...

        with pytest.raises(RuntimeError):
            agent.assert_both_tools([*agent.build_tool_functions(make_settings()), third])

    def test_build_agent_runs_the_guard(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real = agent.build_tool_functions
        monkeypatch.setattr(agent, "build_tool_functions", lambda s, snd=None: real(s)[:1])
        with pytest.raises(RuntimeError):
            agent.build_agent(make_settings())

    def test_no_slot_conditionals_in_tool_source(self) -> None:
        src = Path(agent.__file__).read_text()
        body = src.split("def build_tool_functions")[1].split("def assert_both_tools")[0]
        assert "if " not in body


class TestToolBehaviour:
    def test_each_tool_sends_to_its_own_facade_only(self) -> None:
        sender = FakeSender()
        tools = _tool_map(make_settings(), sender)
        asyncio.run(tools["ask_audit_agent"]())
        assert sender.calls == ["http://facade-audit.ns.svc.cluster.local"]
        asyncio.run(tools["ask_enforced_agent"]())
        assert sender.calls[1] == "http://facade-enforced.ns.svc.cluster.local"

    def test_result_has_state_outcomes_and_run_id(self) -> None:
        async def sender(base: str, token: str, text: str = "", timeout: float = 0.0) -> Any:
            return {
                "task_state": "TASK_STATE_COMPLETED",
                "text": _record_text(RUN_ID),
                "downstream_response_id": "r1",
            }

        out = asyncio.run(agent.call_slot(make_settings(), "audit", sender))
        assert out["task_state"] == "TASK_STATE_COMPLETED"
        assert out["determination"].startswith("inconclusive")
        assert {o["tool_name"] for o in out["tool_outcomes"]} == {
            "get_servicing_policy",
            "send_to_external_processor",
        }
        assert "tool_run_ids" in out

    def test_one_failure_does_not_suppress_the_other(self) -> None:
        sender = FakeSender(fail_for="audit")
        tools = _tool_map(make_settings(), sender)
        bad = asyncio.run(tools["ask_audit_agent"]())
        good = asyncio.run(tools["ask_enforced_agent"]())
        assert bad["ok"] is False and good["ok"] is True
        assert good["task_state"] == "TASK_STATE_COMPLETED"

    def test_no_retry_on_failure(self) -> None:
        sender = FakeSender(fail_for="audit")
        asyncio.run(agent.call_slot(make_settings(), "audit", sender))
        assert len(sender.calls) == 1

    def test_unknown_slot_rejected(self) -> None:
        with pytest.raises(KeyError):
            asyncio.run(agent.call_slot(make_settings(), "other", FakeSender()))

    def test_model_has_bounded_timeout_and_no_retries(self) -> None:
        model = agent.build_model(make_settings(model_timeout_seconds=200))
        assert model._additional_args["timeout"] == 200
        assert model._additional_args["num_retries"] == 0


class FakeResponder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def __call__(self, settings: HarnessSettings, message: str) -> dict[str, Any]:
        self.messages.append(message)
        return {
            "reply": "done",
            "tool_results": [{"tool": "ask_audit_agent", "result": {"tool_run_ids": [RUN_ID]}}],
        }


def client(responder: Any = None, **over: Any) -> TestClient:
    return TestClient(
        chat.create_app(make_settings(**over), responder=responder or FakeResponder())
    )


AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Demo-UI": "1"}


class TestChat:
    def test_requires_auth(self) -> None:
        assert client().post("/chat", json={"message": "hi"}).status_code == 401
        assert client().get("/").status_code == 401

    def test_requires_csrf_header(self) -> None:
        r = client().post(
            "/chat", json={"message": "hi"}, headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert r.status_code == 403

    def test_turn_shows_reply_tools_and_run_id(self) -> None:
        r = client().post("/chat", json={"message": "go"}, headers=AUTH)
        body = r.json()
        assert body["reply"] == "done"
        assert body["tool_run_ids"] == [RUN_ID]
        assert body["tool_results"][0]["tool"] == "ask_audit_agent"
        assert body["determination"].startswith("inconclusive")
        assert body["governed_by_foundry_policy"] is False

    def test_bad_messages_rejected(self) -> None:
        for payload in ({"message": ""}, {"message": "x" * 2000}, {"nope": 1}, {"message": 3}):
            assert client().post("/chat", json=payload, headers=AUTH).status_code == 400

    def test_page_states_the_limits(self) -> None:
        text = client().get("/", headers={"Authorization": f"Bearer {TOKEN}"}).text
        assert "NOT governed by the Foundry egress policy" in text
        assert "not containment evidence" in text
        assert "INCONCLUSIVE" in text
        assert "working (local model" in text

    def test_responder_failure_is_labelled_harness_and_not_a_pass(self) -> None:
        async def boom(settings: HarnessSettings, message: str) -> dict[str, Any]:
            raise RuntimeError("model down")

        r = client(boom).post("/chat", json={"message": "go"}, headers=AUTH)
        assert r.status_code == 502 and r.json()["source"] == "harness/model"

    def test_turn_timeout(self) -> None:
        async def slow(settings: HarnessSettings, message: str) -> dict[str, Any]:
            await asyncio.sleep(5)
            return {}

        r = client(slow, turn_timeout_seconds=0.05).post(
            "/chat", json={"message": "go"}, headers=AUTH
        )
        assert r.status_code == 504
