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
INGRESS_AUTH = {"X-Demo-UI": "1", "X-Auth-Request-Email": "allowed.user@contoso.com"}


class TestChat:
    def test_requires_auth(self) -> None:
        assert client().post("/chat", json={"message": "hi"}).status_code == 401
        assert client().get("/").status_code == 401
        assert client().get("/flow").status_code == 401

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

    def test_websocket_turn_shows_reply_tools_and_run_id(self) -> None:
        with client().websocket_connect("/ws", headers={"Authorization": f"Bearer {TOKEN}"}) as ws:
            ws.send_json({"message": "go"})
            result = None
            for _ in range(8):
                msg = ws.receive_json()
                if msg.get("event") == "result":
                    result = msg
                    break
            assert result is not None
            body = result["data"]
            assert body["reply"] == "done"
            assert body["tool_run_ids"] == [RUN_ID]
            assert body["tool_results"][0]["tool"] == "ask_audit_agent"

    def test_websocket_requires_auth(self) -> None:
        with pytest.raises(Exception):
            with client().websocket_connect("/ws"):
                pass

    def test_bad_messages_rejected(self) -> None:
        for payload in ({"message": ""}, {"message": "x" * 2000}, {"nope": 1}, {"message": 3}):
            assert client().post("/chat", json=payload, headers=AUTH).status_code == 400

    def test_page_states_the_limits(self) -> None:
        text = client().get("/", headers={"Authorization": f"Bearer {TOKEN}"}).text
        assert "Run label" in text
        assert "Model" in text
        assert "Flow diagram" in text
        assert "Run both tools in order" in text
        assert "working (local model" in text

    def test_page_shows_diagnostics_links_when_configured(self) -> None:
        c = client(
            diagnostics_workbook_url="https://portal.azure.com/#blade/Workbook",
            diagnostics_logs_url="https://portal.azure.com/#blade/Logs",
            diagnostics_app_insights_url="https://portal.azure.com/#blade/AppInsights",
        )
        text = c.get("/", headers={"Authorization": f"Bearer {TOKEN}"}).text
        assert "Diagnostics" in text
        assert "Evidence workbook" in text
        assert "Log Analytics" in text
        assert "App Insights" in text

    def test_flow_page_shows_end_to_end_diagram(self) -> None:
        text = client().get("/flow", headers={"Authorization": f"Bearer {TOKEN}"}).text
        assert "End-to-end flow" in text
        assert "A2A facade (audit/enforced slot)" in text
        assert "Foundry hosted agent" in text

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

    def test_ingress_oidc_mode_requires_ingress_identity_headers(self) -> None:
        c = client(auth_mode="ingress_oidc")
        assert c.get("/").status_code == 401
        assert c.get("/flow").status_code == 401
        assert (
            c.post("/chat", json={"message": "go"}, headers={"X-Demo-UI": "1"}).status_code == 401
        )
        with pytest.raises(Exception):
            with c.websocket_connect("/ws"):
                pass

    def test_ingress_oidc_mode_uses_ingress_actor_alias(self) -> None:
        c = client(auth_mode="ingress_oidc")
        r = c.post("/chat", json={"message": "go"}, headers=INGRESS_AUTH)
        assert r.status_code == 200
        assert r.json()["actor_alias"] == "allowed.user-contoso.com"
        page = c.get("/", headers={"X-Auth-Request-Email": "allowed.user@contoso.com"})
        assert 'value="allowed.user-contoso.com"' in page.text
        assert "/oauth2/sign_out?rd=%2F" in page.text
        flow = c.get("/flow", headers={"X-Auth-Request-Email": "allowed.user@contoso.com"})
        assert "/oauth2/sign_out?rd=%2F" in flow.text

    def test_ingress_oidc_mode_rejects_manual_actor_alias_override(self) -> None:
        c = client(auth_mode="ingress_oidc")
        r = c.post(
            "/chat",
            json={"message": "go", "actor_alias": "someone-else"},
            headers=INGRESS_AUTH,
        )
        assert r.status_code == 400

    def test_ingress_oidc_websocket_uses_ingress_actor_alias(self) -> None:
        c = client(auth_mode="ingress_oidc")
        with c.websocket_connect(
            "/ws", headers={"X-Auth-Request-Email": "allowed.user@contoso.com"}
        ) as ws:
            ws.send_json({"message": "go"})
            result = None
            for _ in range(8):
                msg = ws.receive_json()
                if msg.get("event") == "result":
                    result = msg
                    break
            assert result is not None
            assert result["data"]["actor_alias"] == "allowed.user-contoso.com"

    def test_ingress_oidc_websocket_rejects_manual_actor_alias_override(self) -> None:
        c = client(auth_mode="ingress_oidc")
        with c.websocket_connect(
            "/ws", headers={"X-Auth-Request-Email": "allowed.user@contoso.com"}
        ) as ws:
            ws.send_json({"message": "go", "actor_alias": "someone-else"})
            msg = ws.receive_json()
            assert msg["event"] == "error"
            assert msg["status"] == 400

    def test_legacy_mode_page_does_not_show_unspecified_actor_placeholder(self) -> None:
        text = client().get("/", headers={"Authorization": f"Bearer {TOKEN}"}).text
        assert "unspecified-actor" not in text
        assert "/oauth2/sign_out" not in text


