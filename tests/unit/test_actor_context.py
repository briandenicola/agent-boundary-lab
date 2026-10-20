"""Offline tests for the actor-context contract (WP-1, issue #4). No network, no I/O."""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from containment_demo.actor_context import (
    MAX_LIFETIME,
    ActorContext,
    ActorContextError,
    ActorContextStore,
    AuthorizationIntent,
    AuthorizationStatus,
    issue,
    status_from_http,
    with_status,
)

RUN_ID = "harness-abc123def456"
ALIAS = "allowed-tester"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)

#: The only fields this contract may ever carry. If this set grows, it must still be
#: display-safe -- no raw token, header, or claim data.
SAFE_FIELDS = {
    "demo_run_id",
    "actor_alias",
    "authorization_intent",
    "authorization_status",
    "issued_at",
    "expires_at",
}


def _context(**overrides: object) -> ActorContext:
    values: dict[str, object] = {
        "demo_run_id": RUN_ID,
        "actor_alias": ALIAS,
        "authorization_intent": AuthorizationIntent.ALLOWED,
        "authorization_status": AuthorizationStatus.PENDING,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    return ActorContext(**values)  # type: ignore[arg-type]


def test_only_safe_fields_are_defined() -> None:
    assert {f.name for f in fields(ActorContext)} == SAFE_FIELDS


def test_valid_context_round_trips() -> None:
    context = _context()
    assert context.demo_run_id == RUN_ID
    assert context.authorization_intent is AuthorizationIntent.ALLOWED
    assert not context.is_expired(now=NOW + timedelta(minutes=1))
    assert context.is_expired(now=NOW + timedelta(minutes=10))


@pytest.mark.parametrize("bad_id", ["", "has space", "slash/es", "x" * 65, "..", None])
def test_invalid_run_id_rejected(bad_id: str | None) -> None:
    with pytest.raises(ActorContextError, match="run_id_invalid"):
        _context(demo_run_id=bad_id)


@pytest.mark.parametrize("bad_alias", ["", "has space", "x" * 65, "emoji🙂", None])
def test_invalid_alias_rejected(bad_alias: str | None) -> None:
    with pytest.raises(ActorContextError, match="alias_invalid"):
        _context(actor_alias=bad_alias)


def test_intent_must_be_enum_member() -> None:
    with pytest.raises(ActorContextError, match="intent_invalid"):
        _context(authorization_intent="allowed")


def test_status_must_be_enum_member() -> None:
    with pytest.raises(ActorContextError, match="status_invalid"):
        _context(authorization_status="authorized")


def test_naive_timestamps_rejected() -> None:
    naive = datetime(2026, 10, 19, 12, 0)  # intentionally naive, for the test
    with pytest.raises(ActorContextError, match="requires_timezone"):
        _context(issued_at=naive)
    with pytest.raises(ActorContextError, match="requires_timezone"):
        _context(expires_at=naive)


def test_expiry_must_be_after_issued() -> None:
    with pytest.raises(ActorContextError, match="lifetime_not_positive"):
        _context(issued_at=NOW, expires_at=NOW)
    with pytest.raises(ActorContextError, match="lifetime_not_positive"):
        _context(issued_at=NOW, expires_at=NOW - timedelta(seconds=1))


def test_lifetime_is_bounded() -> None:
    with pytest.raises(ActorContextError, match="lifetime_exceeds_maximum"):
        _context(issued_at=NOW, expires_at=NOW + MAX_LIFETIME + timedelta(seconds=1))
    # Exactly the maximum is fine.
    _context(issued_at=NOW, expires_at=NOW + MAX_LIFETIME)


def test_issue_sets_pending_status_and_bounded_window() -> None:
    context = issue(RUN_ID, ALIAS, AuthorizationIntent.DENIED, now=NOW)
    assert context.authorization_status is AuthorizationStatus.PENDING
    assert context.authorization_intent is AuthorizationIntent.DENIED
    assert context.issued_at == NOW
    assert context.expires_at == NOW + MAX_LIFETIME


def test_issue_rejects_lifetime_over_maximum() -> None:
    with pytest.raises(ActorContextError, match="lifetime_exceeds_maximum"):
        issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, lifetime=MAX_LIFETIME * 2, now=NOW)


def test_with_status_returns_new_validated_copy() -> None:
    context = issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, now=NOW)
    authorized = with_status(context, AuthorizationStatus.AUTHORIZED)
    assert authorized is not context
    assert authorized.authorization_status is AuthorizationStatus.AUTHORIZED
    # Original is untouched -- the contract is frozen.
    assert context.authorization_status is AuthorizationStatus.PENDING


def test_store_put_and_require_round_trip() -> None:
    store = ActorContextStore()
    context = issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, now=NOW)
    store.put(context)
    assert store.require(RUN_ID, now=NOW) == context


def test_store_require_missing_context_raises() -> None:
    store = ActorContextStore()
    with pytest.raises(ActorContextError, match="not_found"):
        store.require(RUN_ID, now=NOW)


def test_store_require_expired_context_raises() -> None:
    store = ActorContextStore()
    context = issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, now=NOW)
    store.put(context)
    with pytest.raises(ActorContextError, match="expired"):
        store.require(RUN_ID, now=NOW + MAX_LIFETIME + timedelta(seconds=1))


def test_store_get_rejects_invalid_run_id() -> None:
    store = ActorContextStore()
    with pytest.raises(ActorContextError, match="run_id_invalid"):
        store.get("not a valid id")


def test_store_put_overwrites_same_run_id() -> None:
    store = ActorContextStore()
    first = issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, now=NOW)
    store.put(first)
    second = with_status(first, AuthorizationStatus.AUTHORIZED)
    store.put(second)
    assert store.require(RUN_ID, now=NOW).authorization_status is AuthorizationStatus.AUTHORIZED


class TestStatusFromHttp:
    """WP-3, issue #4: the only safe vocabulary a harness/UI may use for the policy
    authorization label. Must never claim a pass without an explicit 200."""

    def test_200_maps_to_authorized(self) -> None:
        assert status_from_http(200) is AuthorizationStatus.AUTHORIZED

    def test_403_maps_to_denied(self) -> None:
        assert status_from_http(403) is AuthorizationStatus.DENIED

    @pytest.mark.parametrize("status", [401, 404, 500, None])
    def test_everything_else_maps_to_pending_never_a_pass(self, status: int | None) -> None:
        assert status_from_http(status) is AuthorizationStatus.PENDING
