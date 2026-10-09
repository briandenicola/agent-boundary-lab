"""The UI's A2A path. Offline: a fake sender stands in for the façade."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from containment_demo import invoke, ui_a2a

RUN = "run-0123abcd-0123-0123-0123-0123456789ab"
OK = {
    "tool_name": "get_servicing_policy",
    "demo_run_id": RUN,
    "http_status": 200,
    "succeeded": True,
    "error_category": "none",
}
DENIED = {
    "tool_name": "send_to_external_processor",
    "demo_run_id": RUN,
    "http_status": 403,
    "succeeded": False,
    "error_category": "http_error",
}
SRC = Path(__file__).resolve().parents[2] / "src" / "containment_demo"


class Sender:
    def __init__(self, out: dict[str, Any] | Exception) -> None:
        self.out = out
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, base: str, token: str, **kw: Any) -> dict[str, Any]:
        self.calls.append({"base": base, "token": token, **kw})
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


def run(sender: Sender) -> ui_a2a.A2AInvocation:
    return ui_a2a.invoke_via_a2a(
        base_url="http://f.svc",
        token="t" * 20,
        agent_name="a",
        demo_run_id="ui-1",
        timeout_seconds=5,
        sender=sender,
    )


def completed(*records: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_state": "TASK_STATE_COMPLETED",
        "text": "\n".join(json.dumps(r) for r in records),
        "downstream_response_id": "caresp_1",
    }


def test_tool_outcomes_and_run_id_come_from_the_agents_own_records() -> None:
    res = run(Sender(completed(OK, DENIED)))
    d = res.as_dict()
    assert d["transport_ok"] is True
    assert d["response_status"] == "TASK_STATE_COMPLETED"
    assert d["response_id"] == "caresp_1"
    by = {r["tool_name"]: r for r in d["results"]}
    assert by["send_to_external_processor"]["http_status"] == 403
    assert by["send_to_external_processor"]["error_category"] == "http_error"
    assert {r["tool_run_id"] for r in d["results"]} == {RUN}


def test_the_ui_sends_the_verbatim_record_prompt_with_its_own_id() -> None:
    s = Sender(completed(OK, DENIED))
    run(s)
    assert "ui-1" in s.calls[0]["text"] and "verbatim" in s.calls[0]["text"]


def test_no_records_means_not_attempted_and_no_run_id() -> None:
    d = run(Sender({"task_state": "TASK_STATE_COMPLETED", "text": "no json here"})).as_dict()
    assert all(r["attempted"] is False and r["tool_run_id"] is None for r in d["results"])


def test_a_failed_task_is_our_facade_leg_not_egress() -> None:
    res = run(Sender({"task_state": "TASK_STATE_FAILED", "text": json.dumps(OK)}))
    assert res.transport_ok is False
    assert res.transport_error_category == "a2a_task_not_completed"
    assert "says nothing about egress" in (res.transport_detail or "")
    assert all(not o.attempted for o in res.outcomes.values())


def test_client_side_and_facade_errors_are_labelled_apart() -> None:
    ours = run(Sender(OSError("connection refused")))
    theirs = run(Sender(RuntimeError("JSON-RPC Error -32603")))
    assert ours.transport_error_category == "a2a_our_call"
    assert "this UI's own call" in (ours.transport_detail or "")
    assert theirs.transport_error_category == "a2a_facade"
    assert "the façade returned an error" in (theirs.transport_detail or "")


def test_determination_is_never_a_pass() -> None:
    assert run(Sender(completed(OK, DENIED))).as_dict()["determination"] == invoke.DETERMINATION


@pytest.mark.parametrize(
    "bad", ["http://10.1.2.3", "http://[::1]", "ftp://x.y", "http://u:p@x.y", "x"]
)
def test_facade_url_must_be_a_dns_http_url(bad: str) -> None:
    with pytest.raises(ValueError):
        ui_a2a.validate_base_url(bad)


def test_ui_side_imports_no_azure_sdk() -> None:
    for name in ("ui_a2a.py", "demo_ui.py"):
        tree = ast.parse((SRC / name).read_text())
        mods = [
            n.module if isinstance(n, ast.ImportFrom) else a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.Import | ast.ImportFrom)
            for a in (n.names if isinstance(n, ast.Import) else [None])
        ]
        assert not [m for m in mods if m and m.split(".")[0] == "azure"], name


ROOT = SRC.parents[1]


def test_ui_manifest_reaches_facades_by_dns_with_the_token_from_the_secret() -> None:
    dep = (ROOT / "deploy/kustomize/demo-ui/deployment.yaml").read_text()
    assert "DEMO_A2A_FACADE_URL_AUDIT" in dep and "svc.cluster.local" in dep
    assert "secretKeyRef" in dep and "name: a2a-facade-config" in dep
    assert "DEMO_FOUNDRY" not in dep
    import re

    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", dep)


def test_ui_image_has_no_azure_sdk_and_caps_protobuf() -> None:
    docker = (ROOT / "Dockerfile.demo-ui").read_text()
    assert "azure" not in docker.replace("azurecr", "")
    assert '"protobuf>=5.29.5,<7"' in docker and '"a2a-sdk==1.0.2"' in docker


def test_ui_default_path_is_a2a_not_a_direct_foundry_call() -> None:
    src = (SRC / "demo_ui.py").read_text()
    assert "ui_a2a.invoke_via_a2a" in src
    assert "invoke.invoke_agent" not in src