def _outcome(tool_name: str, http_status: int | None, **extra: Any) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "attempted": True,
        "http_status": http_status,
        "destination_host": "policy.example.com",
        "tool_run_id": RUN_ID,
        **extra,
    }


def _responder_with_outcomes(outcomes: list[dict[str, Any]]) -> Any:
    async def responder(settings: HarnessSettings, message: str) -> dict[str, Any]:
        return {
            "reply": "done",
            "tool_results": [
                {
                    "tool": "ask_audit_agent",
                    "result": {
                        "slot": "audit",
                        "tool_run_ids": [RUN_ID],
                        "tool_outcomes": outcomes,
                    },
                }
            ],
        }

    return responder


OID = "8bbab162-0743-444c-b305-fed34bab43fb"


class TestActorOutcomeSurfacing:
    """WP-3 (issue #4): actor alias, policy authorization, and containment
    determination must each be visible and must stay separate from one another."""

    def test_default_actor_alias_is_used_when_not_supplied(self) -> None:
        r = client().post("/chat", json={"message": "go"}, headers=AUTH)
        assert r.json()["actor_alias"] == chat.DEFAULT_ACTOR_ALIAS

    def test_actor_alias_is_echoed_back(self) -> None:
        r = client().post(
            "/chat", json={"message": "go", "actor_alias": "allowed-tester"}, headers=AUTH
        )
        assert r.json()["actor_alias"] == "allowed-tester"

    @pytest.mark.parametrize("bad_alias", ["", "has space", "x" * 65, "emoji🙂"])
    def test_invalid_actor_alias_rejected(self, bad_alias: str) -> None:
        r = client().post("/chat", json={"message": "go", "actor_alias": bad_alias}, headers=AUTH)
        assert r.status_code == 400

    @staticmethod
    def _access(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        r = client(_responder_with_outcomes(outcomes)).post(
            "/chat", json={"message": "go"}, headers=AUTH
        )
        return r.json()["policy_access"][0]

    def test_policy_allowed_needs_200_and_a_verified_user_object_id(self) -> None:
        access = self._access(
            [
                _outcome(
                    "get_servicing_policy", 200, user_token_forwarded=True, user_object_id=OID
                ),
                _outcome("send_to_external_processor", 403),
            ]
        )
        assert access["status"] == "allowed"
        assert access["label"] == "allowed: policy API verified your token"
        assert access["determination"] == "identity_only"

    def test_200_record_goes_through_outcome_from_record_to_allowed(self) -> None:
        from containment_demo.invoke import outcome_from_record

        record = {
            "tool_name": "get_servicing_policy",
            "http_status": 200,
            "succeeded": True,
            "error_category": "none",
            "destination_host": "policy.example.com",
            "demo_run_id": RUN_ID,
            "user_token_forwarded": True,
            "result": {"user_object_id": OID, "policy": {"x": 1}},
        }
        outcome = outcome_from_record(record).as_dict()
        assert outcome["user_object_id"] == OID
        entry = chat._access_entry("audit", {"tool_outcomes": [outcome]})
        assert entry["status"] == "allowed"

    def test_bare_200_is_not_reported_as_allowed(self) -> None:
        access = self._access([_outcome("get_servicing_policy", 200, user_token_forwarded=True)])
        assert access["status"] == "no_evidence"

    def test_policy_denied_shows_who_what_why_and_kql(self) -> None:
        access = self._access(
            [
                _outcome(
                    "get_servicing_policy",
                    403,
                    user_token_forwarded=True,
                    policy_error="user_not_authorized",
                    user_object_id=OID,
                )
            ]
        )
        assert access["status"] == "denied"
        assert access["user_object_id"] == OID
        assert access["error"] == "user_not_authorized"
        assert access["policy_api_host"] == "policy.example.com"
        assert RUN_ID in access["kql"]["receipt"]
        assert "ContainerAppConsoleLogs_CL" in access["kql"]["receipt"]
        assert "authorization_decision" in access["kql"]["receipt"]
        assert "served" in access["kql"]["receipt"]

    def test_unrelated_403_is_not_a_denial(self) -> None:
        access = self._access([_outcome("get_servicing_policy", 403, policy_error="other")])
        assert access["status"] == "no_evidence"

    def test_401_is_not_authenticated(self) -> None:
        access = self._access([_outcome("get_servicing_policy", 401)])
        assert access["status"] == "unauthenticated"

    def test_token_not_forwarded_is_stated_plainly(self) -> None:
        access = self._access([_outcome("get_servicing_policy", 200, user_token_forwarded=False)])
        assert access["status"] == "no_evidence"
        assert "did not reach the tool" in access["label"]

    def test_policy_status_is_no_evidence_when_not_attempted(self) -> None:
        r = client().post("/chat", json={"message": "go"}, headers=AUTH)
        assert r.json()["policy_access"] == []

    def test_containment_determination_never_derived_from_policy_denial(self) -> None:
        """A denied policy call must not change, weaken, or be confused with the
        containment determination -- they are reported side by side, unconditionally."""
        denied = _responder_with_outcomes(
            [_outcome("get_servicing_policy", 403, policy_error="user_not_authorized")]
        )
        authorized = _responder_with_outcomes([_outcome("get_servicing_policy", 200)])
        r_denied = client(denied).post("/chat", json={"message": "go"}, headers=AUTH).json()
        r_ok = client(authorized).post("/chat", json={"message": "go"}, headers=AUTH).json()
        assert r_denied["determination"] == r_ok["determination"]
        assert r_denied["determination"].startswith("inconclusive")
        assert "pass" not in r_denied["determination"].lower()

    def test_policy_status_never_reads_the_containment_tool(self) -> None:
        """send_to_external_processor's status must never set the policy label."""
        access = self._access([_outcome("send_to_external_processor", 200)])
        assert access["status"] == "no_evidence"


def test_model_call_logging_records_sizes_never_content(caplog: pytest.LogCaptureFixture) -> None:
    from google.genai import types

    secret = "SECRET-PAYLOAD-TEXT"
    request = type("Req", (), {})()
    request.config = types.GenerateContentConfig(system_instruction="sys-instruction")
    request.contents = [
        types.Content(role="user", parts=[types.Part(text=secret)]),
        types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="ask_audit_agent", response={"k": secret}
                    )
                )
            ],
        ),
    ]
    with caplog.at_level("INFO", logger=agent.logger.name):
        agent.log_model_request(None, request)
    assert "user:text:" in caplog.text
    assert "user:function_response:" in caplog.text
    assert "system_chars=15" in caplog.text
    assert secret not in caplog.text


