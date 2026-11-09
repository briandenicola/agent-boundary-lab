"""Request-scoped Foundry toolbox transport; no downstream tokens enter the container."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from azure.ai.agentserver.core import get_request_context
from azure.identity import ManagedIdentityCredential

from containment_demo.settings import Settings

MAX_RESPONSE_BYTES = 65_536


class ToolboxError(ValueError):
    """Only a stable reason code, never the upstream error message."""


class ConsentRequired(ToolboxError):
    def __init__(self, link: str) -> None:
        super().__init__("toolbox_consent_required")
        self.link = link


@dataclass
class ToolboxTurn:
    consent_links: list[str] = field(default_factory=list, repr=False)


_turn: ContextVar[ToolboxTurn | None] = ContextVar("toolbox_turn", default=None)


@contextmanager
def capture_consent() -> Iterator[ToolboxTurn]:
    state = ToolboxTurn()
    token = _turn.set(state)
    try:
        yield state
    finally:
        _turn.reset(token)


def record_consent(link: str) -> None:
    state = _turn.get()
    if state is not None and link not in state.consent_links:
        state.consent_links.append(link)


def _raise_rpc_error(error: object) -> None:
    if not isinstance(error, dict):
        raise ToolboxError("toolbox_invalid_error")
    message = error.get("message")
    if error.get("code") == -32006 and isinstance(message, str):
        start = message.find("{")
        if start >= 0:
            try:
                details = json.loads(message[start:])
            except json.JSONDecodeError:
                raise ToolboxError("toolbox_invalid_error") from None
            errors = details.get("errors") if isinstance(details, dict) else None
            if isinstance(errors, list):
                for source in errors:
                    nested = source.get("error") if isinstance(source, dict) else None
                    if not isinstance(nested, dict) or nested.get("code") != "CONSENT_REQUIRED":
                        continue
                    link = nested.get("message")
                    if isinstance(link, str):
                        parsed = urlparse(link)
                        if (
                            len(link) <= 8192
                            and parsed.scheme == "https"
                            and parsed.hostname
                            and not parsed.username
                            and not parsed.password
                            and not any(c.isspace() or ord(c) < 32 for c in link)
                        ):
                            raise ConsentRequired(link)
                    raise ToolboxError("toolbox_invalid_consent_link")
    raise ToolboxError("toolbox_rpc_error")


def _envelope(body: object, request_id: int) -> dict[str, Any]:
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or body.get("id") != request_id:
        raise ToolboxError("toolbox_invalid_response")
    if "error" in body:
        _raise_rpc_error(body["error"])
    result = body.get("result")
    if not isinstance(result, dict):
        raise ToolboxError("toolbox_invalid_result")
    return result


def _rpc(
    client: httpx.Client,
    credential: ManagedIdentityCredential,
    settings: Settings,
    call_id: str,
    request_id: int,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    token = credential.get_token("https://ai.azure.com/.default").token
    deadline = time.monotonic() + settings.http_timeout_seconds
    with client.stream(
        "POST",
        str(settings.toolbox_endpoint),
        headers={
            "Authorization": f"Bearer {token}",
            "x-agent-foundry-call-id": call_id,
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    ) as response:
        response.raise_for_status()
        streaming = response.headers.get("content-type", "").split(";")[0] == "text/event-stream"
        body = b""
        received = 0
        for chunk in response.iter_bytes():
            received += len(chunk)
            if received > MAX_RESPONSE_BYTES:
                raise ToolboxError("toolbox_response_too_large")
            if time.monotonic() >= deadline:
                raise httpx.ReadTimeout("toolbox_response_deadline")
            body += chunk
            if streaming:
                body = body.replace(b"\r\n", b"\n")
                while b"\n\n" in body:
                    event, body = body.split(b"\n\n", 1)
                    data = b"\n".join(
                        line[5:].lstrip()
                        for line in event.split(b"\n")
                        if line.startswith(b"data:")
                    )
                    if data:
                        item = json.loads(data)
                        if isinstance(item, dict) and item.get("id") == request_id:
                            return _envelope(item, request_id)
        if streaming:
            raise ToolboxError("toolbox_incomplete_stream")
        return _envelope(json.loads(body), request_id)


def call_policy(client: httpx.Client, settings: Settings) -> dict[str, Any]:
    context = get_request_context()
    if not context.call_id or not context.user_id:
        raise ToolboxError("toolbox_user_context_missing")
    with ManagedIdentityCredential(
        connection_timeout=settings.http_timeout_seconds,
        read_timeout=settings.http_timeout_seconds,
        retry_total=0,
    ) as credential:
        listed = _rpc(client, credential, settings, context.call_id, 1, "tools/list", {})
        entries = listed.get("tools")
        if not isinstance(entries, list):
            raise ToolboxError("toolbox_invalid_tool_list")
        matches = [
            item
            for item in entries
            if isinstance(item, dict) and item.get("name") == settings.toolbox_policy_tool
        ]
        if len(matches) != 1:
            raise ToolboxError("toolbox_policy_tool_missing")
        metadata = matches[0].get("_meta")
        configuration = metadata.get("tool_configuration") if isinstance(metadata, dict) else None
        if not isinstance(configuration, dict) or configuration.get("require_approval") != "never":
            raise ToolboxError("toolbox_tool_requires_unsupported_approval")
        result = _rpc(
            client,
            credential,
            settings,
            context.call_id,
            2,
            "tools/call",
            {
                "name": settings.toolbox_policy_tool,
                "arguments": {"demo_run_id": settings.demo_run_id},
            },
        )
    if result.get("isError"):
        raise ToolboxError("toolbox_tool_error")
    payload = result.get("structuredContent")
    if payload is None:
        content = result.get("content")
        if (
            isinstance(content, list)
            and len(content) == 1
            and isinstance(content[0], dict)
            and content[0].get("type") == "text"
            and isinstance(content[0].get("text"), str)
        ):
            payload = json.loads(content[0]["text"])
    if (
        not isinstance(payload, dict)
        or payload.get("demo_run_id") != settings.demo_run_id
        or not isinstance(payload.get("policy"), dict)
        or not isinstance(payload.get("user_object_id"), str)
    ):
        raise ToolboxError("toolbox_invalid_policy_result")
    return payload
