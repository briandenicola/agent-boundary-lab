"""Guards on evidence emission.

Two things must hold: nothing sensitive is ever emitted, and the hosted path never
installs a second tracer provider on top of the one the agent server host configures.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from opentelemetry import trace

from containment_demo import telemetry
from containment_demo.settings import PolicyMode, Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        policy_api_url="https://policy.example.com/policy",  # type: ignore[arg-type]
        test_receiver_url="https://receiver.example.net/ingest",  # type: ignore[arg-type]
        policy_mode=PolicyMode.ENFORCED,
        diagnostics_token="test-diagnostics-token-value",  # type: ignore[arg-type]
    )


class RecordingSpan:
    def __init__(self, recording: bool = True) -> None:
        self.recording = recording
        self.events: list[tuple[str, dict[str, Any]]] = []

    def is_recording(self) -> bool:
        return self.recording

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append((name, dict(attributes or {})))


class TestContentCapture:
    def test_capture_is_forced_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in telemetry._CONTENT_CAPTURE_OFF:
            monkeypatch.setenv(key, "true")
        telemetry.disable_content_capture()
        for key in telemetry._CONTENT_CAPTURE_OFF:
            assert os.environ[key] == "false", (
                f"{key} was left enabled; prompts and payloads could reach telemetry"
            )

    def test_an_operator_cannot_opt_back_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pre-existing values are overwritten, not respected."""
        monkeypatch.setenv("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "True")
        telemetry.disable_content_capture()
        assert os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] == "false"


class TestEmittedFields:
    def test_only_allow_listed_keys_are_emitted(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        span = RecordingSpan()
        monkeypatch.setattr(trace, "get_current_span", lambda: span)

        telemetry.emit_tool_evidence(
            settings,
            {
                "tool_name": "send_to_external_processor",
                "succeeded": False,
                "http_status": 403,
                "error_category": "http_error",
                "duration_ms": 12.5,
                "destination_host": "receiver.example.net",
                # Fields that must never be emitted, even though a tool result carries them.
                "result": {"account": "synthetic-123"},
                "authorization": "Bearer should-never-appear",
                "request_payload": {"ssn": "000-00-0000"},
            },
        )

        assert len(span.events) == 1
        name, attributes = span.events[0]
        assert name == "demo.tool_result"
        unexpected = {k for k in attributes if not k.startswith("demo.")}
        assert not unexpected

        rendered = repr(attributes)
        for leak in ("Bearer", "ssn", "000-00-0000", "synthetic-123"):
            assert leak not in rendered, f"{leak!r} reached telemetry attributes"

    def test_run_marker_is_always_attached(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        span = RecordingSpan()
        monkeypatch.setattr(trace, "get_current_span", lambda: span)
        telemetry.emit_tool_evidence(settings, {"tool_name": "get_servicing_policy"})

        _, attributes = span.events[0]
        assert attributes["demo.run_id"] == settings.demo_run_id
        assert attributes["demo.policy_mode"] == "enforced"
        assert attributes["demo.agent_name"] == settings.agent_name
        assert attributes["demo.agent_version"] == settings.agent_version

    def test_none_values_are_dropped(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        span = RecordingSpan()
        monkeypatch.setattr(trace, "get_current_span", lambda: span)
        telemetry.emit_tool_evidence(
            settings, {"tool_name": "get_servicing_policy", "http_status": None}
        )
        _, attributes = span.events[0]
        assert "demo.http_status" not in attributes


class TestProviderOwnership:
    def test_local_setup_defers_when_a_provider_exists(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inside the hosted container the host owns telemetry; we must not add a second."""

        class AlreadyConfiguredProvider:
            pass

        monkeypatch.setattr(trace, "get_tracer_provider", lambda: AlreadyConfiguredProvider())
        monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=fake")

        assert telemetry.configure_local_telemetry(settings) is False

    def test_local_setup_is_a_noop_without_a_connection_string(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
        assert telemetry.configure_local_telemetry(settings) is False