OBO = {
    "obo_tenant_id": "00000000-0000-4000-8000-000000000001",
    "obo_client_id": "00000000-0000-4000-8000-000000000002",
    "obo_client_secret": "synthetic-secret-value",
    "obo_scope": "api://synthetic-policy/policy.read",
}


class TestOnBehalfOf:
    def test_obo_settings_are_all_or_none(self) -> None:
        assert make_settings().obo_enabled is False
        assert make_settings(**OBO).obo_enabled is True
        with pytest.raises(ValidationError):
            make_settings(obo_tenant_id=OBO["obo_tenant_id"])

    def test_obo_failure_returns_identity_error_and_skips_the_turn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from containment_demo.harness import obo

        def fail(settings: Any, assertion: str) -> str:
            raise obo.OboError("invalid_grant")

        monkeypatch.setattr(obo, "_exchange", fail)
        responder = FakeResponder()
        c = client(responder, auth_mode="ingress_oidc", **OBO)
        r = c.post(
            "/chat",
            json={"message": "go"},
            headers={**INGRESS_AUTH, "X-Auth-Request-Access-Token": "ingress-secret"},
        )
        assert r.status_code == 401
        assert r.json()["source"] == "identity"
        assert "invalid_grant" in r.json()["error"]
        assert "ingress-secret" not in r.text
        assert not responder.messages

    def test_obo_token_reaches_the_responder_context_and_is_not_returned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from containment_demo.harness import obo

        monkeypatch.setattr(obo, "_exchange", lambda settings, assertion: "obo-" + assertion)
        seen: list[str | None] = []

        async def responder(settings: HarnessSettings, message: str) -> dict[str, Any]:
            seen.append(obo.current_user_token.get())
            return {"reply": "ok", "tool_results": []}

        c = client(responder, auth_mode="ingress_oidc", **OBO)
        headers = {**INGRESS_AUTH, "X-Auth-Request-Access-Token": "ingress"}
        r = c.post("/chat", json={"message": "go"}, headers=headers)
        assert r.status_code == 200
        assert seen == ["obo-ingress"]
        assert "obo-ingress" not in r.text
        with c.websocket_connect("/ws", headers=headers) as ws:
            ws.send_json({"message": "go"})
            while ws.receive_json()["event"] != "result":
                pass
        assert seen == ["obo-ingress", "obo-ingress"]
        assert obo.current_user_token.get() is None

    def test_missing_ingress_access_token_is_an_identity_error(self) -> None:
        c = client(auth_mode="ingress_oidc", **OBO)
        r = c.post("/chat", json={"message": "go"}, headers=INGRESS_AUTH)
        assert r.status_code == 401
        assert "ingress_access_token_missing" in r.json()["error"]

    def test_call_slot_passes_user_token_only_when_present(self) -> None:
        from containment_demo.harness import obo

        seen: list[dict[str, Any]] = []

        async def sender(base: str, token: str, **kwargs: Any) -> dict[str, Any]:
            seen.append(kwargs)
            return {"task_state": "TASK_STATE_COMPLETED", "text": ""}

        s = make_settings()
        asyncio.run(agent.call_slot(s, "audit", sender))
        reset = obo.current_user_token.set("t")
        try:
            asyncio.run(agent.call_slot(s, "audit", sender))
        finally:
            obo.current_user_token.reset(reset)
        assert "user_token" not in seen[0]
        assert seen[1]["user_token"] == "t"
