"""One synthetic A2A v1.0 SendMessage to a facade, using the official a2a-sdk client.

Runs INSIDE a facade pod (``task a2a:send``) so the bearer token is read from the pod's own
environment and never crosses a command line or the operator's terminal. Prints the A2A
result and the tool ``run-...`` id if the facade surfaced one; never the token.

A failure is labelled by layer: ``our_call`` (this client could not reach or parse),
``facade`` (HTTP/JSON-RPC error returned by the facade) or ``ok``. There is no pass path:
success here proves the facade answered, not that containment held.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from containment_demo import invoke

A2A_VERSION = "1.0"
# The agent only reports a tool's run-... id when asked to return the tool result records
# verbatim, so the caller (not the facade) sends the same prompt invoke.py uses.
SYNTHETIC_TEXT = invoke.DEFAULT_PROMPT.format(demo_run_id="a2a-send")
TIMEOUT_SECONDS = 120.0


def summarise(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce SDK stream events (as dicts) to state, text, run ids and response id."""
    state: str | None = None
    texts: list[str] = []
    run_ids: list[str] = []
    response_id: str | None = None
    for event in events:
        task = event.get("task") or event
        status = task.get("status") or {}
        if status.get("state"):
            state = status["state"]
        for artifact in task.get("artifacts") or []:
            for part in artifact.get("parts") or []:
                if part.get("text"):
                    texts.append(part["text"])
            meta = artifact.get("metadata") or {}
            run_ids.extend(meta.get("tool_run_ids") or [])
            response_id = meta.get("downstream_response_id") or response_id
    return {
        "task_state": state,
        "text": "\n".join(texts),
        "tool_run_ids": sorted(set(run_ids)),
        "downstream_response_id": response_id,
    }


async def send(
    base: str,
    token: str,
    text: str = SYNTHETIC_TEXT,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    import httpx
    from a2a.client import A2ACardResolver, ClientConfig, create_client
    from a2a.helpers import new_text_message
    from a2a.types.a2a_pb2 import Role, SendMessageRequest
    from google.protobuf.json_format import MessageToDict  # type: ignore[import-untyped]

    headers = {"Authorization": f"Bearer {token}", "A2A-Version": A2A_VERSION}
    async with httpx.AsyncClient(
        headers=headers, timeout=httpx.Timeout(timeout), follow_redirects=False
    ) as http:
        card = await A2ACardResolver(httpx_client=http, base_url=base).get_agent_card()
        client = await create_client(
            agent=card, client_config=ClientConfig(streaming=False, httpx_client=http)
        )
        request = SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))
        events = [MessageToDict(e) async for e in client.send_message(request)]
        await client.close()
    return {"layer": "ok", **summarise(events)}


def classify(exc: Exception) -> dict[str, Any]:
    """Label a client failure. The message is type + str only; the token is never in it."""
    name = type(exc).__name__
    text = str(exc)
    layer = "facade" if "JSON-RPC" in text or "HTTP" in text or "401" in text else "our_call"
    return {"layer": layer, "error_type": name, "error": text[:500]}


def main() -> int:
    token = os.environ.get("DEMO_A2A_TOKEN", "")
    port = os.environ.get("DEMO_A2A_LISTEN_PORT", "8080")
    if not token:
        print(json.dumps({"layer": "our_call", "error": "DEMO_A2A_TOKEN not set in this pod"}))
        return 2
    try:
        out = asyncio.run(send(f"http://127.0.0.1:{port}", token))
    except Exception as exc:
        out = classify(exc)
    print(json.dumps(out, indent=2))
    return 0 if out.get("layer") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
