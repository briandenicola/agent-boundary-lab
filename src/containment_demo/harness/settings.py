"""Validated startup configuration for the harness. Destinations come only from here."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from containment_demo import ui_a2a

SLOTS = ("audit", "enforced")


def _env(*names: str) -> AliasChoices:
    return AliasChoices(*names)


class HarnessSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    local_model_base_url: str = Field(validation_alias=_env("LOCAL_MODEL_BASE_URL"))
    local_model_name: str = Field(
        default="qwen2.5-3b-instruct", validation_alias=_env("LOCAL_MODEL_NAME")
    )
    # llama.cpp ignores the key; litellm's openai client still wants a non-empty string.
    local_model_api_key: SecretStr = Field(
        default=SecretStr("not-needed"), validation_alias=_env("LOCAL_MODEL_API_KEY")
    )
    # Model calls take 40-70 s on CPU; generous bounds, and no retries.
    model_timeout_seconds: float = Field(
        default=180.0, gt=0, le=900, validation_alias=_env("HARNESS_MODEL_TIMEOUT_SECONDS")
    )
    tool_timeout_seconds: float = Field(
        default=150.0, gt=0, le=600, validation_alias=_env("HARNESS_TOOL_TIMEOUT_SECONDS")
    )
    turn_timeout_seconds: float = Field(
        default=600.0, gt=0, le=1800, validation_alias=_env("HARNESS_TURN_TIMEOUT_SECONDS")
    )

    a2a_facade_url_audit: str = Field(validation_alias=_env("DEMO_A2A_FACADE_URL_AUDIT"))
    a2a_facade_url_enforced: str = Field(validation_alias=_env("DEMO_A2A_FACADE_URL_ENFORCED"))
    a2a_token: SecretStr = Field(validation_alias=_env("DEMO_A2A_TOKEN"))
    agent_name_audit: str = Field(default="audit", validation_alias=_env("DEMO_AGENT_NAME_AUDIT"))
    agent_name_enforced: str = Field(
        default="enforced", validation_alias=_env("DEMO_AGENT_NAME_ENFORCED")
    )
    ui_token: SecretStr = Field(validation_alias=_env("HARNESS_UI_TOKEN"))
    run_label: Literal["hosted", "local"] = Field(validation_alias=_env("DEMO_RUN_LABEL"))

    @field_validator("local_model_base_url", "a2a_facade_url_audit", "a2a_facade_url_enforced")
    @classmethod
    def _url(cls, v: str) -> str:
        return ui_a2a.validate_base_url(v)

    @field_validator("ui_token", "a2a_token")
    @classmethod
    def _strength(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 16:
            raise ValueError("tokens must be at least 16 characters")
        return v

    def facade_for(self, slot: str) -> str:
        return {"audit": self.a2a_facade_url_audit, "enforced": self.a2a_facade_url_enforced}[slot]

    def agent_for(self, slot: str) -> str:
        return {"audit": self.agent_name_audit, "enforced": self.agent_name_enforced}[slot]
