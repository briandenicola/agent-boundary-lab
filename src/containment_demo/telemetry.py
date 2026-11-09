"""Evidence emission.

This module does two things and deliberately not a third.

1. It turns a tool result into span attributes under a stable ``demo.*`` namespace, so a
   run can be correlated across application traces and platform egress decisions. There
   is no documented correlation key between the two, so ``demo_run_id`` is the only one
   we control and it is attached to everything.

2. It turns off generative-AI content capture before any instrumentation starts. Prompts,
   responses, request payloads and authorization headers must never reach telemetry.

It does **not** register a ``TracerProvider`` in the hosted path. The agent server host
already configures OpenTelemetry when it is constructed; adding a second provider would
produce duplicate or dropped spans. ``configure_local_telemetry`` exists only for running
outside the hosted runtime and is a no-op if a provider is already registered.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
from typing import Any

from opentelemetry import trace

from containment_demo.settings import Settings

logger = logging.getLogger(__name__)

TRACER_NAME = "containment_demo"

#: Environment switches that disable prompt/response capture in the instrumentation
#: layers this image loads. The exact variable each library honours is recorded in
#: docs/telemetry-map.md as it is confirmed against a real run; they are all set to the
#: safe value here so that an unconfirmed one fails closed rather than open.
_CONTENT_CAPTURE_OFF = {
    "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED": "false",
    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
    # google-adk telemetry/context.py:132-136 (_read_add_content_to_legacy_spans): DEFAULTS ON,
    # and is what puts gcp.vertex.agent.llm_request / llm_response / tool_response on spans
    # (telemetry/tracing.py:319-358). Only 'false' or '0' turns it off.
    "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
}


def disable_content_capture() -> None:
    """Force content capture off. Call before any instrumentation is initialised.

    Existing values are overwritten on purpose: this is a safety floor, not a default.
    An operator who wants prompt capture in this demo is asking for synthetic-data-only
    guarantees to be broken silently.
    """
    for key, value in _CONTENT_CAPTURE_OFF.items():
        os.environ[key] = value


def run_attributes(settings: Settings) -> dict[str, str]:
    """Attributes attached to every span so any record can be traced back to one run."""
    return {
        "demo.run_id": settings.demo_run_id,
        "demo.policy_mode": str(settings.policy_mode),
        "demo.agent_name": settings.agent_name,
        "demo.agent_version": settings.agent_version,
    }


def emit_tool_evidence(settings: Settings, result: dict[str, Any]) -> None:
    """Record one tool outcome as a span event.

    Only the observation fields are emitted. Response bodies, request payloads and
    headers are not, and the keys below are an allow-list rather than a filter, so a new
    field added to a tool result cannot leak by default.
    """
    tracer = trace.get_tracer(TRACER_NAME)
    attributes: dict[str, Any] = dict(run_attributes(settings))
    for key in (
        "tool_name",
        "succeeded",
        "http_status",
        "error_category",
        "error_detail",
        "duration_ms",
        "destination_host",
        "user_token_forwarded",
        "transport",
    ):
        if key in result and result[key] is not None:
            attributes[f"demo.{key}"] = result[key]

    span = trace.get_current_span()
    if span is not None and span.is_recording():
        span.add_event("demo.tool_result", attributes=attributes)
        return

    with tracer.start_as_current_span("demo.tool_result") as fallback:
        fallback.set_attributes(attributes)


def emit_governance_evidence(settings: Settings, result: dict[str, Any]) -> None:
    """Application governance evidence, never a synthetic platform egress decision."""
    attributes: dict[str, Any] = dict(run_attributes(settings))
    for key in (
        "tool_name",
        "session_id",
        "invocation_id",
        "tool_call_id",
        "governance_mode",
        "policy_id",
        "policy_version",
        "acs_verdict",
        "enforcement_action",
        "reason_code",
        "evaluation_duration_ms",
        "timestamp",
    ):
        value = result.get(key)
        if value is not None:
            attributes[f"demo.governance.{key}"] = value
    span = trace.get_current_span()
    context = span.get_span_context()
    if context.is_valid:
        attributes["demo.governance.trace_id"] = format(context.trace_id, "032x")
    if span.is_recording():
        span.add_event("demo.governance_decision", attributes=attributes)
    else:
        with trace.get_tracer(TRACER_NAME).start_as_current_span(
            "demo.governance_decision"
        ) as event:
            context = event.get_span_context()
            if context.is_valid:
                attributes["demo.governance.trace_id"] = format(context.trace_id, "032x")
            event.set_attributes(attributes)
    logger.info("governance decision %s", json.dumps(attributes, sort_keys=True))


def configure_local_telemetry(settings: Settings) -> bool:
    """Set up a tracer provider for local runs only.

    Returns ``True`` if this call installed a provider. Returns ``False`` when one is
    already registered, which is the expected outcome inside the hosted container, where
    the agent server host owns telemetry configuration.
    """
    disable_content_capture()

    current = trace.get_tracer_provider()
    if type(current).__name__ not in {"ProxyTracerProvider", "NoOpTracerProvider"}:
        logger.info("tracer provider already registered; not installing another")
        return False

    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info("no Application Insights connection string; traces stay local")
        return False

    try:
        # Resolved at runtime rather than imported at module scope: this is an optional
        # extra, and a static import would make the type checker depend on a package the
        # hosted image deliberately does not ship.
        monitor = importlib.import_module("azure.monitor.opentelemetry")
    except ImportError:
        # A local run without it still works; it simply keeps its traces local, which is
        # honest rather than silently broken.
        logger.warning(
            "azure-monitor-opentelemetry is not installed; traces stay local. "
            "Install with: uv pip install -e '.[telemetry]'"
        )
        return False

    monitor.configure_azure_monitor(
        connection_string=connection_string,
        resource_attributes=run_attributes(settings),
    )
    return True
