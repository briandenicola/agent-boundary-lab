"""WP-2: policy API authorization via the WP-1 actor-context contract.

Offline only -- no network. Covers allowed vs denied actor behavior through the
policy route boundary, explicit 401/403 classes, and the identity-only determination
label (never a containment claim).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from services.policy_api import main as policy

from containment_demo.actor_context import (
    ActorContextStore,
    AuthorizationIntent,
    AuthorizationStatus,
    issue,
)

RUN_ID = "actor-run-0001"
ALIAS = "allowed-tester"
NOW = datetime.now(UTC)


@pytest.fixture
def store() -> ActorContextStore:
    return ActorContextStore()


@pytest.fixture
def client(store: ActorContextStore) -> Iterator[TestClient]:
    with TestClient(policy.create_app(actor_store=store)) as test_client:
        yield test_client


def test_allowed_actor_context_authorizes_the_policy_route(
    client: TestClient, store: ActorContextStore
) -> None:
    store.put(issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, now=NOW))
    response = client.get(f"/policy/{RUN_ID}")
    assert response.status_code == 200
    assert response.json()["policy"]["policy_id"] == "SVC-DEMO-0001"
    # The decision is recorded back onto the context for evidence, not inferred.
    assert store.require(RUN_ID).authorization_status is AuthorizationStatus.AUTHORIZED


def test_denied_actor_context_is_rejected_at_the_authorization_boundary(
    client: TestClient, store: ActorContextStore
) -> None:
    store.put(issue(RUN_ID, "denied-tester", AuthorizationIntent.DENIED, now=NOW))
    response = client.get(f"/policy/{RUN_ID}")
    assert response.status_code == 403
    body = response.json()
    assert body["error"] == "actor_context_denied"
    assert body["determination"] == "identity_only"
    assert "policy" not in body
    assert store.require(RUN_ID).authorization_status is AuthorizationStatus.DENIED


def test_missing_actor_context_is_rejected_with_401(client: TestClient) -> None:
    response = client.get(f"/policy/{RUN_ID}")
    assert response.status_code == 401
    assert response.json()["error"] == "actor_context_not_found"
    assert response.json()["determination"] == "identity_only"


def test_expired_actor_context_is_rejected_with_401(
    client: TestClient, store: ActorContextStore
) -> None:
    store.put(issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, now=NOW - timedelta(minutes=20)))
    response = client.get(f"/policy/{RUN_ID}")
    assert response.status_code == 401
    assert response.json()["error"] == "actor_context_expired"


def test_no_run_id_available_is_rejected_with_401_not_a_containment_signal(
    client: TestClient,
) -> None:
    response = client.get("/policy")
    assert response.status_code == 401
    assert response.json()["error"] == "actor_context_run_id_missing"
    assert response.json()["determination"] == "identity_only"


def test_header_run_marker_is_accepted_as_a_fallback_lookup_key(
    client: TestClient, store: ActorContextStore
) -> None:
    store.put(issue(RUN_ID, ALIAS, AuthorizationIntent.ALLOWED, now=NOW))
    response = client.get("/policy", headers={"x-demo-run-id": RUN_ID})
    assert response.status_code == 200


def test_healthz_remains_the_only_unauthenticated_route(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200
    assert client.get("/unknown").status_code == 401


def test_legacy_default_app_is_unaffected_by_actor_context_integration() -> None:
    with TestClient(policy.app) as legacy_client:
        assert legacy_client.get("/policy").status_code == 200
