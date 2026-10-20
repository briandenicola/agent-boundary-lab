"""On-behalf-of exchange for the signed-in user (issue #4).

The ingress (oauth2-proxy) hands the harness the user's access token in the
``x-auth-request-access-token`` header. The harness exchanges it with MSAL for a token
whose audience is the policy API, and carries that token to the tool call through a
context variable. The token is never logged, returned or stored beyond the turn.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any

from containment_demo.harness.settings import HarnessSettings

INGRESS_TOKEN_HEADER = "x-auth-request-access-token"  # noqa: S105

#: Set by the chat handler before the responder task is created; read by the harness tools.
current_user_token: ContextVar[str | None] = ContextVar("harness_user_token", default=None)


class OboError(Exception):
    """OBO failed. ``code`` is the Entra error code (or a local label); never a token."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _exchange(settings: HarnessSettings, assertion: str) -> str:
    import msal

    app = msal.ConfidentialClientApplication(
        settings.obo_client_id,
        client_credential=settings.obo_client_secret.get_secret_value(),
        authority=f"https://login.microsoftonline.com/{settings.obo_tenant_id}",
    )
    result: dict[str, Any] = app.acquire_token_on_behalf_of(
        user_assertion=assertion, scopes=[settings.obo_scope]
    )
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        code = result.get("error")
        raise OboError(code[:64] if isinstance(code, str) and code else "obo_failed")
    return token


async def acquire_user_token(settings: HarnessSettings, assertion: str | None) -> str | None:
    """The OBO token for this turn, or None when OBO is not configured (legacy)."""
    if not settings.obo_enabled:
        return None
    if not assertion:
        raise OboError("ingress_access_token_missing")
    try:
        return await asyncio.to_thread(_exchange, settings, assertion)
    except OboError:
        raise
    except Exception:
        raise OboError("obo_exchange_failed") from None
