"""The demo UI's invocation path: an A2A SendMessage to a slot's façade.

Hosted agents are invoked through Responses; the façade exposes them as A2A, and this UI
calls the façade as an A2A client. It does not call Foundry and imports no Azure SDK.
The agent's reported tool records are parsed with the same ``invoke`` functions the CLI
uses, so classification has one vocabulary.

There is no pass path: :data:`containment_demo.invoke.DETERMINATION` is the only
determination, and a failure is labelled by whose call failed (this UI's call to the
façade, the façade itself, or the façade's call to the agent) rather than read as egress
evidence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from containment_demo import invoke
from containment_demo.a2a_facade import client as a2a_client

COMPLETED = "TASK_STATE_COMPLETED"

Sender = Callable[..., Awaitable[dict[str, Any]]]


def validate_base_url(value: str) -> str:
    """A façade base URL from startup config: http(s), a DNS name (never an IP), no query."""
    import ipaddress

    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.scheme not in {"http", "https"} or not host or parts.query or parts.fragment:
        raise ValueError("must be an http(s) URL with a host and no query or fragment")
    if parts.username or parts.password:
        raise ValueError("must not carry credentials")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return value.rstrip("/")
    raise ValueError("must use a DNS name, not an IP literal")


@dataclass(frozen=True)
class A2AInvocation:
    """Quacks like ``invoke.InvocationResult`` for the view, plus the A2A facts."""

    demo_run_id: str
    agent_name: str
    transport_ok: bool
    transport_error_category: str | None
    transport_detail: str | None
    task_state: str | None
    response_id: str | None
    outcomes: dict[str, invoke.ToolOutcome] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "demo_run_id": self.demo_run_id,
            "agent_name": self.agent_name,
            "transport_ok": self.transport_ok,
            "transport_error_category": self.transport_error_category,
            "transport_detail": self.transport_detail,
            "response_status": self.task_state,
            "response_id": self.response_id,
            "determination": invoke.DETERMINATION,
            "results": [self.outcomes[name].as_dict() for name in invoke.TOOL_NAMES],
        }


def _failed(
    run_id: str, agent: str, category: str, detail: str, state: str | None = None
) -> A2AInvocation:
    return A2AInvocation(
        demo_run_id=run_id,
        agent_name=agent,
        transport_ok=False,
        transport_error_category=category,
        transport_detail=detail,
        task_state=state,
        response_id=None,
        outcomes={name: invoke._not_attempted(name) for name in invoke.TOOL_NAMES},
    )


def invoke_via_a2a(
    *,
    base_url: str,
    token: str,
    agent_name: str,
    demo_run_id: str,
    timeout_seconds: float,
    sender: Sender = a2a_client.send,
) -> A2AInvocation:
    """One A2A SendMessage to one façade. Blocking; call it from a worker thread."""
    text = invoke.DEFAULT_PROMPT.format(demo_run_id=demo_run_id)
    try:
        out = asyncio.run(
            asyncio.wait_for(
                sender(base_url, token, text=text, timeout=timeout_seconds),
                timeout=timeout_seconds + 5,
            )
        )
    except Exception as exc:
        info = a2a_client.classify(exc)
        who = (
            "the façade returned an error"
            if info["layer"] == "facade"
            else "this UI's own call to the façade failed"
        )
        return _failed(
            demo_run_id,
            agent_name,
            f"a2a_{info['layer']}",
            f"{invoke.sanitize(exc)}. {who}; it says nothing about egress.",
        )

    state = out.get("task_state")
    if state != COMPLETED:
        return _failed(
            demo_run_id,
            agent_name,
            "a2a_task_not_completed",
            f"The A2A task ended in {state}. The façade's call to the agent did not "
            "complete; it says nothing about egress.",
            state,
        )

    records = invoke.tool_records(invoke.extract_json_objects(out.get("text") or ""))
    return A2AInvocation(
        demo_run_id=demo_run_id,
        agent_name=agent_name,
        transport_ok=True,
        transport_error_category=None,
        transport_detail=None,
        task_state=state,
        response_id=out.get("downstream_response_id"),
        outcomes=invoke.build_outcomes(records),
    )
