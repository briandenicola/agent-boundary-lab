"""A small chat service for the harness: one stateless turn per POST or websocket message.

Chosen over extending ``demo_ui``: the demo UI is a two-button, no-model page whose tests
pin that shape, and the harness needs its own model settings and a slow-turn path. This
reuses the demo UI's auth check and nothing else. Every turn starts a fresh ADK session,
so there is no conversation memory to leak between turns.

The harness and its model are not governed by the Foundry policy; the page says so.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import hmac
import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from containment_demo import invoke
from containment_demo.actor_context import status_from_http
from containment_demo.demo_ui import CSRF_HEADER, _authorised, _unauthorised
from containment_demo.harness import agent as harness_agent
from containment_demo.harness.page import FLOW_PAGE, PAGE
from containment_demo.harness.settings import HarnessSettings

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1000
Responder = Callable[[HarnessSettings, str], Awaitable[dict[str, Any]]]

#: Display-only label for which actor drove this turn (WP-3, issue #4). Not a
#: credential and not authorization input: the presenter types this to say who they
#: are demonstrating, it is never checked against anything.
_ACTOR_ALIAS_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
DEFAULT_ACTOR_ALIAS = "unspecified-actor"

_INGRESS_ALIAS_HEADERS = (
    "x-auth-request-preferred-username",
    "x-auth-request-email",
    "x-auth-request-user",
)


async def run_turn(settings: HarnessSettings, message: str) -> dict[str, Any]:
    """Run one agent turn; return the model reply and every tool result it produced."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=harness_agent.build_agent(settings), app_name="harness")
    session = await runner.session_service.create_session(app_name="harness", user_id="harness")
    content = types.Content(role="user", parts=[types.Part(text=message)])
    reply = ""
    tool_results: list[dict[str, Any]] = []
    async for event in runner.run_async(
        user_id="harness", session_id=session.id, new_message=content
    ):
        for response in event.get_function_responses():
            tool_results.append({"tool": response.name, "result": response.response})
        if event.is_final_response() and event.content and event.content.parts:
            reply = "".join(p.text or "" for p in event.content.parts)
    return {"reply": reply, "tool_results": tool_results}


