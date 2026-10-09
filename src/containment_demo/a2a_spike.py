"""A2A spike (Blocker 5): can incoming A2A be enabled on a hosted CONTAINER agent?

PROPOSED and UNVERIFIED. Nothing here has been run against the platform. See
docs/compatibility.md "B5a" for what is documented, what is documented only for prompt
agents, and what is unknown.

Three steps, each recorded on its own:

1. ``enable``  — merge-patch ONE agent with an agent card and
   ``agent_endpoint.protocol_configuration.{responses,a2a}``. This CHANGES the platform, so
   it only runs with ``--enable``. Without it the step is recorded as skipped.
2. ``card``    — GET ``.../protocols/a2a/agentCard/v1.0`` with ``A2A-Version: 1.0``.
3. ``send``    — one A2A message through the Python A2A SDK, version pinned to 1.0.
   Calls the agent, so it only runs with ``--send``.

THERE IS NO PASS. ``determination`` is always :data:`DETERMINATION`. A successful card and
send are *observations* a human may cite; they are not a verdict. A failure is classified as
OUR call (transport, authentication, network — says nothing about A2A support) or the
PLATFORM (a well-formed refusal). Only a platform refusal of the enable or card step is
recorded as an ``unsupported-signal``, and even that is a signal, not a conclusion. Anything
else stays inconclusive.

The Azure SDK, ``httpx`` and ``a2a`` are imported lazily, so ``pytest tests/unit`` needs no
Azure package, credential or network.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from containment_demo.invoke import classify_invocation_exception, http_status_of, sanitize
from containment_demo.settings import ErrorCategory

logger = logging.getLogger(__name__)

DETERMINATION = "inconclusive-a2a-unverified"
A2A_VERSION = "1.0"
CARD_PATH = f"agentCard/v{A2A_VERSION}"
TOKEN_SCOPE = "https://ai.azure.com/.default"  # noqa: S105 - an OAuth scope, not a secret
# Statuses where the platform itself says "not here / not supported / not accepted".
_UNSUPPORTED_STATUSES = frozenset({400, 404, 405, 415, 501})
# Statuses that describe OUR identity or network path, not A2A support.
_OUR_SIDE_STATUSES = frozenset({401, 403, 407})
_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

StepStatus = Literal["ok", "failed", "unsupported-signal", "skipped"]
Origin = Literal["our_call", "platform", "none"]

# Sent as the A2A message. Fixed and synthetic; never logged or recorded back.
_PROBE_TEXT = "a2a-spike connectivity probe"


@dataclass
class StepResult:
    name: str
    status: StepStatus
    origin: Origin = "none"
    error_category: str | None = None
    http_status: int | None = None
    detail: str | None = None
    observed: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "origin": self.origin,
            "error_category": self.error_category,
            "http_status": self.http_status,
            "detail": self.detail,
            "observed": self.observed,
        }


@dataclass
class SpikeResult:
    agent_name: str
    a2a_base: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def determination(self) -> str:
        return DETERMINATION

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "a2a_base": self.a2a_base,
            "determination": DETERMINATION,
            "unsupported_signals": [s.name for s in self.steps if s.status == "unsupported-signal"],
            "steps": [s.as_dict() for s in self.steps],
        }


def project_endpoint(account: str, project: str) -> str:
    for label in (account, project):
        if not _NAME.match(label):
            raise ValueError(f"{label!r} is not a DNS label")
    return f"https://{account}.services.ai.azure.com/api/projects/{project}"


def a2a_base(endpoint: str, agent_name: str) -> str:
    if not _NAME.match(agent_name):
        raise ValueError(f"{agent_name!r} is not a valid agent name")
    return f"{endpoint}/agents/{agent_name}/endpoint/protocols/a2a"


BODY_CAP = 2048
CARD_CAP = 4096
_REDACTIONS = (
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [redacted]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*"), "[redacted-jwt]"),
    (
        re.compile(
            r"(?i)(authorization|token|secret|password|api[-_]?key|sig|client_secret)"
            r"(\"?\s*[:=]\s*\"?)[^\s\",&}]+"
        ),
        r"\1\2[redacted]",
    ),
)


def redact_body(text: str, cap: int = BODY_CAP) -> str:
    """Bounded, redacted platform response text. Tokens and auth values never survive."""
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text[:cap]


def _version_fields(node: Any, path: str = "", depth: int = 0) -> dict[str, Any]:
    """Every field whose NAME mentions 'version', plus supportedInterfaces, with its path."""
    found: dict[str, Any] = {}
    if depth > 6:
        return found
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else str(key)
            if "version" in str(key).lower() or str(key) == "supportedInterfaces":
                found[here] = value
            found.update(_version_fields(value, here, depth + 1))
    elif isinstance(node, list):
        for index, value in enumerate(node[:20]):
            found.update(_version_fields(value, f"{path}[{index}]", depth + 1))
    return found


def declared_protocol_versions(body: dict[str, Any] | None) -> list[str]:
    """Protocol versions the card declares, from supportedInterfaces[].protocolVersion.

    Observed card shape (docs/compatibility.md B5a, 2026-10-09): there is NO top-level
    ``protocolVersion``; the top-level ``version`` is the agent card's own version and is
    deliberately not read here.
    """
    interfaces = body.get("supportedInterfaces") if isinstance(body, dict) else None
    if not isinstance(interfaces, list):
        return []
    return [
        str(item["protocolVersion"])
        for item in interfaces
        if isinstance(item, dict) and isinstance(item.get("protocolVersion"), str)
    ]


def summarise_card(body: dict[str, Any] | None) -> dict[str, Any]:
    """Raw card shape for the record: top-level keys, version-like fields, redacted raw text."""
    if not isinstance(body, dict):
        return {"card_keys": None}
    return {
        "card_keys": sorted(body),
        "card_version_fields": _version_fields(body),
        "card_raw": redact_body(json.dumps(body, indent=1, default=str), CARD_CAP),
    }


def _response_of(exc: BaseException) -> Any:
    """The HTTP response an httpx-style status error carries (``exc.response``), if any."""
    for candidate in _chain_of(exc):
        response = getattr(candidate, "response", None)
        if isinstance(getattr(response, "status_code", None), int):
            return response
    return None


def _chain_of(exc: BaseException) -> list[BaseException]:
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def classify_failure(name: str, exc: BaseException, *, may_signal_unsupported: bool) -> StepResult:
    """Our call versus the platform. A bare status is never read as more than it is.

    ``httpx.HTTPStatusError`` carries its status on ``exc.response``, not ``exc.status_code``,
    so a well-formed platform refusal used to be mislabelled as our own call.
    """
    response = _response_of(exc)
    status = http_status_of(exc)
    observed: dict[str, Any] = {}
    if response is not None:
        status = response.status_code
        category = ErrorCategory.HTTP_ERROR
        try:
            observed["response_body"] = redact_body(str(response.text))
        except Exception:  # unreadable body: record that, do not fail the classification
            observed["response_body"] = "[unreadable]"
    else:
        category = classify_invocation_exception(exc)
    if category is ErrorCategory.HTTP_ERROR and status is not None:
        if status in _OUR_SIDE_STATUSES:
            origin: Origin = "our_call"
            step_status: StepStatus = "failed"
        elif may_signal_unsupported and status in _UNSUPPORTED_STATUSES:
            origin, step_status = "platform", "unsupported-signal"
        else:
            origin, step_status = "platform", "failed"
    else:
        origin, step_status = "our_call", "failed"
    return StepResult(
        name=name,
        status=step_status,
        origin=origin,
        error_category=category.value,
        http_status=status,
        detail=sanitize(exc),
        observed=observed,
    )


# --- the three live operations. Each is injectable, and each is the only place its SDK
# --- is imported. ------------------------------------------------------------------


def build_patch_models() -> tuple[Any, Any]:
    """The documented ``update_details`` arguments, from the installed SDK models."""
    from azure.ai.projects.models import (
        A2AProtocolConfiguration,
        AgentCard,
        AgentCardSkill,
        AgentEndpointConfig,
        ProtocolConfiguration,
        ResponsesProtocolConfiguration,
    )

    endpoint_config = AgentEndpointConfig(
        protocol_configuration=ProtocolConfiguration(
            responses=ResponsesProtocolConfiguration(),
            a2a=A2AProtocolConfiguration(),
        ),
    )
    card = AgentCard(
        version="1.0",
        description="Containment demo agent. Two HTTP tools; synthetic data only.",
        skills=[
            AgentCardSkill(
                id="containment-probe",
                name="Containment probe",
                description="Calls two fixed HTTPS destinations and reports each outcome.",
            )
        ],
    )
    return endpoint_config, card


def live_enable(endpoint: str, agent_name: str) -> None:
    """PATCH the agent. Mutates the platform; only reached with ``--enable``."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint_config, card = build_patch_models()
    project = AIProjectClient(
        endpoint=endpoint, credential=DefaultAzureCredential(), allow_preview=True
    )
    project.agents.update_details(
        agent_name=agent_name, agent_endpoint=endpoint_config, agent_card=card
    )


