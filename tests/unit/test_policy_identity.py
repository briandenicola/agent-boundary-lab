"""Both business routes use the real shared verifier, never a spoofable user header."""

from __future__ import annotations

import io
import json
import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from services.policy_api import main as policy
from services.test_receiver import main as receiver

from containment_demo.delegated_auth import AccessGuard, TokenContract, TokenVerifier

TENANT = "00000000-0000-4000-8000-000000000001"
CLIENT = "00000000-0000-4000-8000-000000000002"
USER = "00000000-0000-4000-8000-000000000003"
OTHER = "00000000-0000-4000-8000-000000000004"
CONTRACT = TokenContract(TENANT, "api://synthetic-policy", "policy.read", frozenset({CLIENT}))


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def token(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    return jwt.encode(
        {
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
            "aud": CONTRACT.audience,
            "tid": TENANT,
            "oid": USER,
            "azp": CLIENT,
            "scp": CONTRACT.scope,
            "nbf": int(time.time()) - 30,
            "exp": int(time.time()) + 300,
            **overrides,
        },
        key,
        algorithm="RS256",
        headers={"kid": "policy-test-key"},
    )


@pytest.fixture
def protected(signing_key: rsa.RSAPrivateKey) -> Iterator[TestClient]:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    validator = TokenVerifier(
        CONTRACT,
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"keys": [{**public, "kid": "policy-test-key"}]})
        ),
    )
    guard = AccessGuard(validator, frozenset({USER}))
    with TestClient(policy.create_app(guard=guard)) as client:
        yield client


@pytest.mark.parametrize("path", ["/policy", "/policy/synthetic-run-1"])
def test_assigned_user_can_read_every_policy_route(
    protected: TestClient, signing_key: rsa.RSAPrivateKey, path: str
) -> None:
    response = protected.get(path, headers={"Authorization": "Bearer " + token(signing_key)})
    assert response.status_code == 200
    assert response.json()["policy"]["policy_id"] == "SVC-DEMO-0001"
    assert response.json()["user_object_id"] == USER
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path", ["/policy", "/policy/synthetic-run-1"])
def test_missing_bearer_and_forged_identity_headers_are_rejected(
    protected: TestClient, path: str
) -> None:
    response = protected.get(
        path,
        headers={
            "X-MS-CLIENT-PRINCIPAL-ID": USER,
            "X-MS-USER-IDENTITY": USER,
            "X-Demo-UI": "1",
            "X-Demo-Token": "synthetic-shared-demo-token",
        },
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["determination"] == "identity_only"
    assert "policy" not in response.json()


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"oid": OTHER}, 403),
        ({"azp": OTHER}, 403),
        ({"aud": "https://ai.azure.com"}, 401),
        ({"tid": OTHER}, 401),
        ({"exp": 1}, 401),
        ({"scp": "unrelated.scope"}, 403),
        ({"idtyp": "app"}, 401),
    ],
)
def test_authentication_and_authorization_are_separate(
    protected: TestClient,
    signing_key: rsa.RSAPrivateKey,
    overrides: dict[str, Any],
    status: int,
) -> None:
    response = protected.get(
        "/policy/synthetic-run-1",
        headers={"Authorization": "Bearer " + token(signing_key, **overrides)},
    )
    assert response.status_code == status
    assert response.json()["determination"] == "identity_only"
    assert "policy" not in response.json()


def test_health_is_the_only_unprotected_business_surface(protected: TestClient) -> None:
    assert protected.get("/healthz").status_code == 200
    assert protected.get("/unknown").status_code == 401


def test_denial_logs_are_not_success_receipts_and_contain_no_identity_or_bearer(
    protected: TestClient, signing_key: rsa.RSAPrivateKey
) -> None:
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    policy.logger.addHandler(handler)
    denied = token(signing_key, oid=OTHER)
    try:
        response = protected.get(
            "/policy/" + denied,
            headers={"Authorization": "Bearer " + denied, "X-Demo-Run-Id": denied},
        )
        assert response.status_code == 403
        record = json.loads(output.getvalue())
        assert record["event"] == "authorization_decision"
        assert record["determination"] == "identity_only"
        assert record["path"] == "/policy/{run_id}"
        assert record["demo_run_id"] == ""
        # The verified object id of the denied user is shown on purpose (owner decision).
        assert record["user_object_id"] == OTHER
        assert response.json()["user_object_id"] == OTHER
        for private in (denied, USER, CLIENT, "Bearer"):
            assert private not in output.getvalue() + response.text
    finally:
        policy.logger.removeHandler(handler)


def test_legacy_policy_and_receiver_behavior_unchanged() -> None:
    with TestClient(policy.app) as client:
        assert client.get("/policy").status_code == 200
    with TestClient(receiver.app) as client:
        assert client.post("/ingest", content=b"synthetic").status_code == 202
