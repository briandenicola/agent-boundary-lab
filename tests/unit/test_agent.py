"""Tests for agent construction. The invariant here is *unconditional registration*.

The demo's entire claim is that the application never decides which destination is
reachable. That claim dies the moment a tool can be dropped, renamed away, or handed a
destination. These tests assert those absences directly, including across policy modes,
so a future refactor that reintroduces a branch fails here rather than in a demo.

Nothing in this module touches the network, Azure, or credentials: the model is a stub
and both tools are exercised only through their signatures.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from containment_demo import agent, tools
from containment_demo.settings import PolicyMode, Settings

AGENT_SOURCE = Path(agent.__file__)

EXPECTED_TOOL_NAMES = {"get_servicing_policy", "send_to_external_processor"}


def _settings(mode: PolicyMode = PolicyMode.LOCAL) -> Settings:
    return Settings(
        policy_api_url="https://policy.example.com/",  # type: ignore[arg-type]
        test_receiver_url="https://receiver.example.net/",  # type: ignore[arg-type]
        diagnostics_token="test-diagnostics-token-value",
        policy_mode=mode,
    )


@pytest.fixture
def settings() -> Settings:
    return _settings()


def _offline_model() -> object:
    """A model object that constructs without any credential or network call.

    ``LiteLlm`` resolves nothing at construction time, so this stays inside the rule that
    the unit suite never needs Azure. It is never invoked: these tests assert
    registration, not model behaviour.
    """
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model="azure/unit-test-not-called")


class TestBothToolsAreAlwaysRegistered:
    def test_exactly_the_two_business_tools_are_built(self, settings: Settings) -> None:
        names = {fn.__name__ for fn in agent.build_tool_functions(settings)}
        assert names == EXPECTED_TOOL_NAMES

    def test_required_tool_names_matches_what_is_built(self, settings: Settings) -> None:
        # Guards against the constant and the implementation drifting apart, which would
        # make every other assertion that uses the constant vacuous.
        built = {fn.__name__ for fn in agent.build_tool_functions(settings)}
        assert set(agent.REQUIRED_TOOL_NAMES) == built

    def test_agent_registers_both_tools(self, settings: Settings) -> None:
        built = agent.build_agent(settings, model=_offline_model())
        registered = {getattr(t, "__name__", getattr(t, "name", None)) for t in built.tools}
        assert registered == EXPECTED_TOOL_NAMES

    @pytest.mark.parametrize("mode", list(PolicyMode))
    def test_registration_is_identical_in_every_policy_mode(self, mode: PolicyMode) -> None:
        # The policy mode is an evidence label. If registration differed by mode, the
        # Audit and Enforced runs would differ in the application as well as the policy,
        # and neither run would attribute anything.
        names = {fn.__name__ for fn in agent.build_tool_functions(_settings(mode))}
        assert names == EXPECTED_TOOL_NAMES

    def test_registration_is_identical_inside_the_hosted_runtime(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setenv("FOUNDRY_AGENT_NAME", "containment-demo-enforced")
        monkeypatch.setenv("FOUNDRY_AGENT_VERSION", "7")
        names = {fn.__name__ for fn in agent.build_tool_functions(settings)}
        assert names == EXPECTED_TOOL_NAMES

    def test_the_blocked_destination_tool_is_not_omitted_or_renamed(
        self, settings: Settings
    ) -> None:
        names = [fn.__name__ for fn in agent.build_tool_functions(settings)]
        assert "send_to_external_processor" in names, (
            "the tool aimed at the non-allowlisted host must always be registered; "
            "removing it would make the demo an application-level check"
        )

    def test_registered_functions_delegate_to_the_real_tool_implementations(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Registration of a differently-behaving wrapper would pass every name check
        # above while never calling the audited implementation.
        called: list[str] = []
        for name in sorted(EXPECTED_TOOL_NAMES):
            monkeypatch.setattr(
                tools,
                name,
                lambda _s, _n=name: (called.append(_n), {"tool_name": _n})[1],
            )
        for fn in agent.build_tool_functions(settings):
            fn()
        assert sorted(called) == sorted(EXPECTED_TOOL_NAMES)


class TestToolsExposeNoDestination:
    @pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOL_NAMES))
    def test_tool_takes_zero_arguments(self, settings: Settings, tool_name: str) -> None:
        fn = next(f for f in agent.build_tool_functions(settings) if f.__name__ == tool_name)
        assert inspect.signature(fn).parameters == {}, (
            f"{tool_name} must take no arguments. Any parameter the model can fill is a "
            "destination the egress policy no longer solely controls."
        )

    def test_tools_have_docstrings_for_the_model(self, settings: Settings) -> None:
        # ADK exposes the docstring to the model. A missing one is not a correctness bug,
        # but it changes what the model is told the tool does, which is demo-visible.
        for fn in agent.build_tool_functions(settings):
            assert (fn.__doc__ or "").strip(), f"{fn.__name__} has no docstring"

    def test_no_url_or_host_literal_appears_in_the_agent_module(self) -> None:
        source = AGENT_SOURCE.read_text(encoding="utf-8")
        code_only = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        found = set(re.findall(r"https?://[a-z0-9.-]+", code_only, flags=re.IGNORECASE))
        # The Entra token scope is an identity audience, not a traffic destination, and
        # is the only URL literal permitted in this module.
        assert found <= {"https://cognitiveservices.azure.com"}, (
            f"destination literals in the agent module: {sorted(found)}. Destinations come "
            "from validated startup settings only."
        )

    def test_agent_module_contains_no_policy_mode_branch(self) -> None:
        tree = ast.parse(AGENT_SOURCE.read_text(encoding="utf-8"))
        branch_sources = [
            ast.unparse(node.test)
            for node in ast.walk(tree)
            if isinstance(node, ast.If | ast.IfExp)
        ]
        offenders = [
            text
            for text in branch_sources
            if "policy_mode" in text or "PolicyMode" in text or "enforced" in text.lower()
        ]
        assert not offenders, f"agent module branches on policy mode: {offenders}"


class TestInstruction:
    def test_instruction_does_not_ask_the_model_to_refuse_a_destination(self) -> None:
        # A prompt-level refusal would produce the demo's expected outcome for entirely
        # the wrong reason, and would survive the policy being switched off.
        lowered = agent.AGENT_INSTRUCTION.lower()
        for phrase in ("do not call", "refuse", "never send", "must not use the"):
            assert phrase not in lowered, (
                f"instruction contains {phrase!r}; a prompt-level refusal is not "
                "platform enforcement"
            )

    def test_instruction_forbids_the_model_claiming_a_policy_decision(self) -> None:
        assert "network policy blocked" in agent.AGENT_INSTRUCTION.lower()
