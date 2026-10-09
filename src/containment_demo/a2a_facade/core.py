"""Settings, the target interface and caller authentication. No a2a-sdk, no Foundry SDK."""

from __future__ import annotations

import hmac
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: The one capability this façade offers. Single turn, text in, text out.
SKILL_ID = "containment-probe"

MAX_INPUT_CHARS = 8000


class FacadeSettings(BaseSettings):
    """Validated startup configuration. Same ``DEMO_`` prefix as the other settings."""

    model_config = SettingsConfigDict(env_prefix="DEMO_", extra="ignore")

    foundry_account_name: str
    foundry_project_name: str
    a2a_target_agent_name: str = Field(description="The one hosted agent this façade fronts.")
    a2a_public_url: str = Field(description="Absolute URL callers use; advertised in the card.")
    a2a_token: SecretStr = Field(description="Shared bearer secret. At least 16 characters.")
    a2a_card_name: str = "containment-demo-a2a-facade"
    a2a_card_description: str = (
        "A2A façade over a Foundry hosted agent. The hosted agent is invoked through the "
        "Responses protocol; this server exposes it as A2A. Synthetic data only."
    )
    a2a_listen_port: int = Field(default=8080, ge=1, le=65535)
    a2a_timeout_seconds: float = Field(default=120.0, gt=0, le=300)

    @field_validator("foundry_account_name", "foundry_project_name", "a2a_target_agent_name")
    @classmethod
    def _dns_label(cls, v: str) -> str:
        if not _NAME.match(v):
            raise ValueError("must be alphanumerics and inner hyphens only")
        return v

    @field_validator("a2a_public_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if not re.match(r"^https?://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/-]*)?$", v):
            raise ValueError("must be an absolute http(s) URL with no query or credentials")
        return v.rstrip("/")

    @field_validator("a2a_token")
    @classmethod
    def _token_strength(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 16:
            raise ValueError("DEMO_A2A_TOKEN must be at least 16 characters")
        return v

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self.foundry_account_name}.services.ai.azure.com"
            f"/api/projects/{self.foundry_project_name}"
        )


# --- the target seam -------------------------------------------------------------


@dataclass(frozen=True)
class TargetReply:
    """What a target returned. ``tool_run_ids`` are only ever ones the agent reported."""

    text: str
    response_id: str | None = None
    tool_run_ids: tuple[str, ...] = ()


class TargetError(Exception):
    """The downstream call failed. Carries a category and status, never content."""

    def __init__(self, category: str, status: int | None = None) -> None:
        super().__init__(f"downstream call failed: {category}")
        self.category = category
        self.status = status


class AgentTarget(Protocol):
    """The only thing the A2A side knows about the agent behind it."""

    async def send(self, text: str) -> TargetReply: ...


# --- caller auth seam (Entra validation is issue #4) ------------------------------


@dataclass(frozen=True)
class Principal:
    """Who called, as an opaque loggable id. Never a credential."""

    id: str


class Authenticator(Protocol):
    """Seam for issue #4: an Entra token validator implements this and replaces the shared
    token. Returns None when the credential is absent or wrong."""

    def authenticate(self, authorization_header: str) -> Principal | None: ...


class SharedTokenAuthenticator:
    """Bearer token compared in constant time, same pattern as the demo UI."""

    PRINCIPAL = Principal(id="shared-token")

    def __init__(self, token: SecretStr) -> None:
        self._token = token.get_secret_value()

    def authenticate(self, authorization_header: str) -> Principal | None:
        scheme, _, presented = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not presented:
            return None
        if hmac.compare_digest(presented, self._token):
            return self.PRINCIPAL
        return None


@dataclass
class ContextMap:
    """context_id -> last downstream response id. IN-MEMORY AND NON-DURABLE: lost on every
    restart, per replica, bounded. It is a correlation aid for logs, NOT conversation
    state: calls use store=False, so nothing is chained and every turn is independent."""

    max_entries: int = 1024
    _items: OrderedDict[str, str] = field(default_factory=OrderedDict)

    def remember(self, context_id: str, response_id: str | None) -> None:
        if not response_id or not _SAFE_ID.match(context_id):
            return
        self._items[context_id] = response_id
        self._items.move_to_end(context_id)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def last(self, context_id: str) -> str | None:
        return self._items.get(context_id)
