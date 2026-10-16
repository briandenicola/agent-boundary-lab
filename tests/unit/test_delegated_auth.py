"""Real JWT signatures and mocked HTTPS only. No tenant, login, or discovery calls."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from containment_demo import delegated_auth
from containment_demo.delegated_auth import (
    AccessGuard,
    AuthError,
    TokenContract,
    TokenVerifier,
    bearer_token,
    configured_guard,
    decode_delegated,
)

TENANT = "00000000-0000-4000-8000-000000000001"
CLIENT = "00000000-0000-4000-8000-000000000002"
USER = "00000000-0000-4000-8000-000000000003"
OTHER = "00000000-0000-4000-8000-000000000004"
CONTRACT = TokenContract(TENANT, "api://synthetic-policy", "policy.read", frozenset({CLIENT}))


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def keys(key: rsa.RSAPrivateKey) -> dict[str, Any]:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {"keys": [{**public, "kid": "synthetic-key", "use": "sig", "alg": "RS256"}]}


def claims(**overrides: Any) -> dict[str, Any]:
    return {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": CONTRACT.audience,
        "tid": TENANT,
        "oid": USER,
        "azp": CLIENT,
        "scp": "policy.read",
        "exp": int(time.time()) + 300,
        "nbf": int(time.time()) - 30,
        **overrides,
    }


def signed(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), key, algorithm="RS256", headers={"kid": "synthetic-key"})


def verifier(key: rsa.RSAPrivateKey) -> TokenVerifier:
    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == (
            f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"
        )
        assert "authorization" not in request.headers
        return httpx.Response(200, json=keys(key))

    return TokenVerifier(CONTRACT, transport=httpx.MockTransport(respond))


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"aud": "api://another-service"}, 401),
        ({"aud": [CONTRACT.audience, "api://another-service"]}, 401),
        ({"tid": OTHER}, 401),
        ({"iss": f"https://login.microsoftonline.com/{OTHER}/v2.0"}, 401),
        ({"exp": 1}, 401),
        ({"nbf": int(time.time()) + 3600}, 401),
        ({"idtyp": "app"}, 401),
        ({"scp": None}, 401),
        ({"scp": "policy.read.extra"}, 403),
        ({"azp": OTHER}, 403),
        ({"appid": OTHER}, 403),
        ({"oid": "not-a-user"}, 401),
        ({"oid": None}, 401),
        ({"nbf": False}, 401),
        ({"exp": float("inf")}, 401),
    ],
)
def test_signed_but_invalid_tokens_are_rejected(
    key: rsa.RSAPrivateKey, overrides: dict[str, Any], status: int
) -> None:
    with pytest.raises(AuthError) as error:
        decode_delegated(signed(key, **overrides), keys(key), CONTRACT)
    assert error.value.status == status
    assert "eyJ" not in str(error.value)


def test_valid_user_is_not_a_claim_dump(key: rsa.RSAPrivateKey) -> None:
    user = decode_delegated(signed(key), keys(key), CONTRACT)
    assert (user.tenant_id, user.object_id, user.client_id) == (TENANT, USER, CLIENT)
    assert USER not in repr(user)
    assert "scp" not in repr(user)


def test_v1_appid_contract_is_supported(key: rsa.RSAPrivateKey) -> None:
    payload = claims(iss=f"https://sts.windows.net/{TENANT}/", appid=CLIENT)
    payload.pop("azp")
    token = jwt.encode(payload, key, algorithm="RS256", headers={"kid": "synthetic-key"})
    assert decode_delegated(token, keys(key), CONTRACT).client_id == CLIENT


def test_signature_key_algorithm_and_duplicate_keys_are_checked(key: rsa.RSAPrivateKey) -> None:
    forged = signed(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    symmetric = jwt.encode(
        claims(),
        "synthetic-test-key-of-at-least-thirty-two-bytes",
        algorithm="HS256",
        headers={"kid": "synthetic-key"},
    )
    duplicate = {"keys": keys(key)["keys"] * 2}
    for token, jwks in ((forged, keys(key)), (symmetric, keys(key)), (signed(key), duplicate)):
        with pytest.raises(AuthError):
            decode_delegated(token, jwks, CONTRACT)


@pytest.mark.parametrize(
    "header", [None, "", "Basic secret", "Bearer", "Bearer a b", "Bearer " + "a" * 16385]
)
def test_bearer_only_no_query_or_shared_token_fallback(header: str | None) -> None:
    with pytest.raises(AuthError):
        bearer_token(header)


async def test_requests_and_session_keys_are_user_isolated(key: rsa.RSAPrivateKey) -> None:
    validator = verifier(key)
    try:
        guard = AccessGuard(validator, frozenset({USER, OTHER}))
        first, second = await asyncio.gather(
            guard.authorize("Bearer " + signed(key)),
            guard.authorize("Bearer " + signed(key, oid=OTHER)),
        )
        assert first.user.object_id == USER
        assert second.user.object_id == OTHER
        assert first.user.session_user_id != second.user.session_user_id
        assert first.bearer.get_secret_value() != second.bearer.get_secret_value()
        assert "eyJ" not in repr(first) + repr(second)
        assert USER not in repr(first)
    finally:
        await validator.close()


async def test_authenticated_user_still_requires_assignment(key: rsa.RSAPrivateKey) -> None:
    validator = verifier(key)
    try:
        guard = AccessGuard(validator, frozenset({USER}))
        with pytest.raises(AuthError, match="user_not_authorized") as error:
            await guard.authorize("Bearer " + signed(key, oid=OTHER))
        assert error.value.status == 403
    finally:
        await validator.close()


@pytest.mark.parametrize("status", [302, 403, 500])
async def test_key_failure_is_unavailable_not_bad_credentials(
    key: rsa.RSAPrivateKey, status: int
) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://unrelated.invalid"},
            text="synthetic-private-server-message",
        )

    validator = TokenVerifier(CONTRACT, transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(AuthError) as error:
            await validator.verify(signed(key))
        assert error.value.status == 503
        assert len(calls) == 1
        assert "synthetic-private" not in str(error.value)
        assert not validator.http.follow_redirects
        assert validator.http.timeout == httpx.Timeout(5)
    finally:
        await validator.close()


async def test_public_keys_cached_not_tokens_or_users(key: rsa.RSAPrivateKey) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=keys(key))

    validator = TokenVerifier(CONTRACT, transport=httpx.MockTransport(respond))
    try:
        await validator.verify(signed(key))
        await validator.verify(signed(key, oid=OTHER))
        assert len(calls) == 1
        assert "eyJ" not in repr(vars(validator))
    finally:
        await validator.close()


async def test_expired_key_cache_is_not_used_during_outage(
    key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [0.0]
    monkeypatch.setattr(delegated_auth, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=keys(key)) if len(calls) == 1 else httpx.Response(503)

    validator = TokenVerifier(CONTRACT, transport=httpx.MockTransport(respond))
    try:
        await validator.verify(signed(key))
        clock[0] = 301
        with pytest.raises(AuthError) as error:
            await validator.verify(signed(key))
        assert error.value.status == 503
        assert len(calls) == 2
    finally:
        await validator.close()


async def test_unknown_key_refresh_is_throttled_and_rotation_is_supported(
    key: rsa.RSAPrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [0.0]
    monkeypatch.setattr(delegated_auth, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        public = keys(key)
        if len(calls) > 1:
            public["keys"][0]["kid"] = "rotated-key"
        return httpx.Response(200, json=public)

    validator = TokenVerifier(CONTRACT, transport=httpx.MockTransport(respond))
    rotated = jwt.encode(claims(), key, algorithm="RS256", headers={"kid": "rotated-key"})
    try:
        await validator.verify(signed(key))
        for _ in range(3):
            with pytest.raises(AuthError):
                await validator.verify(rotated)
        assert len(calls) == 1
        clock[0] = 31
        assert (await validator.verify(rotated)).object_id == USER
        assert len(calls) == 2
    finally:
        await validator.close()


def test_empty_assignment_or_client_configuration_fails() -> None:
    with pytest.raises(ValueError, match="clients_required"):
        TokenContract(TENANT, CONTRACT.audience, CONTRACT.scope, frozenset())
    with pytest.raises(ValueError, match="uuid_invalid"):
        TokenContract("invalid", CONTRACT.audience, CONTRACT.scope, frozenset({CLIENT}))


def test_identity_config_cannot_silently_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    assert configured_guard("SYNTHETIC_POLICY") is None
    monkeypatch.setenv("SYNTHETIC_POLICY_TENANT_ID", TENANT)
    with pytest.raises(ValueError, match="explicit_delegated_mode"):
        configured_guard("SYNTHETIC_POLICY")
    monkeypatch.setenv("SYNTHETIC_POLICY_AUTH_MODE", "delegated")
    with pytest.raises(ValueError, match="incomplete"):
        configured_guard("SYNTHETIC_POLICY")
