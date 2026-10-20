"""Actor-context contract for the allowed/denied demo path (WP-1, issue #4).

This is deliberately small and does **not** perform authorization. It only gives the
harness and the policy API a shared, safe way to describe "which actor is this
``demo_run_id`` run for, and what should happen to it" so that WP-2 can wire real
authorization decisions against it. Enforcement, 401/403 semantics and any actual
token/claim handling stay out of scope here — see ``delegated_auth.py`` for that.

Safety rules, enforced by validation rather than by convention:

- Keyed by ``demo_run_id``, the same synthetic correlation marker used everywhere else
  in this demo (``settings.py``, ``telemetry.py``). No other identifier is accepted.
- Only safe, display-able fields are stored: an actor alias, the intended and actual
  authorization outcome, and a bounded issued/expiry window. There is no field for a
  raw token, an authorization header, or a claim dump, and none should ever be added —
  that would turn this contract into exactly the kind of secret-carrying state it is
  meant to avoid.
- Lifetime is bounded and checked, so a stale context cannot be resolved and silently
  treated as current.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

#: Same shape as the run id accepted elsewhere (settings.py, services/policy_api/main.py).
_RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")
#: An alias is for display only (e.g. "allowed-tester"); still bounded and printable.
_ALIAS_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")

#: No actor context may outlive this. A demo run is a few minutes of wall-clock time;
#: anything longer is a sign the caller is reusing a context instead of issuing a new
#: one, which this contract refuses to support.
MAX_LIFETIME = timedelta(minutes=15)


class AuthorizationIntent(StrEnum):
    """What this run is *supposed* to demonstrate. Set once, at issuance, by the caller
    that already knows which actor it is driving (e.g. the harness's allowed/denied
    case selection). Never inferred from a token."""

    ALLOWED = "allowed"
    DENIED = "denied"


class AuthorizationStatus(StrEnum):
    """What actually happened, as reported by the component that made the decision
    (WP-2's policy API authorization, in the future). This is an identity-authorization
    outcome, not a containment result -- see docs/issue-4-demo-readiness.md."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    DENIED = "denied"
    EXPIRED = "expired"


class ActorContextError(ValueError):
    """Raised for any invalid, missing, or expired actor context. The message is always
    a safe code, never a value from the rejected input."""


def _checked(pattern: re.Pattern[str], value: str, code: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ActorContextError(code)
    return value


@dataclass(frozen=True)
class ActorContext:
    """The full, safe contract for one demo run's actor. Every field is something that
    could be printed in a presenter transcript without redaction."""

    demo_run_id: str
    actor_alias: str
    authorization_intent: AuthorizationIntent
    authorization_status: AuthorizationStatus
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _checked(_RUN_ID_RE, self.demo_run_id, "actor_context_run_id_invalid")
        _checked(_ALIAS_RE, self.actor_alias, "actor_context_alias_invalid")
        if not isinstance(self.authorization_intent, AuthorizationIntent):
            raise ActorContextError("actor_context_intent_invalid")
        if not isinstance(self.authorization_status, AuthorizationStatus):
            raise ActorContextError("actor_context_status_invalid")
        for value in (self.issued_at, self.expires_at):
            if not isinstance(value, datetime) or value.tzinfo is None:
                raise ActorContextError("actor_context_timestamp_requires_timezone")
        lifetime = self.expires_at - self.issued_at
        if lifetime <= timedelta(0):
            raise ActorContextError("actor_context_lifetime_not_positive")
        if lifetime > MAX_LIFETIME:
            raise ActorContextError("actor_context_lifetime_exceeds_maximum")

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now if now is not None else datetime.now(UTC)) >= self.expires_at


def issue(
    demo_run_id: str,
    actor_alias: str,
    authorization_intent: AuthorizationIntent,
    *,
    lifetime: timedelta = MAX_LIFETIME,
    now: datetime | None = None,
) -> ActorContext:
    """Create a new context in ``PENDING`` status. The only constructor callers outside
    this module should use; it fixes ``issued_at``/``expires_at`` consistently."""
    issued_at = now if now is not None else datetime.now(UTC)
    return ActorContext(
        demo_run_id=demo_run_id,
        actor_alias=actor_alias,
        authorization_intent=authorization_intent,
        authorization_status=AuthorizationStatus.PENDING,
        issued_at=issued_at,
        expires_at=issued_at + lifetime,
    )


def with_status(context: ActorContext, status: AuthorizationStatus) -> ActorContext:
    """Return a copy of ``context`` with a new ``authorization_status``. Re-validates
    the result, so this can never be used to smuggle an unsafe field in."""
    return replace(context, authorization_status=status)


def status_from_http(http_status: int | None) -> AuthorizationStatus:
    """Map an observed HTTP status from the policy API route to a safe, display-only
    authorization status (WP-3, issue #4).

    This is the only vocabulary a harness/UI may use to describe what the policy
    authorization boundary (WP-2, ``services/policy_api/main.py``) decided for an
    actor. It never echoes the raw status and never claims ``AUTHORIZED`` without an
    explicit ``200`` -- anything ambiguous (a 401, a transport failure, or no call
    having been observed at all) maps to ``PENDING``, never to a pass. This is an
    identity-authorization label only; it must never be read as, or substituted for, a
    containment determination.
    """
    if http_status == 200:
        return AuthorizationStatus.AUTHORIZED
    if http_status == 403:
        return AuthorizationStatus.DENIED
    return AuthorizationStatus.PENDING


class ActorContextStore:
    """Minimal in-memory registry keyed by ``demo_run_id``.

    This is the integration point WP-2 is expected to use from the policy API (and the
    harness, for issuance) once real authorization wiring lands. It intentionally does
    no I/O, no persistence, and no authorization logic of its own -- it only resolves a
    run id to its actor context, or fails safely if that context is missing or expired.
    """

    def __init__(self) -> None:
        self._contexts: dict[str, ActorContext] = {}

    def put(self, context: ActorContext) -> None:
        self._contexts[context.demo_run_id] = context

    def get(self, demo_run_id: str) -> ActorContext | None:
        _checked(_RUN_ID_RE, demo_run_id, "actor_context_run_id_invalid")
        return self._contexts.get(demo_run_id)

    def require(self, demo_run_id: str, *, now: datetime | None = None) -> ActorContext:
        """Resolve a context or raise. Never returns an expired context."""
        context = self.get(demo_run_id)
        if context is None:
            raise ActorContextError("actor_context_not_found")
        if context.is_expired(now=now):
            raise ActorContextError("actor_context_expired")
        return context
