"""The A2A protocol layer (a2a-sdk 1.0.2) and the Starlette app.

Imports no Foundry SDK and not ``target``: a ``containment_demo.a2a_facade.core.AgentTarget``
is injected. tests/unit/test_a2a_facade.py enforces that by reading this file's imports.

Surface: the agent card, and A2A v1.0 JSON-RPC ``SendMessage`` at ``/``. Streaming is off.
``CancelTask`` returns an explicit unsupported error. Tasks are held in memory
(non-durable). Nothing logged or returned carries prompt text, response text beyond the
agent's own answer to the caller, or an Authorization header.
"""

from __future__ import annotations

import logging
from typing import Any

from a2a.auth.user import User
from a2a.helpers import new_task_from_user_message
from a2a.helpers.proto_helpers import new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    DefaultServerCallContextBuilder,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types.a2a_pb2 import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityRequirement,
    SecurityScheme,
    StringList,
)
from a2a.utils.errors import InvalidParamsError, UnsupportedOperationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from containment_demo.a2a_facade.core import (
    MAX_INPUT_CHARS,
    SKILL_ID,
    AgentTarget,
    Authenticator,
    ContextMap,
    FacadeSettings,
    SharedTokenAuthenticator,
    TargetError,
)

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "1.0"
BINDING = "JSONRPC"
HEALTH_PATH = "/healthz"
BEARER_SCHEME = "bearer"


def build_card(settings: FacadeSettings) -> AgentCard:
    """The card this façade serves: JSONRPC 1.0 only, streaming off, bearer auth."""
    return AgentCard(
        name=settings.a2a_card_name,
        description=settings.a2a_card_description,
        version="1.0",
        supported_interfaces=[
            AgentInterface(
                url=settings.a2a_public_url,
                protocol_binding=BINDING,
                protocol_version=PROTOCOL_VERSION,
            )
        ],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id=SKILL_ID,
                name="Containment probe",
                description="Single-turn text request to the fronted Foundry hosted agent.",
                tags=[],
                examples=[],
            )
        ],
        security_schemes={
            BEARER_SCHEME: SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer")
            )
        },
        security_requirements=[SecurityRequirement(schemes={BEARER_SCHEME: StringList()})],
    )


class FacadeUser(User):  # type: ignore[misc]
    def __init__(self, principal_id: str) -> None:
        self._id = principal_id

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._id


class FacadeCallContextBuilder(DefaultServerCallContextBuilder):  # type: ignore[misc]
    """Carries the principal the auth middleware established into the A2A call context."""

    def build_user(self, request: Request) -> User:
        principal = getattr(request.state, "principal_id", None)
        return FacadeUser(principal) if principal else super().build_user(request)


class FacadeExecutor(AgentExecutor):  # type: ignore[misc]
    """One A2A message in, one Responses call, one task out. Stateless per turn."""

    def __init__(self, target: AgentTarget, contexts: ContextMap | None = None) -> None:
        self._target = target
        self._contexts = contexts if contexts is not None else ContextMap()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        if message is None:
            raise InvalidParamsError("a message is required")
        text = context.get_user_input()
        if not text.strip():
            raise InvalidParamsError("the message has no text")
        if len(text) > MAX_INPUT_CHARS:
            raise InvalidParamsError(f"the message exceeds {MAX_INPUT_CHARS} characters")

        task = context.current_task or new_task_from_user_message(message)
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        principal = context.call_context.user.user_name
        await updater.start_work()

        try:
            reply = await self._target.send(text)
        except TargetError as exc:
            logger.warning(
                "a2a downstream failed principal=%s task_id=%s category=%s http_status=%s",
                principal,
                task.id,
                exc.category,
                exc.status,
            )
            status = f" (HTTP {exc.status})" if exc.status is not None else ""
            await updater.failed(
                updater.new_agent_message(
                    [
                        new_text_part(
                            f"The call from the façade to the hosted agent failed: "
                            f"{exc.category}{status}. This says nothing about the "
                            "agent's own egress."
                        )
                    ]
                )
            )
            return

        self._contexts.remember(task.context_id, reply.response_id)
        logger.info(
            "a2a task completed principal=%s task_id=%s downstream_response_id=%s tool_run_ids=%s",
            principal,
            task.id,
            reply.response_id,
            ",".join(reply.tool_run_ids) or "-",
        )
        metadata: dict[str, Any] = {"tool_run_ids": list(reply.tool_run_ids)}
        if reply.response_id:
            metadata["downstream_response_id"] = reply.response_id
        await updater.add_artifact([new_text_part(reply.text)], name="response", metadata=metadata)
        await updater.complete(updater.new_agent_message([new_text_part(reply.text)], metadata))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError(
            "CancelTask is not supported: the façade makes one non-cancellable call per message."
        )


class AuthMiddleware:
    """Rejects every request but the health probe unless the Authenticator accepts it."""

    def __init__(self, app: ASGIApp, authenticator: Authenticator) -> None:
        self._app = app
        self._auth = authenticator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == HEALTH_PATH:
            await self._app(scope, receive, send)
            return
        header = ""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                header = value.decode("latin-1")
                break
        principal = self._auth.authenticate(header)
        if principal is None:
            response = PlainTextResponse(
                "unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["principal_id"] = principal.id
        await self._app(scope, receive, send)


async def _healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def build_app(
    settings: FacadeSettings,
    target: AgentTarget,
    authenticator: Authenticator | None = None,
) -> Starlette:
    card = build_card(settings)
    handler = DefaultRequestHandler(
        agent_executor=FacadeExecutor(target),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [
        Route(HEALTH_PATH, _healthz, methods=["GET"]),
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, rpc_url="/", context_builder=FacadeCallContextBuilder()),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(
        AuthMiddleware,
        authenticator=authenticator or SharedTokenAuthenticator(settings.a2a_token),
    )
    return app
