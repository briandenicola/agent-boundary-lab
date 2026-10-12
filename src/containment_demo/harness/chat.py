"""A small chat service for the harness: one stateless turn per POST.

Chosen over extending ``demo_ui``: the demo UI is a two-button, no-model page whose tests
pin that shape, and the harness needs its own model settings and a slow-turn path. This
reuses the demo UI's auth check and nothing else. Every turn starts a fresh ADK session,
so there is no conversation memory to leak between turns.

The harness and its model are not governed by the Foundry policy; the page says so.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from containment_demo import invoke
from containment_demo.demo_ui import CSRF_HEADER, _authorised, _unauthorised
from containment_demo.harness import agent as harness_agent
from containment_demo.harness.page import PAGE
from containment_demo.harness.settings import HarnessSettings

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 1000
Responder = Callable[[HarnessSettings, str], Awaitable[dict[str, Any]]]


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


def build_view(settings: HarnessSettings, turn: dict[str, Any], *, turn_id: str) -> dict[str, Any]:
    results = turn["tool_results"]
    run_ids = sorted(
        {
            rid
            for r in results
            for rid in (r["result"] or {}).get("tool_run_ids", [])
            if isinstance(r["result"], dict)
        }
    )
    return {
        "turn_id": turn_id,
        "run_label": settings.run_label,
        "model": settings.local_model_name,
        "reply": turn["reply"],
        "tool_results": results,
        "tool_run_ids": run_ids,
        "determination": invoke.DETERMINATION,
        "governed_by_foundry_policy": False,
    }


def create_app(settings: HarnessSettings, *, responder: Responder = run_turn) -> Starlette:
    lock = asyncio.Lock()

    async def page(request: Request) -> Response:
        if not _authorised(request, settings):
            return _unauthorised()
        return HTMLResponse(
            PAGE.replace("__RUN_LABEL__", settings.run_label).replace(
                "__MODEL__", settings.local_model_name
            )
        )

    async def chat(request: Request) -> Response:
        if not _authorised(request, settings):
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
        return JSONResponse(build_view(settings, turn, turn_id=turn_id))

    async def healthz(_: Request) -> Response:
        return Response("ok")

    return Starlette(
        routes=[
            Route("/", page, methods=["GET"]),
            Route("/chat", chat, methods=["POST"]),
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
