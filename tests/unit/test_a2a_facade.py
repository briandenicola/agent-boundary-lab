"""The A2A façade. Offline: a fake AgentTarget behind the real a2a-sdk app, and a fake
Responses client behind the real adapter. No Foundry SDK, credentials or network."""

from __future__ import annotations

import ast
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from containment_demo.a2a_facade import core, server
from containment_demo.a2a_facade.core import (
    FacadeSettings,
    SharedTokenAuthenticator,
    TargetError,
    TargetReply,
)
from containment_demo.a2a_facade.target import ResponsesTarget

TOKEN = "t" * 32
PROMPT_TEXT = "SECRET-PROMPT-TEXT-123"
ANSWER_TEXT = "SECRET-ANSWER-TEXT-456"
PKG = Path(server.__file__).parent


def make_settings(**over: Any) -> FacadeSettings:
    kw: dict[str, Any] = {
        "foundry_account_name": "acct",
        "foundry_project_name": "proj",
        "a2a_target_agent_name": "containment-demo-audit",
        "a2a_public_url": "http://a2a-facade-audit.ns.svc.cluster.local",
        "a2a_token": TOKEN,
    }
    kw.update(over)
    return FacadeSettings(**kw)


class FakeTarget:
    def __init__(self, reply: TargetReply | Exception | None = None) -> None:
        self.seen: list[str] = []
        self.reply = reply or TargetReply(ANSWER_TEXT, "resp_1", ("run-abc",))

    async def send(self, text: str) -> TargetReply:
        self.seen.append(text)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def client_for(target: FakeTarget) -> TestClient:
    return TestClient(server.build_app(make_settings(), target))


AUTH = {"Authorization": f"Bearer {TOKEN}", "A2A-Version": "1.0"}


def rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}


def send_message(text: str) -> dict[str, Any]:
    return rpc(
        "SendMessage",
        {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"text": text}],
            }
        },
    )


# --- settings --------------------------------------------------------------------


