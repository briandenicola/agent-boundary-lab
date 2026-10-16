"""Unfinished identity deployments must not silently run the legacy shared-token path."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from containment_demo.a2a_facade.core import FacadeSettings
from containment_demo.harness.settings import HarnessSettings


@pytest.mark.parametrize("mode", ["delegated", "unknown"])
def test_harness_refuses_unimplemented_identity_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("HARNESS_AUTH_MODE", mode)
    settings: dict[str, Any] = {
        "local_model_base_url": "http://model:8080/v1",
        "a2a_facade_url_audit": "http://audit:8080",
        "a2a_facade_url_enforced": "http://enforced:8080",
        "a2a_token": "synthetic-shared-token",
        "ui_token": "synthetic-ui-token",
        "run_label": "local",
    }
    with pytest.raises(ValidationError, match="HARNESS_AUTH_MODE"):
        HarnessSettings(**settings)


@pytest.mark.parametrize("mode", ["delegated", "unknown"])
def test_bridge_refuses_unimplemented_identity_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setenv("DEMO_A2A_AUTH_MODE", mode)
    with pytest.raises(ValidationError, match="a2a_auth_mode"):
        FacadeSettings(
            foundry_account_name="synthetic",
            foundry_project_name="synthetic",
            a2a_target_agent_name="audit",
            a2a_public_url="http://bridge:8080",
            a2a_token="synthetic-shared-token",
        )
