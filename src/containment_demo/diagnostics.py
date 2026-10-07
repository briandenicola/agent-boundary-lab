"""Authenticated diagnostic route.

The agent is driven by a model, and a model may decline to call a tool, call it twice,
or describe a call it never made. None of that is evidence about the network. This route
exists so a run can be triggered deterministically, bypassing the model while using the
**exact same two tool implementations** the agent uses.

Three constraints make this a diagnostic and not a third business tool:

* It accepts no destination. There is no URL, host, path or scheme parameter. Callers
  choose *which of the two fixed tools* to run, nothing more.
* It calls ``tools.get_servicing_policy`` and ``tools.send_to_external_processor``
  directly. It does not re-implement an HTTP call, so it cannot drift from the agent's
  behaviour and quietly test something else.
* It requires authentication. It causes real outbound traffic, so it is never open.

One tool failing must not suppress the other's result: each is run independently and
both outcomes are always returned.
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from containment_demo import tools
from containment_demo.settings import Settings

logger = logging.getLogger(__name__)

DIAGNOSTICS_PATH = "/internal/diagnostics/run"

#: The only callables this route may invoke. A name not in this mapping is rejected;
#: there is no way to reach an arbitrary destination through it.
_RUNNERS = {
    "get_servicing_policy": tools.get_servicing_policy,
    "send_to_external_processor": tools.send_to_external_processor,
}


def _authorised(request: Request, settings: Settings) -> bool:
    """Constant-time check of the bearer token.

    ``diagnostics_token`` is guaranteed non-empty by settings validation whenever
    diagnostics are enabled, so an absent configured secret cannot silently allow access.
    """
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        return False
    expected = settings.diagnostics_token.get_secret_value() if settings.diagnostics_token else ""
    if not expected:
        return False
    return hmac.compare_digest(presented, expected)


def _run_one(name: str, settings: Settings) -> dict[str, Any]:
    """Run a single tool, converting an unexpected crash into a recorded outcome.

    The tools already classify their own network failures. This guard exists only so
    that a defect in one tool cannot prevent the other's result from being reported.
    """
    try:
        return _RUNNERS[name](settings)
    except Exception as exc:  # noqa: BLE001 - must not mask the sibling tool's result
        logger.exception("diagnostic tool raised", extra={"tool": name})
        return {
            "tool_name": name,
            "succeeded": False,
            "error_category": "unexpected",
            "error_detail": type(exc).__name__,
            "demo_run_id": settings.demo_run_id,
        }


async def diagnostics_handler(request: Request, settings: Settings) -> JSONResponse:
    """Run one or both fixed tools and return their raw outcomes.

    The response deliberately reports only what the application observed. It makes no
    allow/deny determination: distinguishing a platform denial from a destination's own
    403, a DNS failure or a timeout requires platform evidence this process cannot see.
    """
    if not _authorised(request, settings):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    requested = request.query_params.getlist("tool") or list(_RUNNERS)
    unknown = [name for name in requested if name not in _RUNNERS]
    if unknown:
        return JSONResponse(
            {
                "error": "unknown tool",
                "unknown": unknown,
                "allowed": sorted(_RUNNERS),
            },
            status_code=400,
        )

    results = [_run_one(name, settings) for name in requested]
    logger.info(
        "diagnostic run complete",
        extra={"demo_run_id": settings.demo_run_id, "policy_mode": str(settings.policy_mode)},
    )
    return JSONResponse(
        {
            "demo_run_id": settings.demo_run_id,
            "policy_mode": str(settings.policy_mode),
            "agent_name": settings.agent_name,
            "agent_version": settings.agent_version,
            "determination": "inconclusive-without-platform-evidence",
            "results": results,
        }
    )


def register_diagnostics_route(host: Any, settings: Settings) -> None:
    """Attach the diagnostic route to the agent server host."""

    async def route(request: Request) -> JSONResponse:
        return await diagnostics_handler(request, settings)

    host.add_route(DIAGNOSTICS_PATH, route, methods=["POST"], include_in_schema=False)
    logger.info("diagnostics route registered", extra={"path": DIAGNOSTICS_PATH})