def live_card(base: str, timeout: float) -> tuple[int, dict[str, Any] | None]:
    import httpx
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token(TOKEN_SCOPE).token
    response = httpx.get(
        f"{base}/{CARD_PATH}",
        headers={"Authorization": f"Bearer {token}", "A2A-Version": A2A_VERSION},
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
    )
    response.raise_for_status()
    body = response.json()
    return response.status_code, body if isinstance(body, dict) else None


def live_send(base: str, timeout: float) -> int:
    """One A2A message via the Python A2A SDK, as in the Microsoft doc. Returns reply count."""
    import asyncio

    import httpx
    from a2a.client import A2ACardResolver, ClientConfig, create_client
    from a2a.helpers import new_text_message
    from a2a.types.a2a_pb2 import Role, SendMessageRequest
    from azure.identity import DefaultAzureCredential

    token = DefaultAzureCredential().get_token(TOKEN_SCOPE).token

    async def go() -> int:
        # The header and the resolved v1.0 card agree, so there is no version-ambiguous 400.
        async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}", "A2A-Version": A2A_VERSION},
            timeout=httpx.Timeout(timeout),
            follow_redirects=False,
        ) as http:
            resolver = A2ACardResolver(httpx_client=http, base_url=base, agent_card_path=CARD_PATH)
            card = await resolver.get_agent_card()
            client = await create_client(
                agent=card, client_config=ClientConfig(streaming=False, httpx_client=http)
            )
            count = 0
            request = SendMessageRequest(message=new_text_message(_PROBE_TEXT, role=Role.ROLE_USER))
            async for _ in client.send_message(request):
                count += 1
            await client.close()
            return count

    return asyncio.run(go())


