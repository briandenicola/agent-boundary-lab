"""Startup configuration, validated before the agent is allowed to serve traffic.

Every outbound destination this demo can reach is fixed here, at startup, from
configuration. No tool accepts a URL argument. That is the point: if a tool could be
handed an arbitrary destination, the egress policy would no longer be the only thing
deciding where traffic goes, and the experiment would prove nothing.

Validation is deliberately loud and fail-fast. A misconfigured demo that starts anyway
is worse than one that refuses to start, because its results look real.
"""

from __future__ import annotations

import os
import uuid
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class PolicyMode(StrEnum):
    """Which egress policy this deployment is running under.

    This is **metadata for evidence labelling only**. Nothing in the application may
    branch on it. The whole claim of this demo is that behaviour differs because the
    platform enforced a policy, not because the application knew which mode it was in.
    """

    LOCAL = "local"
    AUDIT = "audit"
    ENFORCED = "enforced"


class ErrorCategory(StrEnum):
    """Classification of a failed outbound call.

    There is deliberately no ``POLICY_DENIED`` member. The application cannot know that
    a platform denied a request; it only observes an HTTP status, a TLS failure, a DNS
    failure, or a timeout. Attributing a denial requires corroborating platform evidence
    and is the verifier's job, never a tool's.
    """

    NONE = "none"
    HTTP_ERROR = "http_error"
    TLS_ERROR = "tls_error"
    DNS_ERROR = "dns_error"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    UNEXPECTED = "unexpected"


def _host_of(url: str) -> str:
    parsed = urlparse(str(url))
    if not parsed.hostname:
        raise ValueError(f"URL has no host: {url!r}")
    return parsed.hostname.lower()


class Settings(BaseSettings):
    """Validated startup configuration.

    Environment variables are read with the ``DEMO_`` prefix, e.g. ``DEMO_POLICY_API_URL``.
    The ``FOUNDRY_`` and ``AGENT_`` prefixes are reserved by the platform and are never
    used for our own settings.
    """

    model_config = SettingsConfigDict(
        env_prefix="DEMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- The two business destinations -------------------------------------------------
    # These must be distinct hostnames. A path-based distinction would not be a valid
    # test, because the egress policy allowlists hosts.

    policy_api_url: HttpUrl = Field(
        description="Allowlisted destination. Expected to succeed in every mode.",
    )
    test_receiver_url: HttpUrl = Field(
        description="Destination deliberately omitted from the allowlist. "
        "Expected to be denied by the platform under Enforced.",
    )

    # --- HTTP behaviour ----------------------------------------------------------------

    http_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
        description="Explicit bounded timeout. There is no unbounded path.",
    )

    # --- Evidence labelling ------------------------------------------------------------

    policy_mode: PolicyMode = Field(
        default=PolicyMode.LOCAL,
        description="Evidence label only. Never branch on this.",
    )
    demo_run_id: str = Field(
        default_factory=lambda: f"run-{uuid.uuid4()}",
        description="Synthetic correlation marker. The only correlation key we control, "
        "and therefore not optional — see docs/compatibility.md C3.",
    )

    # --- Model access ------------------------------------------------------------------

    model_deployment: str = Field(
        default="gpt-5.4-mini",
        description=(
            "Foundry model deployment name, used as litellm 'azure/<deployment>'. "
            "Must match infra/cloud var.model_name -- the deployment is named after the "
            "model, so a mismatch here fails at the first model call, not at startup."
        ),
    )
    azure_openai_endpoint: str | None = Field(
        default=None,
        description="Foundry/Azure OpenAI endpoint. Required when running against a model.",
    )
    azure_openai_api_version: str = Field(default="2024-10-21")

    # --- Diagnostics -------------------------------------------------------------------

    diagnostics_enabled: bool = Field(
        default=True,
        description="Exposes the authenticated deterministic diagnostic route.",
    )
    diagnostics_token: SecretStr | None = Field(
        default=None,
        description="Shared secret required by the diagnostic route. Mandatory whenever "
        "diagnostics are enabled; there is no unauthenticated mode.",
    )

    @field_validator("policy_api_url", "test_receiver_url")
    @classmethod
    def _must_be_https(cls, v: HttpUrl) -> HttpUrl:
        if urlparse(str(v)).scheme != "https":
            raise ValueError(
                f"destination must use https, got {urlparse(str(v)).scheme!r}: {v}. "
                "Plain HTTP would not exercise the egress proxy's TLS path."
            )
        return v

    @model_validator(mode="after")
    def _destinations_must_differ(self) -> Settings:
        policy_host = _host_of(str(self.policy_api_url))
        receiver_host = _host_of(str(self.test_receiver_url))
        if policy_host == receiver_host:
            raise ValueError(
                "policy_api_url and test_receiver_url resolve to the same host "
                f"({policy_host!r}). The egress policy allowlists hostnames, so identical "
                "hosts make allow and deny indistinguishable and the demo proves nothing."
            )
        return self

    @model_validator(mode="after")
    def _diagnostics_require_a_token(self) -> Settings:
        if self.diagnostics_enabled:
            secret = self.diagnostics_token.get_secret_value() if self.diagnostics_token else ""
            if len(secret) < 16:
                raise ValueError(
                    "diagnostics_token must be set to at least 16 characters when "
                    "diagnostics_enabled is true. The diagnostic route triggers real "
                    "outbound calls, so it is never exposed unauthenticated."
                )
        return self

    @property
    def policy_api_host(self) -> str:
        return _host_of(str(self.policy_api_url))

    @property
    def test_receiver_host(self) -> str:
        return _host_of(str(self.test_receiver_url))

    @property
    def agent_version(self) -> str:
        """Platform-assigned agent version, or 'local' outside the hosted runtime."""
        return os.environ.get("FOUNDRY_AGENT_VERSION", "local")

    @property
    def agent_name(self) -> str:
        return os.environ.get("FOUNDRY_AGENT_NAME", "containment-demo-local")


def ca_bundle_path() -> str | None:
    """Return the CA bundle the hosted runtime injected, if any.

    The egress proxy intercepts TLS and injects its own CA into the sandbox trust bundle.
    That CA is infrastructure-specific and rotates roughly every 30 days, so the
    documentation says to treat it as runtime configuration and never pin, copy or
    persist it. We therefore read it fresh from the environment on every client build
    and never cache or hardcode a path.

    Returns ``None`` outside the hosted runtime, in which case the system trust store is
    used. Verification is never disabled, in any mode.
    """
    for var in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        value = os.environ.get(var)
        if value:
            return value
    return None
