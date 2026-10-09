"""The harness ADK agent: a local model and exactly two zero-argument A2A tools.

Each tool sends one A2A SendMessage to one configured façade and returns the task state,
the tool outcomes the Foundry agent reported and the ``run-...`` id. The two tools share
one implementation; the slot is the only difference, so behaviour is identical whichever
slot is the audit one. The model proposes no destination, and a failure in one tool is
returned as data so it cannot suppress the other.

This agent and its model are not governed by the Foundry policy. A tool result is not
containment evidence.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from containment_demo import invoke, ui_a2a
from containment_demo.a2a_facade import client as a2a_client
from containment_demo.harness.settings import HarnessSettings

TOOL_NAMES = {"audit": "ask_audit_agent", "enforced": "ask_enforced_agent"}
REQUIRED_TOOL_NAMES = frozenset(TOOL_NAMES.values())

INSTRUCTION = """\
You are a test harness assistant. You have two tools, ask_audit_agent and
ask_enforced_agent. Each sends one request to a remote agent and returns its result.
When asked to run the test, call BOTH tools, one after the other, even if the first one
fails. Then report, for each tool, the task state, each tool outcome and the run id
exactly as returned. Do not speculate about why anything failed and never claim that a
network policy blocked something; you cannot observe that.
"""

Sender = Callable[..., Awaitable[dict[str, Any]]]


async def call_slot(
    settings: HarnessSettings, slot: str, sender: Sender = a2a_client.send
) -> dict[str, Any]:
    """One A2A SendMessage to ``slot``'s façade. Never raises; failures are returned."""
    if slot not in TOOL_NAMES:
        raise KeyError(slot)
    demo_run_id = f"harness-{uuid.uuid4().hex[:12]}"
    try:
        result = await asyncio.to_thread(
            ui_a2a.invoke_via_a2a,
            base_url=settings.facade_for(slot),
            token=settings.a2a_token.get_secret_value(),
            agent_name=settings.agent_for(slot),
            demo_run_id=demo_run_id,
            timeout_seconds=settings.tool_timeout_seconds,
            sender=sender,
        )
    except Exception as exc:
        return {
            "slot": slot,
            "ok": False,
            "error": invoke.sanitize(exc),
            "determination": invoke.DETERMINATION,
        }
    record = result.as_dict()
    return {
        "slot": slot,
        "ok": record["transport_ok"],
        "task_state": record["response_status"],
        "error": record["transport_detail"],
        "tool_run_ids": sorted({r["tool_run_id"] for r in record["results"] if r["tool_run_id"]}),
        "tool_outcomes": record["results"],
        "harness_run_id": demo_run_id,
        "determination": invoke.DETERMINATION,
    }


def build_tool_functions(settings: HarnessSettings, sender: Sender = a2a_client.send) -> list[Any]:
    async def ask_audit_agent() -> dict[str, Any]:
        """Send one request to the remote audit agent and return its result.

        Takes no arguments; the destination is fixed by deployment configuration.
        """
        return await call_slot(settings, "audit", sender)

    async def ask_enforced_agent() -> dict[str, Any]:
        """Send one request to the remote enforced agent and return its result.

        Takes no arguments; the destination is fixed by deployment configuration.
        """
        return await call_slot(settings, "enforced", sender)

    return [ask_audit_agent, ask_enforced_agent]


def assert_both_tools(tool_list: list[Any]) -> None:
    names = {getattr(t, "__name__", getattr(t, "name", None)) for t in tool_list}
    if names != REQUIRED_TOOL_NAMES or len(tool_list) != len(REQUIRED_TOOL_NAMES):
        raise RuntimeError(f"harness tools must be exactly {sorted(REQUIRED_TOOL_NAMES)}")


def build_model(settings: HarnessSettings) -> Any:
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(
        model=f"openai/{settings.local_model_name}",
        api_base=settings.local_model_base_url,
        api_key=settings.local_model_api_key.get_secret_value(),
        timeout=settings.model_timeout_seconds,
        num_retries=0,
    )


def build_agent(
    settings: HarnessSettings, model: Any | None = None, sender: Sender = a2a_client.send
) -> Any:
    from google.adk.agents import LlmAgent

    tool_list = build_tool_functions(settings, sender)
    assert_both_tools(tool_list)
    return LlmAgent(
        name="harness_assistant",
        model=model if model is not None else build_model(settings),
        instruction=INSTRUCTION,
        tools=tool_list,
    )