def run_spike(
    *,
    endpoint: str,
    agent_name: str,
    enable: bool,
    send: bool,
    timeout: float = 60.0,
    enable_fn: Callable[[str, str], None] = live_enable,
    card_fn: Callable[[str, float], tuple[int, dict[str, Any] | None]] = live_card,
    send_fn: Callable[[str, float], int] = live_send,
) -> SpikeResult:
    base = a2a_base(endpoint, agent_name)
    result = SpikeResult(agent_name=agent_name, a2a_base=base)

    if enable:
        try:
            enable_fn(endpoint, agent_name)
            result.steps.append(StepResult("enable", "ok", detail="patch accepted"))
        except Exception as exc:
            result.steps.append(classify_failure("enable", exc, may_signal_unsupported=True))
    else:
        result.steps.append(StepResult("enable", "skipped", detail="pass --enable to PATCH"))

    try:
        status, body = card_fn(base, timeout)
        declared = declared_protocol_versions(body)
        observed = {
            "http_status": status,
            "card_protocol_versions": declared,
            **summarise_card(body),
        }
        if A2A_VERSION in declared:
            result.steps.append(StepResult("card", "ok", http_status=status, observed=observed))
        else:
            result.steps.append(
                StepResult(
                    "card",
                    "failed",
                    origin="platform",
                    http_status=status,
                    detail=f"card declares no interface with protocolVersion {A2A_VERSION}",
                    observed=observed,
                )
            )
    except Exception as exc:
        result.steps.append(classify_failure("card", exc, may_signal_unsupported=True))

    if send:
        try:
            count = send_fn(base, timeout)
            result.steps.append(StepResult("send", "ok", observed={"reply_events": count}))
        except Exception as exc:
            result.steps.append(classify_failure("send", exc, may_signal_unsupported=False))
    else:
        result.steps.append(StepResult("send", "skipped", detail="pass --send to call the agent"))

    logger.info(
        "a2a spike agent=%s steps=%s",
        agent_name,
        {s.name: s.status for s in result.steps},
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A2A spike. PROPOSED, UNVERIFIED.")
    parser.add_argument("--account", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--enable", action="store_true", help="PATCH the agent (changes Azure)")
    parser.add_argument("--send", action="store_true", help="send one A2A message")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(argv)

    result = run_spike(
        endpoint=project_endpoint(args.account, args.project),
        agent_name=args.agent,
        enable=args.enable,
        send=args.send,
        timeout=args.timeout,
    )
    json.dump(result.as_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    # Exit 0 only means the spike ran. It is never a pass.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
