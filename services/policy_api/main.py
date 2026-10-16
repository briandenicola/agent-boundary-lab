"""Allowlisted policy API.

One of the two controlled destinations. This one is on the egress allowlist, so a call
to it is expected to succeed in every mode, including Enforced. If it fails under
Enforced the allowlist is wrong and the run is a misconfiguration, not a containment
result.

It returns a fixed synthetic policy. The content is irrelevant to the experiment; what
matters is that the call completes and leaves a receipt carrying the run marker, so the
successful half of the demo is positively evidenced rather than merely assumed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from containment_demo.delegated_auth import AccessGuard, AuthError, configured_guard

SERVICE_NAME = "policy-api"

#: Entirely synthetic. No customer data, in any field, ever.
SERVICING_POLICY = {
    "policy_id": "SVC-DEMO-0001",
    "product": "synthetic-demo-account",
    "servicing_tier": "standard",
    "max_adjustment_amount": 250,
    "requires_second_approval_above": 100,
    "notes": "Synthetic policy for the containment demo. Not a real servicing rule.",
}


def _configure_logging() -> logging.Logger:
    """Emit one JSON object per line so receipts are queryable without parsing prose."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(SERVICE_NAME)
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


logger = _configure_logging()


def _path_run_id(run_id: str) -> str:
    """Run id from the URL path (GATE 0 experiment). Unsafe values are dropped, not logged."""
    return run_id if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", run_id) else ""


def _run_marker(request: Request) -> str:
    """The correlation key, from either the header or the query string.

    There is no documented correlation key between platform egress decisions and
    application traces, so this marker is the only one we control. Both carriers are
    accepted so a receipt is still attributable if one is stripped in transit.
    """
    path_id = _path_run_id(request.path_params.get("run_id", ""))
    marker = (
        path_id
        or request.headers.get("x-demo-run-id")
        or request.query_params.get("demo_run_id")
        or ""
    )
    return _path_run_id(marker) if getattr(request.state, "identity_protected", False) else marker


def _receipt(request: Request, **extra: Any) -> dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "event": "receipt",
        "received_at": datetime.now(UTC).isoformat(),
        "demo_run_id": _run_marker(request),
        "method": request.method,
        "path": ("/policy/{run_id}" if request.url.path.startswith("/policy/") else "/policy")
        if getattr(request.state, "identity_protected", False)
        else request.url.path,
        **extra,
    }


async def healthz() -> dict[str, str]:
    """Liveness only. Not logged as a receipt, so probes cannot be mistaken for traffic."""
    return {"status": "ok", "service": SERVICE_NAME}


async def get_policy(request: Request) -> JSONResponse:
    """Return the fixed synthetic policy and record that the call arrived."""
    logger.info(json.dumps(_receipt(request, outcome="served")))
    return JSONResponse(
        {
            "demo_run_id": _run_marker(request),
            "served_at": datetime.now(UTC).isoformat(),
            "policy": SERVICING_POLICY,
        }
    )


def create_app(*, guard: AccessGuard | None = None) -> FastAPI:
    guard = guard if guard is not None else configured_guard("POLICY_API")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            if guard is not None:
                logger.info(
                    json.dumps(
                        {
                            "service": SERVICE_NAME,
                            "event": "identity_configuration",
                            "auth_mode": "delegated",
                            "determination": "identity_only",
                        }
                    )
                )
            yield
        finally:
            if guard is not None:
                await guard.verifier.close()

    application = FastAPI(
        title="Containment demo policy API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    if guard is not None:
        from collections.abc import Awaitable, Callable

        from starlette.responses import Response

        @application.middleware("http")
        async def require_user(
            request: Request, call_next: Callable[[Request], Awaitable[Response]]
        ) -> Response:
            if request.url.path == "/healthz":
                return await call_next(request)
            request.state.identity_protected = True
            try:
                context = await guard.authorize(request.headers.get("authorization"))
                request.state.delegated_user = context.user
            except AuthError as error:
                logger.info(
                    json.dumps(
                        _receipt(
                            request,
                            event="authorization_decision",
                            outcome="unavailable" if error.status == 503 else "denied",
                            auth_error=error.code,
                            determination="identity_only",
                        )
                    )
                )
                headers = {"Cache-Control": "no-store"}
                if error.status == 401:
                    headers["WWW-Authenticate"] = "Bearer"
                return JSONResponse(
                    {"error": error.code, "determination": "identity_only"},
                    status_code=error.status,
                    headers=headers,
                )
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

    application.add_api_route("/healthz", healthz, methods=["GET"])
    application.add_api_route("/policy", get_policy, methods=["GET"])
    application.add_api_route("/policy/{run_id}", get_policy, methods=["GET"])
    return application


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",  # noqa: S104
        port=int(os.environ.get("PORT", "8080")),
        access_log=False,
    )


if __name__ == "__main__":
    main()
