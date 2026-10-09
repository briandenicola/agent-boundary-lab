"""Tests for startup configuration validation.

A misconfigured demo that starts anyway produces results that look real. These tests
exist so that it refuses.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from containment_demo.settings import PolicyMode, Settings, ca_bundle_path


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "policy_api_url": "https://policy.example.com/policy",
        "test_receiver_url": "https://receiver.example.net/ingest",
        "diagnostics_token": "test-diagnostics-token-value",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_valid_configuration_is_accepted() -> None:
    settings = make_settings()
    assert settings.policy_api_host == "policy.example.com"
    assert settings.test_receiver_host == "receiver.example.net"


def test_identical_hosts_are_rejected() -> None:
    """The egress policy allowlists hosts, so identical hosts make the test meaningless."""
    with pytest.raises(ValidationError, match="same host"):
        make_settings(
            policy_api_url="https://same.example.com/a",
            test_receiver_url="https://same.example.com/b",
        )


def test_identical_hosts_rejected_regardless_of_case() -> None:
    with pytest.raises(ValidationError, match="same host"):
        make_settings(
            policy_api_url="https://Same.Example.com/a",
            test_receiver_url="https://same.example.com/b",
        )


def test_plain_http_destination_is_rejected() -> None:
    with pytest.raises(ValidationError, match="https"):
        make_settings(policy_api_url="http://policy.example.com/policy")


def test_malformed_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(policy_api_url="not-a-url")


def test_missing_destination_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            test_receiver_url="https://receiver.example.net/ingest",
            diagnostics_token="test-diagnostics-token-value",
        )


@pytest.mark.parametrize("bad_timeout", [0, -1, 61])
def test_timeout_must_be_bounded_and_positive(bad_timeout: float) -> None:
    """There is no unbounded and no nonsensical timeout path."""
    with pytest.raises(ValidationError):
        make_settings(http_timeout_seconds=bad_timeout)


def test_timeout_has_a_default_so_there_is_never_no_timeout() -> None:
    assert make_settings().http_timeout_seconds > 0


def test_demo_run_id_is_unique_per_instance() -> None:
    """The run marker is our only correlation key, so it must not collide."""
    assert make_settings().demo_run_id != make_settings().demo_run_id


def test_policy_mode_defaults_to_local() -> None:
    """A deployment must opt in to claiming it is Audit or Enforced."""
    assert make_settings().policy_mode is PolicyMode.LOCAL


def test_unknown_policy_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(policy_mode="enforcedish")


def test_agent_version_reports_local_outside_hosted_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FOUNDRY_AGENT_VERSION", raising=False)
    assert make_settings().agent_version == "local"


def test_agent_version_reads_platform_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOUNDRY_AGENT_VERSION", "7")
    assert make_settings().agent_version == "7"


class TestCaBundle:
    """The proxy CA rotates roughly monthly and must never be pinned or cached."""

    def test_returns_none_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.delenv("SSL_CERT_FILE", raising=False)
        assert ca_bundle_path() is None

    def test_prefers_requests_ca_bundle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/run/a.pem")
        monkeypatch.setenv("SSL_CERT_FILE", "/run/b.pem")
        assert ca_bundle_path() == "/run/a.pem"

    def test_falls_back_to_ssl_cert_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
        monkeypatch.setenv("SSL_CERT_FILE", "/run/b.pem")
        assert ca_bundle_path() == "/run/b.pem"

    def test_is_read_fresh_every_call_not_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Rotation means a cached path goes stale and TLS starts failing."""
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/run/first.pem")
        assert ca_bundle_path() == "/run/first.pem"
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/run/rotated.pem")
        assert ca_bundle_path() == "/run/rotated.pem"


def test_azure_openai_api_version_default_is_v1_not_a_dated_version() -> None:
    """2024-10-21 predates the Responses API; litellm routes gpt-5.4+ tool calls to
    /openai/responses and the dated version 404'd live (2026-10-09)."""
    assert Settings.model_fields["azure_openai_api_version"].default == "v1"
