"""Guards for Blocker 0 — the OpenTelemetry dependency override.

The invariant, from docs/compatibility.md "Blocker 0":

``google-adk`` pins ``opentelemetry-api >=1.39,<=1.42.1``; ``azure-ai-agentserver-core``
pins ``>=1.43.0``. No released pair is co-installable, so **pip cannot install this
project**. It installs only under ``uv``, which applies the
``[tool.uv] override-dependencies`` block in ``pyproject.toml`` that forces
``opentelemetry-api``/``-sdk`` to ``>=1.43,<2``.

That override deliberately runs ADK outside its declared support window, so it fails at
*runtime* rather than at install time if ADK ever calls an OpenTelemetry API removed
after 1.42.1. These tests are the standing guard for that trade:

* the override is still declared, and still covers both packages;
* the installed version is actually above ADK's declared ceiling — i.e. the override was
  really applied, not silently dropped;
* ADK and the agent server both import and function at that version;
* the conflict still exists upstream, so the day ADK relaxes its pin, this suite says so
  and the override can be removed rather than quietly outliving its reason.

No network, no credentials: everything here reads installed metadata and local files.
"""

from __future__ import annotations

import importlib.metadata as metadata
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

#: The floor the agent server requires and the override encodes.
REQUIRED_OTEL_FLOOR = Version("1.43")

OVERRIDDEN_PACKAGES = ("opentelemetry-api", "opentelemetry-sdk")


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _declared_constraint(distribution: str, dependency: str) -> Requirement | None:
    """The requirement ``distribution`` declares on ``dependency``, from its metadata."""
    for raw in metadata.requires(distribution) or []:
        requirement = Requirement(raw)
        if requirement.name.lower() == dependency and not requirement.marker:
            return requirement
    return None


class TestTheOverrideIsDeclared:
    def test_uv_override_block_exists(self, pyproject: dict) -> None:
        overrides = pyproject.get("tool", {}).get("uv", {}).get("override-dependencies")
        assert overrides, (
            "pyproject [tool.uv] override-dependencies is missing. Without it the "
            "dependency set is unsolvable and the project cannot be installed at all."
        )

    @pytest.mark.parametrize("package", OVERRIDDEN_PACKAGES)
    def test_both_opentelemetry_distributions_are_overridden(
        self, pyproject: dict, package: str
    ) -> None:
        # Overriding only the API would let the SDK resolve below the floor and split the
        # two halves of OpenTelemetry across incompatible versions.
        declared = pyproject.get("tool", {}).get("uv", {}).get("override-dependencies")
        assert declared, "pyproject [tool.uv] override-dependencies is missing"
        overrides = [Requirement(raw) for raw in declared]
        match = next((r for r in overrides if r.name.lower() == package), None)
        assert match is not None, f"{package} is not in override-dependencies"
        assert match.specifier.contains(str(REQUIRED_OTEL_FLOOR)), (
            f"{package} override {match.specifier} does not admit "
            f"{REQUIRED_OTEL_FLOOR}, which azure-ai-agentserver-core requires"
        )

    def test_the_override_points_at_its_justification(self) -> None:
        # The override is a deliberate, documented risk. An undocumented one is just a
        # pin somebody will delete.
        source = PYPROJECT.read_text(encoding="utf-8")
        assert "Blocker 0" in source
        assert "compatibility.md" in source


class TestTheOverrideWasActuallyApplied:
    @pytest.mark.parametrize("package", OVERRIDDEN_PACKAGES)
    def test_installed_version_is_at_or_above_the_floor(self, package: str) -> None:
        installed = Version(metadata.version(package))
        assert installed >= REQUIRED_OTEL_FLOOR, (
            f"{package} {installed} is below {REQUIRED_OTEL_FLOOR}. The environment was "
            "built without the uv override — azure-ai-agentserver-core will not work. "
            "Install with `uv sync`, not pip."
        )

    def test_installed_version_is_above_adk_declared_ceiling(self) -> None:
        # This is the whole of Blocker 0 in one assertion: we are knowingly running ADK
        # outside its declared support window. If this ever stops being true without the
        # pin changing, something re-resolved the environment.
        adk = _declared_constraint("google-adk", "opentelemetry-api")
        assert adk is not None, "google-adk no longer declares an opentelemetry-api pin"
        installed = metadata.version("opentelemetry-api")
        assert not adk.specifier.contains(installed), (
            f"opentelemetry-api {installed} now satisfies google-adk's {adk.specifier}. "
            "The override may no longer be needed — re-check Blocker 0 before removing it."
        )


class TestTheUpstreamConflictStillExists:
    def test_adk_and_the_agent_server_remain_mutually_exclusive(self) -> None:
        # The day this fails is the day the override can be deleted. Failing loudly is
        # the point: an override nobody revisits becomes folklore.
        adk = _declared_constraint("google-adk", "opentelemetry-api")
        server = _declared_constraint("azure-ai-agentserver-core", "opentelemetry-api")
        assert adk is not None and server is not None

        candidates = [
            v
            for v in ("1.39.0", "1.40.0", "1.41.0", "1.42.1", "1.43.0", "1.44.0", "1.45.0")
            if adk.specifier.contains(v) and server.specifier.contains(v)
        ]
        assert not candidates, (
            "google-adk and azure-ai-agentserver-core now agree on "
            f"{candidates}. Blocker 0 is over: remove the [tool.uv] override and this "
            "test, and update docs/compatibility.md."
        )


class TestTheOverriddenStackActuallyWorks:
    """The override trades an install-time failure for a runtime one. Exercise it."""

    def test_adk_telemetry_tracer_resolves(self) -> None:
        from google.adk.telemetry import tracer

        assert tracer is not None
        assert hasattr(tracer, "start_as_current_span")

    def test_adk_agent_and_function_tool_construct(self) -> None:
        from google.adk.agents import LlmAgent
        from google.adk.models.lite_llm import LiteLlm

        def sample_tool() -> dict[str, str]:
            """A zero-argument tool, matching this project's tool shape."""
            return {"ok": "yes"}

        built = LlmAgent(
            name="override_guard",
            model=LiteLlm(model="azure/unit-test-not-called"),
            instruction="unit test",
            tools=[sample_tool],
        )
        assert len(built.tools) == 1

    def test_the_agent_server_host_imports(self) -> None:
        from azure.ai.agentserver.responses import ResponsesAgentServerHost

        assert ResponsesAgentServerHost is not None

    def test_both_halves_of_opentelemetry_are_the_same_version(self) -> None:
        # A split API/SDK pair is the specific way this override fails quietly.
        api = Version(metadata.version("opentelemetry-api"))
        sdk = Version(metadata.version("opentelemetry-sdk"))
        assert (api.major, api.minor) == (sdk.major, sdk.minor), (
            f"opentelemetry-api {api} and -sdk {sdk} are on different minor versions"
        )
