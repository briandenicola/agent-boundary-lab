"""The in-pod A2A client. Offline: pure reduction and classification, no network."""

from __future__ import annotations

import json

from containment_demo.a2a_facade import client

TASK = {
    "task": {
        "status": {"state": "TASK_STATE_COMPLETED"},
        "artifacts": [
            {
                "parts": [{"text": "hello"}],
                "metadata": {
                    "tool_run_ids": ["run-b", "run-a"],
                    "downstream_response_id": "resp_1",
                },
            }
        ],
    }
}


def test_summarise_surfaces_state_text_and_run_ids_only_from_the_reply():
    out = client.summarise([TASK])
    assert out["task_state"] == "TASK_STATE_COMPLETED"
    assert out["text"] == "hello"
    assert out["tool_run_ids"] == ["run-a", "run-b"]
    assert out["downstream_response_id"] == "resp_1"


def test_summarise_invents_no_run_id():
    bare = {"artifacts": [{"parts": [{"text": "x"}]}], "status": {"state": "TASK_STATE_COMPLETED"}}
    out = client.summarise([{"task": bare}])
    assert out["tool_run_ids"] == []
    assert out["downstream_response_id"] is None


def test_facade_errors_are_labelled_facade_and_local_ones_our_call():
    assert client.classify(RuntimeError("JSON-RPC Error -32603"))["layer"] == "facade"
    assert client.classify(OSError("connection refused"))["layer"] == "our_call"


def test_missing_token_fails_without_calling(monkeypatch, capsys):
    monkeypatch.delenv("DEMO_A2A_TOKEN", raising=False)
    assert client.main() == 2
    assert json.loads(capsys.readouterr().out)["layer"] == "our_call"


def test_token_never_printed(monkeypatch, capsys):
    secret = "s3cret-token-value-0123456789"
    monkeypatch.setenv("DEMO_A2A_TOKEN", secret)

    async def boom(base, token):
        raise RuntimeError("HTTP 401")

    monkeypatch.setattr(client, "send", boom)
    client.main()
    assert secret not in capsys.readouterr().out


def test_client_pins_a2a_v1():
    assert client.A2A_VERSION == "1.0"


def test_client_asks_for_verbatim_tool_records_so_run_ids_can_be_read():
    assert "verbatim" in client.SYNTHETIC_TEXT
    assert "get_servicing_policy" in client.SYNTHETIC_TEXT
    assert "{demo_run_id}" not in client.SYNTHETIC_TEXT
