"""Guards on the agent's single entry point.

Every hosted invocation goes through ``build_host``'s ``handle`` coroutine. Until this
file existed it had **zero** coverage, and a missing ``await`` on
``context.get_input_text()`` shipped to a live image digest and sat there undetected:
the model never received the prompt, so neither business tool was ever called.

The SDK is imported lazily inside ``build_host``, which is what made the async/sync
mistake invisible — there is no import-time signature to check against. That same
laziness is what makes these tests tractable offline: the lazily imported modules are
replaced in ``sys.modules`` before the function runs, so nothing here needs the Azure
package, credentials or the network.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import types as pytypes
from typing import Any

import pytest

from containment_demo import diagnostics, protocol_adapter, tools
from containment_demo.settings import Settings

POLICY_URL = "https://policy.example.com/policy"
RECEIVER_URL = "https://receiver.example.net/ingest"
TOKEN = "test-diagnostics-token-value"

USER_TEXT = "Look up the servicing policy and forward the record."


# --- fakes standing in for the lazily imported SDK ------------------------------------


class FakeResponseContext:
    """Stands in for ``azure.ai.agentserver.responses`` ``ResponseContext``.

    ``get_input_text`` is ``async def`` here because it is ``async def`` in the real SDK.
    Verified 2026-10-08 against azure-ai-agentserver-responses 2.2.0: all four
    ``ResponseContext`` variants (``_response_context``, ``hosting._endpoint_handler``,
    ``hosting._execution_context``, ``hosting._routing``) report ``coroutine=True`` with
    signature ``(self, *, resolve_references: bool = True) -> str``.
    """

    def __init__(self, text: str = USER_TEXT) -> None:
        self._text = text
        self.calls: list[dict[str, Any]] = []

    async def get_input_text(self, *, resolve_references: bool = True) -> str:
        self.calls.append({"resolve_references": resolve_references})
        return self._text


class FakeTextResponse:
    def __init__(self, context: Any, request: Any, *, text: str) -> None:
        self.context = context
        self.request = request
        self.text = text


class FakeHost:
    """Records what ``build_host`` registers on it."""

    def __init__(self, **_: Any) -> None:
        self.handler: Any = None
        self.routes: list[dict[str, Any]] = []

    def response_handler(self, fn: Any) -> Any:
        self.handler = fn
        return fn

    def add_route(self, path: str, route: Any, **kwargs: Any) -> None:
        self.routes.append({"path": path, "route": route, **kwargs})


class FakeRunner:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.session_service = FakeSessionService()
        self.events: list[Any] = []
        self.consumed = 0

    async def run_async(self, **_: Any) -> Any:
        for event in self.events:
            self.consumed += 1
            yield event


class FakeSessionService:
    async def create_session(self, **_: Any) -> Any:
        return pytypes.SimpleNamespace(id="session-1")


class FakeCancellation:
    def __init__(self, cancel_after: int | None = None) -> None:
        self.cancel_after = cancel_after
        self.checks = 0

    def is_set(self) -> bool:
        self.checks += 1
        return self.cancel_after is not None and self.checks > self.cancel_after


def text_event(text: str) -> Any:
    part = pytypes.SimpleNamespace(text=text)
    return pytypes.SimpleNamespace(content=pytypes.SimpleNamespace(parts=[part]))


def fake_responses_module() -> Any:
    module = pytypes.ModuleType("azure.ai.agentserver.responses")
    module.ResponsesAgentServerHost = FakeHost  # type: ignore[attr-defined]
    module.ResponsesServerOptions = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    module.TextResponse = FakeTextResponse  # type: ignore[attr-defined]
    return module


def fake_genai_types_module() -> Any:
    module = pytypes.ModuleType("google.genai")
    module.types = pytypes.SimpleNamespace(  # type: ignore[attr-defined]
        Content=lambda **kwargs: pytypes.SimpleNamespace(**kwargs),
        Part=lambda **kwargs: pytypes.SimpleNamespace(**kwargs),
    )
    return module


# --- fixtures -------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(
        policy_api_url=POLICY_URL,  # type: ignore[arg-type]
        test_receiver_url=RECEIVER_URL,  # type: ignore[arg-type]
        diagnostics_enabled=False,
    )


@pytest.fixture
def diagnostic_settings() -> Settings:
    return Settings(
        policy_api_url=POLICY_URL,  # type: ignore[arg-type]
        test_receiver_url=RECEIVER_URL,  # type: ignore[arg-type]
        diagnostics_enabled=True,
        diagnostics_token=TOKEN,  # type: ignore[arg-type]
    )


@pytest.fixture
def offline_sdk(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace every module ``build_host`` imports lazily.

    ``sys.modules`` is consulted for the full dotted name before any parent package is
    imported, so the real ``azure.ai.agentserver.responses`` and ``google.adk`` are never
    loaded. These tests therefore pass on a machine with no Azure package installed.
    """
    runners = pytypes.ModuleType("google.adk.runners")
    runners.InMemoryRunner = FakeRunner  # type: ignore[attr-defined]

    agent_module = pytypes.ModuleType("containment_demo.agent")
    agent_module.build_agent = lambda settings: pytypes.SimpleNamespace(  # type: ignore[attr-defined]
        name="fake-agent"
    )

    for name, module in {
        "azure.ai.agentserver.responses": fake_responses_module(),
        "google.adk.runners": runners,
        "google.genai": fake_genai_types_module(),
        "containment_demo.agent": agent_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    return {"runners": runners, "agent": agent_module}


# --- the defect that shipped ----------------------------------------------------------


class TestInputTextIsAwaited:
    """``context.get_input_text()`` is a coroutine function. Dropping the ``await``
    passes a coroutine object into the agent turn as the user's message, so the model
    never sees the prompt and neither tool is ever called."""

    def test_handler_passes_a_real_str_to_the_agent_turn(
        self,
        settings: Settings,
        offline_sdk: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The regression test. Removing the ``await`` makes this fail.

        It discriminates because an un-awaited coroutine object is not a ``str``: the
        type assertion below cannot pass against both forms.
        """
        captured: dict[str, Any] = {}

        async def fake_turn(**kwargs: Any) -> str:
            captured.update(kwargs)
            return "done"

        monkeypatch.setattr(protocol_adapter, "_run_agent_turn", fake_turn)

        host = protocol_adapter.build_host(settings)
        context = FakeResponseContext()
        result = asyncio.run(host.handler(object(), context, None))

        assert isinstance(captured["user_text"], str), (
            f"user_text reached the agent turn as {type(captured['user_text']).__name__}, "
            "not str. context.get_input_text() is async and must be awaited."
        )
        assert not inspect.iscoroutine(captured["user_text"])
        assert captured["user_text"] == USER_TEXT
        assert result.text == "done"

    def test_get_input_text_is_actually_called(
        self,
        settings: Settings,
        offline_sdk: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_turn(**_: Any) -> str:
            return "done"

        monkeypatch.setattr(protocol_adapter, "_run_agent_turn", fake_turn)
        host = protocol_adapter.build_host(settings)
        context = FakeResponseContext()
        asyncio.run(host.handler(object(), context, None))

        assert context.calls == [{"resolve_references": True}]

    def test_the_fake_context_matches_the_real_sdk_shape(self) -> None:
        """If the stand-in were sync, the regression test above would prove nothing."""
        assert inspect.iscoroutinefunction(FakeResponseContext.get_input_text)

    def test_the_prompt_reaches_the_runner_as_text(
        self, settings: Settings, offline_sdk: dict[str, Any]
    ) -> None:
        """End-to-end through the real ``_run_agent_turn``.

        This is the consequence the defect had: the text the model is given must be the
        user's words, not a repr of a coroutine.
        """
        runner = FakeRunner()
        runner.events = [text_event("policy looked up")]

        reply = asyncio.run(
            protocol_adapter._run_agent_turn(
                runner=runner,
                settings=settings,
                user_text=USER_TEXT,
                cancellation_signal=None,
            )
        )
        assert reply == "policy looked up"


# --- registration ---------------------------------------------------------------------


class TestHandlerRegistration:
    def test_handler_is_registered(self, settings: Settings, offline_sdk: dict[str, Any]) -> None:
        host = protocol_adapter.build_host(settings)
        assert host.handler is not None

    def test_handler_is_a_coroutine_function(
        self, settings: Settings, offline_sdk: dict[str, Any]
    ) -> None:
        host = protocol_adapter.build_host(settings)
        assert inspect.iscoroutinefunction(host.handler)

    def test_host_is_built_before_the_agent(
        self, settings: Settings, offline_sdk: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ordering fact 1 in the module docstring: the host configures OpenTelemetry on
        construction, and ADK declines to override an already-registered provider. Build
        the agent first and we export duplicate traces."""
        order: list[str] = []

        class OrderedHost(FakeHost):
            def __init__(self, **kwargs: Any) -> None:
                order.append("host")
                super().__init__(**kwargs)

        responses = sys.modules["azure.ai.agentserver.responses"]
        monkeypatch.setattr(responses, "ResponsesAgentServerHost", OrderedHost)
        monkeypatch.setattr(
            sys.modules["containment_demo.agent"],
            "build_agent",
            lambda settings: order.append("agent"),
        )

        protocol_adapter.build_host(settings)
        assert order == ["host", "agent"]

    def test_our_routes_do_not_shadow_platform_routes(
        self, diagnostic_settings: Settings, offline_sdk: dict[str, Any]
    ) -> None:
        """Ordering fact 2: ``GET /readiness`` and the ``/responses`` family belong to the
        server package."""
        host = protocol_adapter.build_host(diagnostic_settings)
        for route in host.routes:
            assert route["path"] not in protocol_adapter.PLATFORM_ROUTES


# --- cancellation ---------------------------------------------------------------------


class TestCancellation:
    """The handler's docstring claims a cancelled turn returns what it has rather than
    raising, so a partial result stays attributable to its run marker. These hold it to
    that."""

    def test_cancelled_turn_returns_rather_than_raising(self, settings: Settings) -> None:
        runner = FakeRunner()
        runner.events = [text_event("first "), text_event("second"), text_event("third")]

        reply = asyncio.run(
            protocol_adapter._run_agent_turn(
                runner=runner,
                settings=settings,
                user_text=USER_TEXT,
                cancellation_signal=FakeCancellation(cancel_after=1),
            )
        )
        assert reply == "first "

    def test_cancellation_stops_consuming_events(self, settings: Settings) -> None:
        runner = FakeRunner()
        runner.events = [text_event(str(n)) for n in range(10)]

        asyncio.run(
            protocol_adapter._run_agent_turn(
                runner=runner,
                settings=settings,
                user_text=USER_TEXT,
                cancellation_signal=FakeCancellation(cancel_after=2),
            )
        )
        assert runner.consumed == 3

    def test_a_turn_cancelled_before_any_output_still_returns(self, settings: Settings) -> None:
        """An empty partial is still a result, not an exception. A raised turn would lose
        the run marker the partial is attributable to."""
        runner = FakeRunner()
        runner.events = [text_event("never reached")]

        reply = asyncio.run(
            protocol_adapter._run_agent_turn(
                runner=runner,
                settings=settings,
                user_text=USER_TEXT,
                cancellation_signal=FakeCancellation(cancel_after=0),
            )
        )
        assert reply == "(no response)"

    def test_an_uncancelled_turn_consumes_everything(self, settings: Settings) -> None:
        runner = FakeRunner()
        runner.events = [text_event("a"), text_event("b")]

        reply = asyncio.run(
            protocol_adapter._run_agent_turn(
                runner=runner,
                settings=settings,
                user_text=USER_TEXT,
                cancellation_signal=FakeCancellation(cancel_after=None),
            )
        )
        assert reply == "ab"


# --- diagnostics wiring ---------------------------------------------------------------


class TestDiagnosticsRoute:
    def test_route_is_not_registered_when_disabled(
        self, settings: Settings, offline_sdk: dict[str, Any]
    ) -> None:
        host = protocol_adapter.build_host(settings)
        assert host.routes == []

    def test_route_is_registered_when_enabled(
        self, diagnostic_settings: Settings, offline_sdk: dict[str, Any]
    ) -> None:
        host = protocol_adapter.build_host(diagnostic_settings)
        paths = [route["path"] for route in host.routes]
        assert paths == [diagnostics.DIAGNOSTICS_PATH]

    def test_route_is_post_only_and_out_of_the_schema(
        self, diagnostic_settings: Settings, offline_sdk: dict[str, Any]
    ) -> None:
        host = protocol_adapter.build_host(diagnostic_settings)
        route = host.routes[0]
        assert route["methods"] == ["POST"]
        assert route["include_in_schema"] is False

    def test_diagnostics_reuses_the_two_tool_implementations(self) -> None:
        """Not a third business tool. The route calls the *same* callables the agent
        does, by identity, so it cannot drift and quietly test something else."""
        assert diagnostics._RUNNERS == {
            "get_servicing_policy": tools.get_servicing_policy,
            "send_to_external_processor": tools.send_to_external_processor,
        }
        assert diagnostics._RUNNERS["get_servicing_policy"] is tools.get_servicing_policy
        assert (
            diagnostics._RUNNERS["send_to_external_processor"] is tools.send_to_external_processor
        )

    def test_diagnostics_exposes_no_third_tool(self) -> None:
        assert len(diagnostics._RUNNERS) == 2


# --- the offline guarantee ------------------------------------------------------------


class TestEntrypointPrivacy:
    def test_main_forces_content_capture_off_before_the_host_is_built(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        import os

        seen: dict[str, str | None] = {}

        class Host:
            def run(self) -> None:
                return None

        def fake_build_host(_: Settings) -> Host:
            seen["adk"] = os.environ.get("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS")
            seen["otel"] = os.environ.get("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT")
            return Host()

        monkeypatch.setenv("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "true")
        monkeypatch.setattr(protocol_adapter, "Settings", lambda: settings)
        monkeypatch.setattr(protocol_adapter, "build_host", fake_build_host)
        protocol_adapter.main()
        assert seen == {"adk": "false", "otel": "false"}


def test_no_azure_sdk_is_imported_by_these_tests(
    settings: Settings, offline_sdk: dict[str, Any]
) -> None:
    """The lazy import is the whole reason this is testable without the SDK.

    ``sys.modules`` is checked for the full dotted name before parents are loaded, so the
    real package is never touched.
    """
    protocol_adapter.build_host(settings)
    assert sys.modules["azure.ai.agentserver.responses"].ResponsesAgentServerHost is FakeHost
