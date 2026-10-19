"""The in-pod A2A client. Offline: pure reduction and classification, no network."""

from __future__ import annotations

import json

import pytest

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


def test_failed_task_preserves_the_safe_status_message():
    message = (
        "The call from the façade to the hosted agent failed: http_error (HTTP 500). "
        "This says nothing about the agent's own egress."
    )
    out = client.summarise(
        [
            {
                "task": {
                    "status": {
                        "state": "TASK_STATE_FAILED",
                        "message": {"parts": [{"text": message}]},
                    }
                }
            }
        ]
    )
    assert out["task_state"] == "TASK_STATE_FAILED"
    assert out["text"] == message
    assert out["status_message"] == message
    assert out["tool_run_ids"] == []
    assert out["downstream_response_id"] is None


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("TASK_STATE_COMPLETED", 0),
        ("TASK_STATE_FAILED", 1),
        ("TASK_STATE_REJECTED", 1),
        ("TASK_STATE_CANCELED", 1),
        ("TASK_STATE_WORKING", 1),
        (None, 1),
    ],
)
def test_main_requires_a_completed_task(monkeypatch, capsys, state, expected):
    monkeypatch.setenv("DEMO_A2A_TOKEN", "synthetic-client-secret")

    async def reply(base, token):
        return {"layer": "ok", "task_state": state}

    monkeypatch.setattr(client, "send", reply)
    assert client.main() == expected
    assert json.loads(capsys.readouterr().out)["task_state"] == state


@pytest.mark.parametrize(
    ("state", "layer"),
    [("TASK_STATE_COMPLETED", "ok"), ("TASK_STATE_FAILED", "task")],
)
async def test_sdk_response_keeps_failed_task_distinct_from_transport_success(
    monkeypatch, state, layer
):
    import a2a.client
    from a2a.types import a2a_pb2

    closed = []

    class FakeClient:
        async def send_message(self, request):
            yield a2a_pb2.SendMessageResponse(
                task=a2a_pb2.Task(
                    status=a2a_pb2.TaskStatus(
                        state=a2a_pb2.TaskState.Value(state),
                        message=a2a_pb2.Message(
                            parts=[a2a_pb2.Part(text="Synthetic task status (HTTP 500)")]
                        ),
                    )
                )
            )

        async def close(self):
            closed.append(True)

    async def card(self):
        return object()

    async def create_client(**kwargs):
        return FakeClient()

    monkeypatch.setattr(a2a.client.A2ACardResolver, "get_agent_card", card)
    monkeypatch.setattr(a2a.client, "create_client", create_client)
    out = await client.send("http://127.0.0.1:12345", "synthetic-token")
    assert out["layer"] == layer
    assert out["task_state"] == state
    assert out["status_message"] == "Synthetic task status (HTTP 500)"
    assert closed == [True]


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
