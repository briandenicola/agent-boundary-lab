"""Demo UI guards. Offline: the invoker is a fake, so no SDK, credentials or network."""

from __future__ import annotations

import base64
import logging
from typing import Any

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from containment_demo import demo_ui, invoke

TOKEN = "t" * 24
FACADE_TOKEN = "f" * 24
SECRET_TEXT = "SECRET-PROMPT-SHOULD-NEVER-APPEAR"


def make_settings(**over: Any) -> demo_ui.UiSettings:
    base: dict[str, Any] = {
        "a2a_facade_url_audit": "http://a2a-facade-audit.ns.svc.cluster.local",
        "a2a_facade_url_enforced": "http://a2a-facade-enforced.ns.svc.cluster.local",
        "a2a_token": FACADE_TOKEN,
        "agent_name_audit": "agent-a",
        "agent_name_enforced": "agent-e",
        "ui_token": TOKEN,
        "run_label": "hosted",
    }
    base.update(over)
    return demo_ui.UiSettings(**base)


class FakeResult:
    def __init__(self, record: dict[str, Any]) -> None:
        self._record = record
        self.transport_ok = record["transport_ok"]

    def as_dict(self) -> dict[str, Any]:
        return self._record


def record(**over: Any) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "demo_run_id": "x",
        "agent_name": "agent-a",
        "transport_ok": True,
        "transport_error_category": None,
        "transport_detail": None,
        "response_status": "completed",
        "determination": "pass",  # a lying record must not leak into the view
        "results": [
            {
                "tool_name": "get_servicing_policy",
                "attempted": True,
                "succeeded": True,
                "error_category": None,
                "http_status": 200,
                "destination_host": "ok.example",
            },
            {
                "tool_name": "send_to_external_processor",
                "attempted": True,
                "succeeded": False,
                "error_category": "http",
                "http_status": 403,
                "destination_host": "denied.example",
            },
        ],
    }
    rec.update(over)
    return rec


class Invoker:
    def __init__(self, rec: dict[str, Any] | None = None) -> None:
        self.rec = rec or record()
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kw: Any) -> FakeResult:
        self.calls.append(kw)
        return FakeResult({**self.rec, "demo_run_id": kw["demo_run_id"]})


def client(invoker: Invoker | None = None, **over: Any) -> tuple[TestClient, Invoker]:
    inv = invoker or Invoker()
    return TestClient(demo_ui.create_app(make_settings(**over), invoker=inv)), inv


AUTH = {"Authorization": f"Bearer {TOKEN}", "X-Demo-UI": "1"}


# --- authentication ---------------------------------------------------------------------


def test_run_requires_auth() -> None:
    c, inv = client()
    assert c.post("/run/audit", headers={"X-Demo-UI": "1"}).status_code == 401
    bad = {"Authorization": "Bearer wrong-wrong-wrong-wrong", "X-Demo-UI": "1"}
    assert c.post("/run/audit", headers=bad).status_code == 401
    assert inv.calls == []


def test_page_requires_auth_and_basic_works() -> None:
    c, _ = client()
    assert c.get("/").status_code == 401
    basic = base64.b64encode(f"demo:{TOKEN}".encode()).decode()
    assert c.get("/", headers={"Authorization": f"Basic {basic}"}).status_code == 200


def test_healthz_is_open() -> None:
    c, _ = client()
    assert c.get("/healthz").status_code == 200


