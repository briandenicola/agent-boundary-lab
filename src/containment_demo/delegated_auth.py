"""Shared delegated JWT validation. No token cache, discovery URLs, or workload fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import jwt
from pydantic import SecretStr


class AuthError(ValueError):
    def __init__(self, code: str, status: int = 401, user_object_id: str | None = None) -> None:
        self.code = code
        self.status = status
        # Only ever set from a signature-verified token's oid claim (never a secret).
        self.user_object_id = user_object_id
        super().__init__(code)


def _uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("identity_configuration_uuid_invalid") from None
    if not parsed.int or str(parsed) != value:
        raise ValueError("identity_configuration_uuid_invalid")
    return value


@dataclass(frozen=True)
class TokenContract:
    tenant_id: str
    audience: str
    scope: str
    client_ids: frozenset[str]

    def __post_init__(self) -> None:
        _uuid(self.tenant_id)
        if not self.client_ids:
            raise ValueError("identity_configuration_clients_required")
        for client in self.client_ids:
            _uuid(client)
        for value in (self.audience, self.scope):
            if (
                not value
                or len(value) > 512
                or any(char.isspace() or ord(char) < 32 for char in value)
            ):
                raise ValueError("identity_configuration_audience_or_scope_invalid")


@dataclass(frozen=True, repr=False)
class DelegatedUser:
    tenant_id: str
    object_id: str
    client_id: str

    def __repr__(self) -> str:
        return "DelegatedUser(<validated identity>)"

    @property
    def session_user_id(self) -> str:
        """Qualified ADK user key; not a display name or a logging field."""
        return hashlib.sha256(f"{self.tenant_id}:{self.object_id}".encode()).hexdigest()


@dataclass(frozen=True)
class DelegatedRequest:
    user: DelegatedUser
    bearer: SecretStr = field(repr=False, compare=False)


def bearer_token(header: str | None) -> str:
    if header is None:
        raise AuthError("authentication_required")
    parts = header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 16384:
        raise AuthError("invalid_bearer")
    return parts[1]


def decode_delegated(token: str, keys: dict[str, Any], contract: TokenContract) -> DelegatedUser:
    try:
        if not token or len(token) > 16384:
            raise AuthError("invalid_token")
        header = jwt.get_unverified_header(token)
        if (
            header.get("alg") != "RS256"
            or not isinstance(header.get("kid"), str)
            or not 1 <= len(header["kid"]) <= 256
        ):
            raise AuthError("invalid_token")
        matches = [
            key
            for key in keys["keys"]
            if isinstance(key, dict)
            and key.get("kid") == header["kid"]
            and key.get("kty") == "RSA"
            and key.get("use", "sig") == "sig"
            and key.get("alg", "RS256") == "RS256"
        ]
        if len(matches) != 1:
            raise AuthError("invalid_token")
        key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256")
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=contract.audience,
            issuer=[
                f"https://login.microsoftonline.com/{contract.tenant_id}/v2.0",
                f"https://sts.windows.net/{contract.tenant_id}/",
            ],
            options={
                "require": ["exp", "nbf", "aud", "iss", "tid", "oid", "scp"],
                "strict_aud": True,
            },
        )
        if (
            claims["tid"] != contract.tenant_id
            or claims.get("idtyp") == "app"
            or not isinstance(claims["scp"], str)
            or any(
                type(claims[name]) not in (int, float) or not math.isfinite(claims[name])
                for name in ("exp", "nbf")
            )
        ):
            raise AuthError("invalid_delegated_token")
        subject = _uuid(claims["oid"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, AuthError):
            raise
        raise AuthError("invalid_token") from None
    if contract.scope not in claims["scp"].split():
        raise AuthError("insufficient_scope", 403)
    client = claims.get("azp", claims.get("appid"))
    if (
        not isinstance(client, str)
        or client not in contract.client_ids
        or ("appid" in claims and claims["appid"] != client)
    ):
        raise AuthError("untrusted_oauth_client", 403)
    return DelegatedUser(contract.tenant_id, subject, client)


class TokenVerifier:
    """Caches only public signing keys. Expired keys are never used on fetch failure."""

    def __init__(
        self, contract: TokenContract, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.contract = contract
        self.http = httpx.AsyncClient(
            timeout=5, follow_redirects=False, trust_env=False, verify=True, transport=transport
        )
        self._keys: dict[str, Any] | None = None
        self._fetched_at = float("-inf")
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self.http.aclose()

    async def _load_keys(self, *, refresh: bool = False) -> dict[str, Any]:
        async with self._lock:
            age = time.monotonic() - self._fetched_at
            if self._keys is not None and age < 300 and (not refresh or age < 30):
                return self._keys
            try:
                url = (
                    f"https://login.microsoftonline.com/{self.contract.tenant_id}"
                    "/discovery/v2.0/keys"
                )
                async with self.http.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise AuthError("signing_keys_unavailable", 503)
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 262144:
                            raise AuthError("signing_keys_invalid", 503)
                keys = json.loads(content)
                if (
                    not isinstance(keys, dict)
                    or not isinstance(keys.get("keys"), list)
                    or not 1 <= len(keys["keys"]) <= 128
                    or not all(isinstance(key, dict) for key in keys["keys"])
                ):
                    raise AuthError("signing_keys_invalid", 503)
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                if isinstance(exc, AuthError):
                    raise
                raise AuthError("signing_keys_unavailable", 503) from None
            self._keys = keys
            self._fetched_at = time.monotonic()
            return keys

    async def verify(self, token: str) -> DelegatedUser:
        if not token or len(token) > 16384:
            raise AuthError("invalid_token")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AuthError("invalid_token") from None
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise AuthError("invalid_token")
        keys = await self._load_keys()
        if not any(key.get("kid") == header["kid"] for key in keys["keys"]):
            keys = await self._load_keys(refresh=True)
        return decode_delegated(token, keys, self.contract)


@dataclass(frozen=True)
class AccessGuard:
    verifier: TokenVerifier
    allowed_user_ids: frozenset[str] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.allowed_user_ids:
            raise ValueError("identity_configuration_authorized_users_required")
        for user in self.allowed_user_ids:
            _uuid(user)

    async def authorize(self, authorization: str | None) -> DelegatedRequest:
        token = bearer_token(authorization)
        user = await self.verifier.verify(token)
        if user.object_id not in self.allowed_user_ids:
            raise AuthError("user_not_authorized", 403, user_object_id=user.object_id)
        return DelegatedRequest(user, SecretStr(token))


def configured_guard(prefix: str) -> AccessGuard | None:
    """Explicit opt-in only; incomplete or misspelled identity config never falls back."""
    mode = os.environ.get(f"{prefix}_AUTH_MODE", "legacy")
    names = ("TENANT_ID", "AUDIENCE", "SCOPE", "CLIENT_IDS", "AUTHORIZED_USER_IDS")
    values = {name: os.environ.get(f"{prefix}_{name}", "") for name in names}
    if mode == "legacy":
        if any(values.values()):
            raise ValueError("identity_configuration_requires_explicit_delegated_mode")
        return None
    if mode != "delegated" or not all(values.values()):
        raise ValueError("identity_configuration_incomplete_or_invalid_mode")
    clients = frozenset(values["CLIENT_IDS"].split(","))
    users = frozenset(values["AUTHORIZED_USER_IDS"].split(","))
    contract = TokenContract(values["TENANT_ID"], values["AUDIENCE"], values["SCOPE"], clients)
    for user in users:
        _uuid(user)
    return AccessGuard(TokenVerifier(contract), users)
