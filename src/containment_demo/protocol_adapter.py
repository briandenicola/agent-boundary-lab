"""Foundry hosted-agent protocol adapter.

Wraps the ADK runner in the Responses protocol server so the same agent code runs
unchanged inside the Foundry hosted-agent container.

Two ordering facts drive the structure of this module, both verified against the
installed packages rather than assumed (see docs/compatibility.md A3 and E3):

1. ``ResponsesAgentServerHost()`` configures OpenTelemetry when it is constructed. ADK's
   ``maybe_set_otel_providers()`` declines to override an already-registered global
   provider. So the host must be built **before** the agent, and then ADK no-ops and we
   get one tracer provider instead of two exporting duplicates.
2. ``GET /readiness`` is registered by the server package. We do not implement it, and
   we must not shadow it.
"""

from __future__ import annotations

import logging
from typing import Any

from containment_demo.settings import Settings
from containment_demo.telemetry import disable_content_capture

logger = logging.getLogger(__name__)

#: Routes owned by the server package. Ours must not collide with these.
PLATFORM_ROUTES = frozenset(
    {
        "/responses",
        "/responses/{response_id}",
        "/responses/{response_id}/cancel",
        "/responses/{response_id}/input_items",
        "/readiness",
    }
)


def build_host(settings: Settings) -> Any:
    """Construct the Responses host and register the agent handler.

    The host is constructed first, before any ADK import does telemetry setup. Do not
    reorder this function without reading the note in the module docstring.
    """
    from azure.ai.agentserver.responses import (
        ResponsesAgentServerHost,
        ResponsesServerOptions,
        TextResponse,
    )

    host = ResponsesAgentServerHost(
        options=ResponsesServerOptions(default_model=settings.model_deployment)
    )

    # ADK is imported only now, after the host has configured the global tracer provider.
    from google.adk.runners import InMemoryRunner

    from containment_demo.agent import build_agent

    agent = build_agent(settings)
    runner = InMemoryRunner(agent=agent, app_name=settings.agent_name)

    @host.response_handler
    async def handle(request: Any, context: Any, cancellation_signal: Any) -> Any:
        """Run one turn through the ADK agent.

        Cancellation and shutdown are distinct signals in this runtime; only
        cancellation is observed here, and a cancelled turn returns what it has rather
        than raising, so a partial result is still attributable to its run marker.

        ``get_input_text`` is a **coroutine function** on every ``ResponseContext``
        variant in ``azure-ai-agentserver-responses`` 2.2.0 — signature
        ``(self, *, resolve_references: bool = True) -> str``. Without the ``await``
        this binds a coroutine object, the model never sees the prompt, and neither
        business tool is ever called. Covered by
        ``tests/unit/test_protocol_adapter.py::TestInputTextIsAwaited``.
        """
        user_text = await context.get_input_text()
        reply = await _run_agent_turn(
            runner=runner,
            settings=settings,
            user_text=user_text,
            cancellation_signal=cancellation_signal,
        )
        return TextResponse(context, request, text=reply)

    if settings.diagnostics_enabled:
        from containment_demo.diagnostics import register_diagnostics_route

        register_diagnostics_route(host, settings)

    return host


async def _run_agent_turn(
    *,
    runner: Any,
    settings: Settings,
    user_text: str,
    cancellation_signal: Any,
) -> str:
    """Drive the ADK runner for a single user turn and collect the final text."""
    from google.genai import types

    session_service = runner.session_service
    session = await session_service.create_session(
        app_name=settings.agent_name,
        user_id="demo-user",
    )

    content = types.Content(role="user", parts=[types.Part(text=user_text)])
    chunks: list[str] = []

    async for event in runner.run_async(
        user_id="demo-user",
        session_id=session.id,
        new_message=content,
    ):
        if cancellation_signal is not None and cancellation_signal.is_set():
            logger.info("turn cancelled by client", extra={"demo_run_id": settings.demo_run_id})
            break
        if getattr(event, "content", None) and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    chunks.append(part.text)

    return "".join(chunks) or "(no response)"


def main() -> None:
    """Container entrypoint.

    Configuration is validated before the server starts. A validation failure exits
    non-zero rather than serving traffic with an unusable destination configuration.
    """
    logging.basicConfig(level=logging.INFO)
    # Before anything that reads ADK's telemetry context, and for every mode.
    disable_content_capture()
    settings = Settings()  # type: ignore[call-arg]
    logger.info(
        "starting hosted agent",
        extra={
            "demo_run_id": settings.demo_run_id,
            "policy_mode": str(settings.policy_mode),
            "policy_api_host": settings.policy_api_host,
            "test_receiver_host": settings.test_receiver_host,
            "agent_version": settings.agent_version,
        },
    )
    build_host(settings).run()


if __name__ == "__main__":
    main()