def test_post_without_csrf_header_is_rejected() -> None:
    c, inv = client()
    r = c.post("/run/audit", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 403
    assert inv.calls == []


# --- no arbitrary destination -----------------------------------------------------------


@pytest.mark.parametrize("slot", ["https://evil.example", "other", "agent-a", "AUDIT"])
def test_unknown_slot_rejected(slot: str) -> None:
    c, inv = client()
    assert c.post(f"/run/{slot}", headers=AUTH).status_code == 404
    assert inv.calls == []


def test_slots_map_to_configured_names_and_facades() -> None:
    c, inv = client()
    c.post("/run/audit", headers=AUTH)
    c.post("/run/enforced", headers=AUTH)
    assert [k["agent_name"] for k in inv.calls] == ["agent-a", "agent-e"]
    assert [k["base_url"] for k in inv.calls] == [
        "http://a2a-facade-audit.ns.svc.cluster.local",
        "http://a2a-facade-enforced.ns.svc.cluster.local",
    ]
    assert all(k["token"] == FACADE_TOKEN for k in inv.calls)


# --- determination and honesty ----------------------------------------------------------


def test_determination_is_always_inconclusive_never_pass() -> None:
    c, _ = client()
    body = c.post("/run/audit", headers=AUTH).json()
    assert body["determination"] == invoke.DETERMINATION
    assert "pass" not in str(body["determination"]).lower()
    page = c.get("/", headers=AUTH).text.lower()
    assert "inconclusive-without-platform-evidence" in page
    assert ">pass<" not in page


def test_denied_tool_is_a_classified_failure_not_a_block() -> None:
    c, _ = client()
    tools = c.post("/run/enforced", headers=AUTH).json()["tools"]
    denied = next(t for t in tools if t["tool_name"] == "send_to_external_processor")
    assert denied["error_category"] == "http"
    assert denied["succeeded"] is False
    assert "blocked" not in str(denied).lower()


def test_transport_failure_is_labelled_as_our_call() -> None:
    inv = Invoker(
        record(transport_ok=False, transport_error_category="dns", transport_detail="x", results=[])
    )
    c, _ = client(inv)
    body = c.post("/run/audit", headers=AUTH).json()
    assert body["our_call"]["ok"] is False
    assert body["our_call"]["error_category"] == "dns"
    assert "OUR CALL" in c.get("/", headers=AUTH).text


def test_platform_evidence_is_declared_not_joined() -> None:
    c, _ = client()
    text = c.post("/run/audit", headers=AUTH).json()["platform_evidence"]
    assert "not read by this UI" in text
    assert "OperationId does not" in text
    assert "no telemetry field joins" not in text  # the stale GATE 0 claim


def test_run_label_is_shown_and_required() -> None:
    c, _ = client(run_label="local")
    assert c.post("/run/audit", headers=AUTH).json()["run_label"] == "local"
    with pytest.raises(ValidationError):
        make_settings(run_label=None)


# --- secrets and logs -------------------------------------------------------------------


def test_no_prompt_or_token_in_response_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    inv = Invoker(record(transport_detail=None))
    c, _ = client(inv)
    with caplog.at_level(logging.DEBUG):
        r = c.post("/run/audit", headers=AUTH)
        page = c.get("/", headers=AUTH)
    blob = r.text + page.text + caplog.text
    assert TOKEN not in blob
    assert FACADE_TOKEN not in blob
    assert SECRET_TEXT not in blob
    assert "prompt" not in inv.calls[0]
    assert "Authorization" not in caplog.text


def test_view_drops_unknown_fields_from_the_record() -> None:
    rec = record()
    rec["response_text"] = SECRET_TEXT
    c, _ = client(Invoker(rec))
    assert SECRET_TEXT not in c.post("/run/audit", headers=AUTH).text


# --- settings ---------------------------------------------------------------------------


def test_short_token_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(ui_token="short")


def test_bad_agent_name_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(agent_name_audit="a/../b")
    with pytest.raises(ValidationError):
        make_settings(a2a_facade_url_audit="http://10.0.0.5")
    with pytest.raises(ValidationError):
        make_settings(a2a_facade_url_enforced="ftp://x.example")
    with pytest.raises(ValidationError):
        make_settings(a2a_facade_url_audit="http://x.example/?a=1")


def test_token_not_in_repr() -> None:
    assert TOKEN not in repr(make_settings())
    assert FACADE_TOKEN not in repr(make_settings())


# --- which run id is shown (GATE 0: platform rows join on the TOOL's run id) --------------


def _with_tool_ids(first: str | None, second: str | None) -> dict[str, Any]:
    rec = record()
    rec["results"][0]["tool_run_id"] = first
    rec["results"][1]["tool_run_id"] = second
    return rec


def test_the_tool_run_id_is_shown_and_the_ui_id_is_labelled_ui_only() -> None:
    c, _ = client(Invoker(_with_tool_ids("run-abc", "run-abc")))
    body = c.post("/run/audit", headers=AUTH).json()
    assert body["tool_run_ids"] == ["run-abc"]
    assert body["ui_run_id"].startswith("ui-")
    assert "demo_run_id" not in body
    page = c.get("/", headers=AUTH).text
    assert "joins platform egress rows" in page
    assert "UI-only id (joins nothing)" in page


def test_missing_tool_run_id_is_stated_not_invented() -> None:
    c, _ = client(Invoker(_with_tool_ids(None, None)))
    body = c.post("/run/audit", headers=AUTH).json()
    assert body["tool_run_ids"] == []
    assert not any(v.startswith("ui-") for v in body["tool_run_ids"])
    assert "not available in the invoke result" in c.get("/", headers=AUTH).text


def test_disagreeing_tool_run_ids_are_both_shown() -> None:
    c, _ = client(Invoker(_with_tool_ids("run-a", "run-b")))
    assert c.post("/run/audit", headers=AUTH).json()["tool_run_ids"] == ["run-a", "run-b"]