class TestSettings:
    def test_short_token_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(a2a_token="short")

    @pytest.mark.parametrize("url", ["ftp://x", "http://x/?q=1", "http://u:p@x", "x"])
    def test_public_url_must_be_a_plain_absolute_http_url(self, url: str) -> None:
        with pytest.raises(ValidationError):
            make_settings(a2a_public_url=url)

    def test_agent_name_must_be_a_name_not_a_url(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(a2a_target_agent_name="https://evil.example/x")

    def test_endpoint_is_built_from_names_only(self) -> None:
        assert make_settings().endpoint == "https://acct.services.ai.azure.com/api/projects/proj"


# --- auth ------------------------------------------------------------------------


class TestAuth:
    @pytest.mark.parametrize(
        "headers",
        [{}, {"Authorization": "Bearer wrong-wrong-wrong-wrong"}, {"Authorization": TOKEN}],
    )
    def test_no_or_wrong_token_is_401_on_every_route(self, headers: dict[str, str]) -> None:
        c = client_for(FakeTarget())
        assert c.get("/.well-known/agent-card.json", headers=headers).status_code == 401
        assert c.post("/", json=send_message("x"), headers=headers).status_code == 401

    def test_right_token_reaches_the_card(self) -> None:
        r = client_for(FakeTarget()).get("/.well-known/agent-card.json", headers=AUTH)
        assert r.status_code == 200

    def test_healthz_is_open(self) -> None:
        assert client_for(FakeTarget()).get("/healthz").status_code == 200

    def test_unauthenticated_call_never_reaches_the_target(self) -> None:
        t = FakeTarget()
        client_for(t).post("/", json=send_message("x"))
        assert t.seen == []

    def test_comparison_is_constant_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[tuple[str, str]] = []
        real = core.hmac.compare_digest

        def spy(a: str, b: str) -> bool:
            calls.append((a, b))
            return real(a, b)

        monkeypatch.setattr(core.hmac, "compare_digest", spy)
        SharedTokenAuthenticator(core.SecretStr(TOKEN)).authenticate(f"Bearer {TOKEN}")
        assert calls

    def test_authenticator_is_a_replaceable_seam(self) -> None:
        class Only:
            def authenticate(self, header: str) -> core.Principal | None:
                return core.Principal("entra-oid") if header == "Bearer x" else None

        app = server.build_app(make_settings(), FakeTarget(), authenticator=Only())
        c = TestClient(app)
        assert (
            c.get("/.well-known/agent-card.json", headers={"Authorization": "Bearer x"}).status_code
            == 200
        )
        assert c.get("/.well-known/agent-card.json", headers=AUTH).status_code == 401


# --- card ------------------------------------------------------------------------


def test_card_is_jsonrpc_1_0_only_with_streaming_off_and_no_native_claim() -> None:
    card = client_for(FakeTarget()).get("/.well-known/agent-card.json", headers=AUTH).json()
    ifaces = card["supportedInterfaces"]
    assert [(i["protocolBinding"], i["protocolVersion"]) for i in ifaces] == [("JSONRPC", "1.0")]
    assert ifaces[0]["url"] == "http://a2a-facade-audit.ns.svc.cluster.local"
    assert card["capabilities"].get("streaming", False) is False
    assert "Responses protocol" in card["description"]
    assert "native" not in card["description"].lower()


# --- SendMessage -----------------------------------------------------------------


class TestSendMessage:
    def test_text_goes_to_the_target_and_comes_back_as_artifact_and_message(self) -> None:
        t = FakeTarget()
        body = client_for(t).post("/", json=send_message(PROMPT_TEXT), headers=AUTH).json()
        task = body["result"]["task"]
        assert t.seen == [PROMPT_TEXT]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert task["artifacts"][0]["parts"][0]["text"] == ANSWER_TEXT
        assert task["status"]["message"]["parts"][0]["text"] == ANSWER_TEXT

    def test_tool_run_id_and_downstream_response_id_are_surfaced_when_reported(self) -> None:
        task = (
            client_for(FakeTarget())
            .post("/", json=send_message("hi"), headers=AUTH)
            .json()["result"]["task"]
        )
        meta = task["artifacts"][0]["metadata"]
        assert meta["tool_run_ids"] == ["run-abc"]
        assert meta["downstream_response_id"] == "resp_1"

    def test_no_tool_run_id_is_invented_when_the_agent_reported_none(self) -> None:
        t = FakeTarget(TargetReply("ok", "resp_2", ()))
        task = (
            client_for(t).post("/", json=send_message("hi"), headers=AUTH).json()["result"]["task"]
        )
        assert task["artifacts"][0]["metadata"]["tool_run_ids"] == []

    @pytest.mark.parametrize("text", ["", "   ", "x" * 8001])
    def test_empty_or_oversized_input_is_an_error_and_not_forwarded(self, text: str) -> None:
        t = FakeTarget()
        body = client_for(t).post("/", json=send_message(text), headers=AUTH).json()
        assert "error" in body or body["result"]["task"]["status"]["state"] != (
            "TASK_STATE_COMPLETED"
        )
        assert t.seen == []

    def test_downstream_failure_is_a_failed_task_labelled_as_our_call(self) -> None:
        t = FakeTarget(TargetError("timeout", None))
        task = (
            client_for(t)
            .post("/", json=send_message(PROMPT_TEXT), headers=AUTH)
            .json()["result"]["task"]
        )
        assert task["status"]["state"] == "TASK_STATE_FAILED"
        msg = task["status"]["message"]["parts"][0]["text"]
        assert "timeout" in msg and "façade" in msg and "egress" in msg
        assert PROMPT_TEXT not in json.dumps(task["status"])

    def test_streaming_method_is_not_available(self) -> None:
        body = client_for(FakeTarget()).post(
            "/", json={**send_message("x"), "method": "SendStreamingMessage"}, headers=AUTH
        )
        assert "error" in body.json() or body.status_code >= 400


class TestCancel:
    def test_cancel_returns_a_clear_unsupported_error(self) -> None:
        import asyncio

        from a2a.utils.errors import UnsupportedOperationError

        ex = server.FacadeExecutor(FakeTarget())
        with pytest.raises(UnsupportedOperationError, match="not supported"):
            asyncio.run(ex.cancel(None, None))  # type: ignore[arg-type]

    def test_cancel_over_the_wire_is_not_success(self) -> None:
        c = client_for(FakeTarget())
        tid = c.post("/", json=send_message("hi"), headers=AUTH).json()["result"]["task"]["id"]
        body = c.post("/", json=rpc("CancelTask", {"id": tid}), headers=AUTH).json()
        assert "error" in body


# --- logging ---------------------------------------------------------------------


def test_logs_carry_ids_and_never_content_or_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # DEBUG is deliberately not used: a2a-sdk's own DEBUG logs dump request bodies, and
    # __main__ never enables DEBUG.
    caplog.set_level(logging.INFO)
    c = client_for(FakeTarget())
    c.post("/", json=send_message(PROMPT_TEXT), headers=AUTH)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "resp_1" in text and "run-abc" in text and "shared-token" in text
    for forbidden in (PROMPT_TEXT, ANSWER_TEXT, TOKEN, "Bearer"):
        assert forbidden not in text


# --- the A2A side imports no Foundry ---------------------------------------------


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            out.add(node.module or "")
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


@pytest.mark.parametrize("module", ["server.py", "core.py"])
def test_a2a_side_imports_no_foundry_sdk_and_not_the_adapter(module: str) -> None:
    banned = ("azure", "openai", "containment_demo.invoke", "containment_demo.a2a_facade.target")
    bad = [i for i in _imports(PKG / module) if i.startswith(banned)]
    assert bad == []


def test_only_the_target_module_references_foundry_specifics() -> None:
    for path in PKG.glob("*.py"):
        if path.name == "target.py":
            continue
        src = path.read_text()
        assert "ai.azure.com/.default" not in src and "agent_reference" not in src, path.name


# --- the adapter -----------------------------------------------------------------


class FakeResponses:
    def __init__(self, payload: Any = None, exc: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payload = payload
        self._exc = exc
        self.responses = self

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        if self._exc:
            raise self._exc
        return self._payload


def target_with(fake: FakeResponses) -> ResponsesTarget:
    return ResponsesTarget(endpoint="https://e", agent_name="a", timeout_seconds=5, client=fake)


class TestResponsesTarget:
    async def test_store_is_false_and_the_call_is_bounded(self) -> None:
        fake = FakeResponses({"id": "resp_9", "output_text": "hello"})
        reply = await target_with(fake).send("question")
        (call,) = fake.calls
        assert call["store"] is False
        assert call["input"] == "question" and call["timeout"] == 5
        assert (reply.text, reply.response_id) == ("hello", "resp_9")

    async def test_tool_run_id_comes_only_from_the_agents_own_record(self) -> None:
        record = json.dumps(
            {"tool_name": "get_servicing_policy", "demo_run_id": "run-abc", "succeeded": True}
        )
        fake = FakeResponses({"id": "r", "output_text": record})
        assert (await target_with(fake).send("q")).tool_run_ids == ("run-abc",)

    async def test_no_record_means_no_run_id(self) -> None:
        fake = FakeResponses({"id": "r", "output_text": "plain prose"})
        assert (await target_with(fake).send("q")).tool_run_ids == ()

    async def test_failure_is_classified_and_never_returned_as_a_reply(self) -> None:
        class ReadTimeout(Exception):
            pass

        fake = FakeResponses(exc=ReadTimeout("read timed out"))
        with pytest.raises(TargetError) as err:
            await target_with(fake).send("q")
        assert err.value.category == "timeout"
        assert "q" not in str(err.value)


# --- packaging and manifests ------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_pins_match_the_extra_and_cap_protobuf() -> None:
    import tomllib

    extra = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "optional-dependencies"
    ]["a2a-facade"]
    docker = (ROOT / "Dockerfile.a2a-facade").read_text()
    for dep in extra:
        assert f'"{dep}"' in docker, dep
    assert "protobuf>=5.29.5,<7" in docker


def test_the_facade_image_is_not_the_agent_image() -> None:
    docker = (ROOT / "Dockerfile.a2a-facade").read_text()
    assert "google-adk" not in docker.split("RUN uv pip", 1)[1]
    assert 'ENTRYPOINT ["python", "-m", "containment_demo.a2a_facade"]' in docker


def _overlay(slot: str) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(
        (ROOT / "deploy/kustomize/a2a-facade" / slot / "kustomization.yaml").read_text()
    )


def test_audit_and_enforced_overlays_differ_only_by_slot_and_target() -> None:
    a, e = _overlay("audit"), _overlay("enforced")
    norm = json.dumps(a, sort_keys=True)
    for token in ("audit", "AUDIT"):
        norm = norm.replace(token, "SLOT")
    other = json.dumps(e, sort_keys=True)
    for token in ("enforced", "ENFORCED"):
        other = other.replace(token, "SLOT")
    assert norm == other


def test_overlays_set_the_target_and_nothing_else_and_share_one_image_placeholder() -> None:
    base = (ROOT / "deploy/kustomize/a2a-facade/base/deployment.yaml").read_text()
    assert base.count("REPLACE_WITH_A2A_FACADE_IMAGE") == 1
    for slot in ("audit", "enforced"):
        text = (ROOT / "deploy/kustomize/a2a-facade" / slot / "kustomization.yaml").read_text()
        assert "IMAGE" not in text
        assert f"REPLACE_WITH_AGENT_NAME_{slot.upper()}" in text


def test_manifests_use_the_existing_identity_and_no_literal_secret_or_address() -> None:
    import re

    for path in (ROOT / "deploy/kustomize/a2a-facade").rglob("*.yaml"):
        text = path.read_text()
        assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text), path
        assert "DEMO_A2A_TOKEN" not in text, path
    dep = (ROOT / "deploy/kustomize/a2a-facade/base/deployment.yaml").read_text()
    assert "serviceAccountName: demo-ui" in dep