def _flattened_tool_outcomes(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every per-tool outcome record across all of this turn's agent calls, regardless
    of which call produced it. A call that transported-failed contributes none, which
    is correct: there is nothing to classify from a call that never reached a tool."""
    outcomes: list[dict[str, Any]] = []
    for r in results:
        result = r.get("result")
        if isinstance(result, dict):
            outcomes.extend(o for o in result.get("tool_outcomes") or [] if isinstance(o, dict))
    return outcomes


def _policy_http_status(outcomes: list[dict[str, Any]]) -> int | None:
    """The HTTP status ``get_servicing_policy`` reported, or ``None`` if it was never
    attempted this turn. This is the only signal used for the policy authorization
    label below -- never ``send_to_external_processor``, which is the containment tool."""
    for outcome in outcomes:
        if outcome.get("tool_name") == "get_servicing_policy":
            return outcome.get("http_status")
    return None


def _ingress_actor_alias(request: Request) -> str | None:
    """Resolve a display-safe actor alias from ingress-auth headers.

    The ingress (oauth2-proxy) is the authentication boundary in ingress_oidc mode.
    This function never returns raw claims: values are sanitized into the existing
    actor-alias character set before display.
    """
    for name in _INGRESS_ALIAS_HEADERS:
        raw = request.headers.get(name, "").strip()
        if not raw:
            continue
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", raw)[:64].strip("._-")
        if _ACTOR_ALIAS_RE.fullmatch(cleaned):
            return cleaned
    return None


def _ingress_actor_alias_from_headers(headers: Any) -> str | None:
    for name in _INGRESS_ALIAS_HEADERS:
        raw = headers.get(name, "").strip()
        if not raw:
            continue
        cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", raw)[:64].strip("._-")
        if _ACTOR_ALIAS_RE.fullmatch(cleaned):
            return cleaned
    return None


def _is_authorised_headers(headers: Any, settings: HarnessSettings) -> bool:
    header = headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if not presented:
        return False
    if scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(presented, validate=True).decode("utf-8")
        except ValueError:
            return False
        presented = decoded.partition(":")[2]
    elif scheme.lower() != "bearer":
        return False
    return bool(presented) and hmac.compare_digest(presented, settings.ui_token.get_secret_value())


def build_view(
    settings: HarnessSettings,
    turn: dict[str, Any],
    *,
    turn_id: str,
    actor_alias: str = DEFAULT_ACTOR_ALIAS,
) -> dict[str, Any]:
    results = turn["tool_results"]
    run_ids = sorted(
        {
            rid
            for r in results
            for rid in (r["result"] or {}).get("tool_run_ids", [])
            if isinstance(r["result"], dict)
        }
    )
    # Two separate outcome categories, surfaced side by side and never merged:
    # - policy_authorization_status: WP-2's identity-authorization decision for this
    #   actor, read only from get_servicing_policy's reported HTTP status.
    # - determination: the containment determination (always inconclusive without
    #   platform evidence). It is a constant precisely so a policy denial above can
    #   never be mistaken for, or silently promoted into, a containment result.
    policy_status = status_from_http(_policy_http_status(_flattened_tool_outcomes(results)))
    return {
        "turn_id": turn_id,
        "run_label": settings.run_label,
        "model": settings.local_model_name,
        "reply": turn["reply"],
        "tool_results": results,
        "tool_run_ids": run_ids,
        "actor_alias": actor_alias,
        "policy_authorization_status": str(policy_status),
        "determination": invoke.DETERMINATION,
        "governed_by_foundry_policy": False,
    }


def create_app(settings: HarnessSettings, *, responder: Responder = run_turn) -> Starlette:
    lock = asyncio.Lock()
    logout_chip = '<a class="chip" href="/oauth2/sign_out?rd=%2F">Logout</a>'
    diagnostics_links = [
        ("Evidence workbook", settings.diagnostics_workbook_url),
        ("Log Analytics", settings.diagnostics_logs_url),
        ("App Insights", settings.diagnostics_app_insights_url),
    ]
    diagnostics_items = "".join(
        f'<a class="chip" href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{label}</a>'
        for label, url in diagnostics_links
        if url.strip()
    )
    diagnostics_card = (
        '<section class="card"><h2>Diagnostics</h2><div class="row">'
        + diagnostics_items
        + "</div></section>"
        if diagnostics_items
        else ""
    )

    async def page(request: Request) -> Response:
        actor_alias = ""
        show_logout = False
        if settings.auth_mode == "legacy":
            if not _authorised(request, settings):
                return _unauthorised()
        else:
            show_logout = True
            actor_alias = _ingress_actor_alias(request) or ""
            if not actor_alias:
                return _unauthorised()
        return HTMLResponse(
            PAGE.replace("__RUN_LABEL__", settings.run_label)
            .replace("__MODEL__", settings.local_model_name)
            .replace("__ACTOR_ALIAS__", html.escape(actor_alias, quote=True))
            .replace("__LOGOUT_CHIP__", logout_chip if show_logout else "")
            .replace("__DIAGNOSTICS_CARD__", diagnostics_card)
        )

    async def flow(request: Request) -> Response:
        show_logout = False
        if settings.auth_mode == "legacy":
            if not _authorised(request, settings):
                return _unauthorised()
        else:
            show_logout = True
            if _ingress_actor_alias(request) is None:
                return _unauthorised()
        return HTMLResponse(
            FLOW_PAGE.replace("__RUN_LABEL__", settings.run_label)
            .replace("__MODEL__", settings.local_model_name)
            .replace("__FLOW_LOGOUT_CHIP__", logout_chip if show_logout else "")
        )

    async def chat(request: Request) -> Response:
        ingress_alias = None
        if settings.auth_mode == "legacy":
            if not _authorised(request, settings):
                return _unauthorised()
        else:
            ingress_alias = _ingress_actor_alias(request)
            if ingress_alias is None:
                return _unauthorised()
        if request.headers.get(CSRF_HEADER) != "1":
            return JSONResponse({"error": "missing X-Demo-UI header"}, status_code=403)
        try:
            body = await request.json()
            message = body["message"]
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "body must be JSON with a message"}, status_code=400)
        if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_CHARS:
            return JSONResponse({"error": "message must be 1-1000 characters"}, status_code=400)
        actor_alias = body.get("actor_alias", DEFAULT_ACTOR_ALIAS)
        if settings.auth_mode == "ingress_oidc":
            if actor_alias not in (DEFAULT_ACTOR_ALIAS, ingress_alias):
                return JSONResponse(
                    {"error": "actor_alias is managed by ingress authentication"},
                    status_code=400,
                )
            actor_alias = ingress_alias or DEFAULT_ACTOR_ALIAS
        if not isinstance(actor_alias, str) or not _ACTOR_ALIAS_RE.fullmatch(actor_alias):
            return JSONResponse(
                {"error": "actor_alias must be 1-64 safe characters"}, status_code=400
            )
        if lock.locked():
            return JSONResponse({"error": "a turn is already in progress"}, status_code=409)
        turn_id = f"turn-{uuid.uuid4().hex[:12]}"
        async with lock:
            logger.info("harness turn starting turn_id=%s", turn_id)
            try:
                turn = await asyncio.wait_for(
                    responder(settings, message), timeout=settings.turn_timeout_seconds
                )
            except TimeoutError:
                return JSONResponse(
                    {"error": "turn timed out", "turn_id": turn_id, "source": "harness"},
                    status_code=504,
                )
            except Exception as exc:
                logger.warning("harness turn failed turn_id=%s %s", turn_id, type(exc).__name__)
                return JSONResponse(
                    {"error": invoke.sanitize(exc), "turn_id": turn_id, "source": "harness/model"},
                    status_code=502,
                )
        return JSONResponse(build_view(settings, turn, turn_id=turn_id, actor_alias=actor_alias))

    async def ws(websocket: WebSocket) -> None:
        ingress_alias = None
        if settings.auth_mode == "legacy":
            if not _is_authorised_headers(websocket.headers, settings):
                await websocket.close(code=1008)
                return
        else:
            ingress_alias = _ingress_actor_alias_from_headers(websocket.headers)
            if ingress_alias is None:
                await websocket.close(code=1008)
                return

        await websocket.accept()
        while True:
            try:
                body = await websocket.receive_json()
            except WebSocketDisconnect:
                return
            except Exception:
                await websocket.send_json(
                    {"event": "error", "status": 400, "source": "request", "error": "invalid JSON"}
                )
                continue

            message = body.get("message")
            if (
                not isinstance(message, str)
                or not message.strip()
                or len(message) > MAX_MESSAGE_CHARS
            ):
                await websocket.send_json(
                    {
                        "event": "error",
                        "status": 400,
                        "source": "request",
                        "error": "message must be 1-1000 characters",
                    }
                )
                continue

            actor_alias = body.get("actor_alias", DEFAULT_ACTOR_ALIAS)
            if settings.auth_mode == "ingress_oidc":
                if actor_alias not in (DEFAULT_ACTOR_ALIAS, ingress_alias):
                    await websocket.send_json(
                        {
                            "event": "error",
                            "status": 400,
                            "source": "request",
                            "error": "actor_alias is managed by ingress authentication",
                        }
                    )
                    continue
                actor_alias = ingress_alias or DEFAULT_ACTOR_ALIAS
            if not isinstance(actor_alias, str) or not _ACTOR_ALIAS_RE.fullmatch(actor_alias):
                await websocket.send_json(
                    {
                        "event": "error",
                        "status": 400,
                        "source": "request",
                        "error": "actor_alias must be 1-64 safe characters",
                    }
                )
                continue
            if lock.locked():
                await websocket.send_json(
                    {
                        "event": "error",
                        "status": 409,
                        "source": "harness",
                        "error": "a turn is already in progress",
                    }
                )
                continue

            turn_id = f"turn-{uuid.uuid4().hex[:12]}"
            await websocket.send_json({"event": "accepted", "turn_id": turn_id})
            async with lock:
                logger.info("harness turn starting turn_id=%s", turn_id)
                turn_task = asyncio.create_task(responder(settings, message))
                started = asyncio.get_running_loop().time()
                next_progress_at = 5.0
                try:
                    while not turn_task.done():
                        elapsed = asyncio.get_running_loop().time() - started
                        remaining = settings.turn_timeout_seconds - elapsed
                        if remaining <= 0:
                            turn_task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await turn_task
                            raise TimeoutError
                        try:
                            await asyncio.wait_for(asyncio.shield(turn_task), timeout=min(1.0, remaining))
                        except TimeoutError:
                            pass
                        elapsed = asyncio.get_running_loop().time() - started
                        if elapsed >= next_progress_at and not turn_task.done():
                            await websocket.send_json(
                                {
                                    "event": "progress",
                                    "turn_id": turn_id,
                                    "elapsed_seconds": int(elapsed),
                                }
                            )
                            next_progress_at += 5.0
                    turn = await turn_task
                except TimeoutError:
                    await websocket.send_json(
                        {
                            "event": "error",
                            "status": 504,
                            "source": "harness",
                            "turn_id": turn_id,
                            "error": "turn timed out",
                        }
                    )
                    continue
                except Exception as exc:
                    logger.warning("harness turn failed turn_id=%s %s", turn_id, type(exc).__name__)
                    await websocket.send_json(
                        {
                            "event": "error",
                            "status": 502,
                            "source": "harness/model",
                            "turn_id": turn_id,
                            "error": invoke.sanitize(exc),
                        }
                    )
                    continue
            await websocket.send_json(
                {
                    "event": "result",
                    "turn_id": turn_id,
                    "data": build_view(settings, turn, turn_id=turn_id, actor_alias=actor_alias),
                }
            )

    async def healthz(_: Request) -> Response:
        return Response("ok")

    return Starlette(
        routes=[
            Route("/", page, methods=["GET"]),
            Route("/flow", flow, methods=["GET"]),
            Route("/chat", chat, methods=["POST"]),
            WebSocketRoute("/ws", ws),
            Route("/healthz", healthz, methods=["GET"]),
        ]
    )


def main() -> None:  # pragma: no cover - process entrypoint
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = HarnessSettings()  # type: ignore[call-arg]
    uvicorn.run(create_app(settings), host="0.0.0.0", port=8080, log_level="warning")  # noqa: S104


if __name__ == "__main__":  # pragma: no cover
    main()
