"""Tests for the agent deployment module.

These run with no network, no Azure credentials, and without ``azure-ai-projects``
installed. The SDK client and its models namespace are injected, so everything here
exercises our logic rather than Microsoft's.

The one test that touches the real SDK is skipped when the package is absent, and even
then it only constructs model objects in memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pytest
from pydantic import ValidationError

from containment_demo.deploy import (
    DeploymentError,
    DeploySettings,
    DigestRejectedError,
    DriftError,
    UnrecognisedStatusError,
    _normalise_status,
    _service_error_of,
    _status_of,
    build_definition,
    build_environment,
    deploy_all,
    find_matching_version,
    plan,
    poll_attempts,
    wait_until_ready,
)
from containment_demo.settings import PolicyMode, Settings

IMAGE = "demoacr.azurecr.io/containment-demo@sha256:" + "a" * 64
OTHER_IMAGE = "demoacr.azurecr.io/containment-demo@sha256:" + "b" * 64
ARM_PREFIX = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-demo"
    "/providers/Microsoft.CognitiveServices/accounts/foundry-demo/raiPolicies"
)
AUDIT_POLICY = f"{ARM_PREFIX}/containment-audit"
ENFORCED_POLICY = f"{ARM_PREFIX}/containment-enforced"


# --- fakes ---------------------------------------------------------------------------
#
# Deliberately dumb stand-ins. They record what was asked for and hand back what the
# service would; none of them reach the network.


@dataclass
class FakeRaiConfig:
    rai_policy_name: str
    invocations_moderation: Any = None


@dataclass
class FakeContainerConfiguration:
    image: str
    registry_connection_id: str | None = None


@dataclass
class FakeProtocolVersionRecord:
    protocol: str
    version: str


@dataclass
class FakeHostedAgentDefinition:
    cpu: str
    memory: str
    rai_config: FakeRaiConfig | None = None
    environment_variables: dict[str, str] | None = None
    container_configuration: FakeContainerConfiguration | None = None
    protocol_versions: list[FakeProtocolVersionRecord] | None = None


class FakeModels:
    RaiConfig = FakeRaiConfig
    ContainerConfiguration = FakeContainerConfiguration
    ProtocolVersionRecord = FakeProtocolVersionRecord
    HostedAgentDefinition = FakeHostedAgentDefinition


@dataclass
class FakeVersion:
    version: str
    definition: FakeHostedAgentDefinition | None
    status: Any = "active"
    error: Any = None
    # Set only for versions the fake itself created: they report creating once and then
    # reach active, which is what the service does on a healthy deployment.
    auto_ready: bool = False


@dataclass
class FakeAgentsOperations:
    existing: dict[str, list[FakeVersion]] = field(default_factory=dict)
    statuses: dict[str, list[str]] = field(default_factory=dict)
    created: list[tuple[str, FakeHostedAgentDefinition]] = field(default_factory=list)
    create_error: Exception | None = None
    get_version_calls: int = 0
    # What a DIRECT read returns when it disagrees with what list_versions said.
    direct: dict[tuple[str, str], FakeVersion] = field(default_factory=dict)

    def list_versions(self, agent_name: str) -> list[FakeVersion]:
        from azure.core.exceptions import ResourceNotFoundError

        if agent_name not in self.existing:
            raise ResourceNotFoundError(message=f"no agent {agent_name}")
        return self.existing[agent_name]

    def create_version(self, agent_name: str, **kwargs: Any) -> FakeVersion:
        if self.create_error is not None:
            raise self.create_error
        definition = kwargs["definition"]
        self.created.append((agent_name, definition))
        siblings = self.existing.setdefault(agent_name, [])
        version = FakeVersion(
            version=str(len(siblings) + 1),
            definition=definition,
            status="creating",
            auto_ready=True,
        )
        siblings.append(version)
        return version

    def get_version(self, agent_name: str, agent_version: str) -> FakeVersion:
        self.get_version_calls += 1
        if (agent_name, agent_version) in self.direct:
            return self.direct[(agent_name, agent_version)]
        versions = self.existing[agent_name]
        match = next(v for v in versions if v.version == agent_version)
        queued = self.statuses.get(agent_name)
        if queued:
            match.status = queued.pop(0)
        elif match.auto_ready:
            match.status = "active"
        # Otherwise the last reported status is sticky: a service does not silently
        # become active just because the test ran out of scripted values.
        return match


@dataclass
class FakeClient:
    agents: FakeAgentsOperations = field(default_factory=FakeAgentsOperations)


# --- fixtures ------------------------------------------------------------------------


def make_cfg(**overrides: object) -> DeploySettings:
    defaults: dict[str, object] = {
        "foundry_account_name": "foundry-demo",
        "foundry_project_name": "proj-demo",
        "agent_image": IMAGE,
        "agent_name_audit": "containment-demo-audit",
        "agent_name_enforced": "containment-demo-enforced",
        "rai_policy_audit_id": AUDIT_POLICY,
        "rai_policy_enforced_id": ENFORCED_POLICY,
    }
    defaults.update(overrides)
    return DeploySettings(**defaults)  # type: ignore[arg-type]


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "policy_api_url": "https://policy.example.com/",
        "test_receiver_url": "https://receiver.example.net/",
        "diagnostics_token": "test-diagnostics-token-value",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_env_bleed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stray DEMO_ variable in the developer's shell must not change a result."""
    for key in list(__import__("os").environ):
        if key.startswith("DEMO_"):
            monkeypatch.delenv(key, raising=False)


def run(client: FakeClient, cfg: DeploySettings, settings: Settings) -> Any:
    return deploy_all(
        client,
        FakeModels,
        cfg,
        settings,
        sleep=lambda _: None,
        monotonic=_FakeClock(),
    )


class _FakeClock:
    """Advances a full second per call so a bounded wait cannot hang a test."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        self._now += 1.0
        return self._now


# --- configuration -------------------------------------------------------------------


def test_tag_reference_is_rejected() -> None:
    """A tag can be repointed between the two deployments; the digest cannot."""
    with pytest.raises(ValidationError, match="digest-pinned"):
        make_cfg(agent_image="demoacr.azurecr.io/containment-demo:v1")


def test_bare_image_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="digest-pinned"):
        make_cfg(agent_image="containment-demo")


def test_short_digest_is_rejected() -> None:
    with pytest.raises(ValidationError, match="digest-pinned"):
        make_cfg(agent_image="demoacr.azurecr.io/demo@sha256:abc123")


def test_bare_policy_name_is_rejected() -> None:
    """B4: the service needs the full ARM id, and a bare name fails open-ish."""
    with pytest.raises(ValidationError, match="full ARM resource id"):
        make_cfg(rai_policy_audit_id="containment-audit")


def test_invalid_agent_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="invalid"):
        make_cfg(agent_name_audit="-leading-hyphen")


def test_endpoint_is_the_private_data_plane_url() -> None:
    assert make_cfg().endpoint == (
        "https://foundry-demo.services.ai.azure.com/api/projects/proj-demo"
    )


def test_no_hardcoded_environment_values() -> None:
    """Every environment-specific value must come from configuration."""
    with pytest.raises(ValidationError):
        DeploySettings()  # type: ignore[call-arg]


# --- plan and definition ---------------------------------------------------------------


def test_plan_is_one_audit_and_one_enforced() -> None:
    audit, enforced = plan(make_cfg())
    assert audit.policy_mode is PolicyMode.AUDIT
    assert enforced.policy_mode is PolicyMode.ENFORCED
    assert audit.rai_policy_id == AUDIT_POLICY
    assert enforced.rai_policy_id == ENFORCED_POLICY


def test_definition_carries_the_policy_arm_id_and_the_digest() -> None:
    cfg = make_cfg()
    audit, _ = plan(cfg)
    definition = build_definition(FakeModels, cfg, make_settings(), audit)
    assert definition.rai_config.rai_policy_name == AUDIT_POLICY
    assert definition.container_configuration.image == IMAGE
    assert definition.protocol_versions[0].protocol == "responses"


def test_registered_protocol_version_is_2_0_0_not_v1() -> None:
    """The platform rejected 'v1' at invoke time (HTTP 400, 2026-10-09) and named 2.0.0."""
    assert DeploySettings.model_fields["agent_protocol_version"].default == "2.0.0"
    cfg = make_cfg()
    audit, _ = plan(cfg)
    definition = build_definition(FakeModels, cfg, make_settings(), audit)
    assert definition.protocol_versions[0].version == "2.0.0"


def test_environment_differs_only_by_the_evidence_label() -> None:
    cfg = make_cfg()
    settings = make_settings()
    audit, enforced = plan(cfg)
    audit_env = build_environment(settings, audit)
    enforced_env = build_environment(settings, enforced)

    differing = {
        k for k in audit_env.keys() | enforced_env.keys() if audit_env.get(k) != enforced_env.get(k)
    }
    assert differing == {"DEMO_POLICY_MODE"}


def test_environment_never_contains_an_allowlist_hint() -> None:
    """Nothing handed to the container may tell it which host is special."""
    env = build_environment(make_settings(), plan(make_cfg())[0])
    joined = " ".join(f"{k}={v}" for k, v in env.items()).lower()
    for word in ("allowlist", "allowed_host", "blocked", "denied"):
        assert word not in joined


# --- idempotency ------------------------------------------------------------------------


def test_matching_version_is_found() -> None:
    version = FakeVersion(
        version="3",
        definition=FakeHostedAgentDefinition(
            cpu="1",
            memory="2Gi",
            rai_config=FakeRaiConfig(AUDIT_POLICY),
            container_configuration=FakeContainerConfiguration(IMAGE),
        ),
    )
    assert find_matching_version([version], IMAGE, AUDIT_POLICY) is version


def test_version_with_a_different_image_does_not_match() -> None:
    version = FakeVersion(
        version="3",
        definition=FakeHostedAgentDefinition(
            cpu="1",
            memory="2Gi",
            rai_config=FakeRaiConfig(AUDIT_POLICY),
            container_configuration=FakeContainerConfiguration(OTHER_IMAGE),
        ),
    )
    assert find_matching_version([version], IMAGE, AUDIT_POLICY) is None


def test_version_with_a_different_policy_does_not_match() -> None:
    version = FakeVersion(
        version="3",
        definition=FakeHostedAgentDefinition(
            cpu="1",
            memory="2Gi",
            rai_config=FakeRaiConfig(ENFORCED_POLICY),
            container_configuration=FakeContainerConfiguration(IMAGE),
        ),
    )
    assert find_matching_version([version], IMAGE, AUDIT_POLICY) is None


def test_failed_version_is_never_reused() -> None:
    version = FakeVersion(
        version="3",
        definition=FakeHostedAgentDefinition(
            cpu="1",
            memory="2Gi",
            rai_config=FakeRaiConfig(AUDIT_POLICY),
            container_configuration=FakeContainerConfiguration(IMAGE),
        ),
        status="failed",
    )
    assert find_matching_version([version], IMAGE, AUDIT_POLICY) is None


def test_first_run_creates_both_agents() -> None:
    client = FakeClient()
    report = run(client, make_cfg(), make_settings())
    assert [name for name, _ in client.agents.created] == [
        "containment-demo-audit",
        "containment-demo-enforced",
    ]
    assert all(not r.reused for r in report.results)


def test_rerun_creates_nothing_and_still_succeeds() -> None:
    """The init container restarts with the pod; a restart must not duplicate or fail."""
    client = FakeClient()
    run(client, make_cfg(), make_settings())
    client.agents.created.clear()

    report = run(client, make_cfg(), make_settings())
    assert client.agents.created == []
    assert all(r.reused for r in report.results)


def _stale_active_version_4() -> tuple[FakeClient, FakeHostedAgentDefinition]:
    """list_versions says version 1 is active; a direct read says failed/ImageError."""
    cfg = make_cfg()
    audit, _ = plan(cfg)
    definition = build_definition(FakeModels, cfg, make_settings(), audit)
    client = FakeClient()
    client.agents.existing[audit.agent_name] = [FakeVersion("1", definition, status="active")]
    client.agents.direct[(audit.agent_name, "1")] = FakeVersion(
        "1",
        definition,
        status="failed",
        error={"code": "ImageError", "message": "Container registry authentication failed"},
    )
    return client, definition


def test_list_active_but_direct_failed_is_not_reused() -> None:
    client, _ = _stale_active_version_4()
    report = run(client, make_cfg(), make_settings())
    audit = next(r for r in report.results if r.agent_name == make_cfg().agent_name_audit)
    assert not audit.reused
    assert audit.version == "2"
    assert [n for n, _ in client.agents.created].count(audit.agent_name) == 1


def test_direct_read_failure_is_logged_with_the_service_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="containment_demo.deploy")
    client, _ = _stale_active_version_4()
    run(client, make_cfg(), make_settings())
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "ImageError" in text
    assert "Skipping it" in text


def test_direct_read_that_confirms_active_is_still_reused() -> None:
    client = FakeClient()
    run(client, make_cfg(), make_settings())
    client.agents.created.clear()
    client.agents.get_version_calls = 0
    run(client, make_cfg(), make_settings())
    assert client.agents.created == []
    assert client.agents.get_version_calls >= 2


def test_service_error_is_read_from_a_mapping_when_there_is_no_attribute() -> None:
    """AgentVersionDetails declares no `error` field: getattr is None, the key is not."""

    class MappingOnly(dict[str, Any]):
        pass

    payload = {"code": "ImageError", "message": "AcrPull"}
    assert _service_error_of(MappingOnly(error=payload)) == payload
    assert _service_error_of(MappingOnly()) is None


def test_failed_message_carries_code_and_message() -> None:
    client = _version_reporting("failed")
    client.agents.existing["a"][0].error = {"code": "ImageError", "message": "AcrPull"}
    with pytest.raises(DeploymentError, match=r"ImageError.*AcrPull"):
        _wait(client)


def test_new_digest_creates_a_new_version() -> None:
    client = FakeClient()
    run(client, make_cfg(), make_settings())
    client.agents.created.clear()

    run(client, make_cfg(agent_image=OTHER_IMAGE), make_settings())
    assert len(client.agents.created) == 2


# --- waiting: the 2026-10-08 incident ------------------------------------------------------
#
# A healthy version was polled for 45 minutes and never accepted, and the loop emitted
# nothing about what it saw. Every test here covers one property of that failure.


def _wait(client: FakeClient, agent: str = "a", *, timeout: float = 12.0, poll: float = 3.0) -> Any:
    return wait_until_ready(
        client,
        agent,
        "1",
        timeout_seconds=timeout,
        poll_seconds=poll,
        sleep=lambda _: None,
        monotonic=_FakeClock(),
    )


def _version_reporting(*statuses: str) -> FakeClient:
    client = FakeClient()
    client.agents.existing["a"] = [FakeVersion("1", None, status=statuses[0])]
    client.agents.statuses["a"] = list(statuses)
    return client


@pytest.mark.parametrize("ready", ["active", "running"])
def test_ready_set_accepts_both_observed_values(ready: str) -> None:
    """`running` is what the live service returned on 2026-10-08.

    It is NOT in the SDK's AgentVersionStatus enum. Brian's production deployer
    (banking-agent-foundry-orchestrator, src/agents/deployer/deploy.py:20) has
    READY_STATUSES = {"active", "running"}. The enum is incomplete; the service is right.
    """
    version = _wait(_version_reporting("creating", ready))
    assert _status_of(version) == ready


@pytest.mark.parametrize("ready", ["Running", "ACTIVE"])
def test_ready_match_is_case_insensitive(ready: str) -> None:
    """The portal showed `Running` with a capital R."""
    assert _wait(_version_reporting(ready)) is not None


def test_enum_valued_status_is_matched_not_stringified() -> None:
    """The SDK coerces known values to a (str, Enum) member.

    `str(AgentVersionStatus.ACTIVE)` is 'AgentVersionStatus.ACTIVE', so the original
    `str(status).lower()` produced 'agentversionstatus.active' and could never match.
    Verified against azure-ai-projects 2.8.0 on 2026-10-08.
    """

    # (str, Enum) deliberately, not StrEnum: this must reproduce the SDK's own mixin,
    # where str(member) returns the qualified name. StrEnum would not show the bug.
    class StatusEnum(str, Enum):  # noqa: UP042
        ACTIVE = "active"

    assert str(StatusEnum.ACTIVE).lower() != "active"  # the original bug, reproduced
    assert _normalise_status(StatusEnum.ACTIVE) == "active"
    assert _wait(_version_reporting(StatusEnum.ACTIVE)) is not None  # type: ignore[arg-type]


def test_pending_statuses_keep_waiting() -> None:
    for pending in ("creating", "starting", "updating"):
        assert _wait(_version_reporting(pending, "active")) is not None


def test_failed_raises_immediately_without_exhausting_the_bound() -> None:
    client = _version_reporting("failed")
    with pytest.raises(DeploymentError, match="terminal status"):
        _wait(client, timeout=300.0)
    assert client.agents.get_version_calls == 1


def test_failed_includes_the_service_error_payload() -> None:
    client = _version_reporting("failed")
    client.agents.existing["a"][0].error = {"code": "ImagePullFailure"}
    with pytest.raises(DeploymentError, match="ImagePullFailure"):
        _wait(client)


def test_timeout_is_a_failure_not_a_pass() -> None:
    with pytest.raises(DeploymentError, match="Treating a timeout as a failure"):
        _wait(_version_reporting(*["creating"] * 200))


def test_the_loop_is_bounded_by_iteration_count() -> None:
    """A bounded `for` cannot fail to terminate, which `while True` demonstrably did.

    The clock is frozen, so a wall-clock deadline alone would never trip. The loop must
    still stop.
    """
    client = _version_reporting(*["creating"] * 500)
    with pytest.raises(DeploymentError):
        wait_until_ready(
            client,
            "a",
            "1",
            timeout_seconds=12.0,
            poll_seconds=3.0,
            sleep=lambda _: None,
            monotonic=lambda: 0.0,
        )
    assert client.agents.get_version_calls == poll_attempts(12.0, 3.0) == 4


def test_the_bound_is_derived_from_timeout_and_poll_interval() -> None:
    assert poll_attempts(120.0, 3.0) == 40
    assert poll_attempts(12.0, 3.0) == 4
    assert poll_attempts(1.0, 3.0) == 1
    assert poll_attempts(120.0, 0) == 1  # never a ZeroDivisionError mid-deployment


def test_unknown_status_is_surfaced_and_still_bounded() -> None:
    client = _version_reporting(*["wedged-new-status"] * 200)
    with pytest.raises(UnrecognisedStatusError, match="wedged-new-status"):
        _wait(client)
    assert client.agents.get_version_calls == poll_attempts(12.0, 3.0)


def test_unknown_status_is_never_treated_as_success() -> None:
    with pytest.raises(UnrecognisedStatusError):
        _wait(_version_reporting("succeeded"))


def test_unknown_status_that_later_becomes_ready_still_succeeds() -> None:
    assert _wait(_version_reporting("brand-new-pending-name", "running")) is not None


def test_status_is_logged_on_every_poll(caplog: pytest.LogCaptureFixture) -> None:
    """Defect 1. Silence is what made a healthy deploy indistinguishable from a hang."""
    caplog.set_level(logging.INFO, logger="containment_demo.deploy")
    _wait(_version_reporting("creating", "creating", "running"))

    polls = [r for r in caplog.records if "status=" in r.getMessage()]
    assert len(polls) >= 3
    assert "'creating'" in polls[0].getMessage()
    assert "attempt=1/4" in polls[0].getMessage()
    assert "elapsed=" in polls[0].getMessage()
    assert "a: version 1" in polls[0].getMessage()
    assert any("'running'" in r.getMessage() for r in polls)


def test_unrecognised_status_is_logged_as_a_warning_every_time(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="containment_demo.deploy")
    with pytest.raises(UnrecognisedStatusError):
        _wait(_version_reporting(*["mystery"] * 200))

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == poll_attempts(12.0, 3.0)
    assert all("UNRECOGNISED" in r.getMessage() for r in warnings)
    assert all("mystery" in r.getMessage() for r in warnings)


# --- read-back verification ----------------------------------------------------------------


def test_wrong_policy_on_read_back_fails_loudly() -> None:
    """The nightmare case: an Enforced agent that quietly has no policy attached."""
    client = FakeClient()

    original = FakeAgentsOperations.create_version

    def sabotage(self: FakeAgentsOperations, agent_name: str, **kwargs: Any) -> FakeVersion:
        version = original(self, agent_name, **kwargs)
        assert version.definition is not None
        version.definition.rai_config = None
        return version

    client.agents.create_version = sabotage.__get__(client.agents)  # type: ignore[method-assign]
    with pytest.raises(DriftError, match="rai_policy_name"):
        run(client, make_cfg(), make_settings())


def test_image_drift_between_the_two_agents_fails_loudly() -> None:
    client = FakeClient()
    original = FakeAgentsOperations.create_version

    def sabotage(self: FakeAgentsOperations, agent_name: str, **kwargs: Any) -> FakeVersion:
        version = original(self, agent_name, **kwargs)
        if agent_name.endswith("enforced"):
            assert version.definition is not None
            assert version.definition.container_configuration is not None
            version.definition.container_configuration.image = OTHER_IMAGE
        return version

    client.agents.create_version = sabotage.__get__(client.agents)  # type: ignore[method-assign]
    with pytest.raises(DriftError, match="image"):
        run(client, make_cfg(), make_settings())


def test_missing_definition_on_read_back_is_a_failure() -> None:
    client = FakeClient()
    original = FakeAgentsOperations.create_version

    def sabotage(self: FakeAgentsOperations, agent_name: str, **kwargs: Any) -> FakeVersion:
        version = original(self, agent_name, **kwargs)
        version.definition = None
        return version

    client.agents.create_version = sabotage.__get__(client.agents)  # type: ignore[method-assign]
    with pytest.raises(DriftError, match="no definition"):
        run(client, make_cfg(), make_settings())


def test_same_policy_on_both_agents_is_rejected() -> None:
    cfg = make_cfg(rai_policy_enforced_id=AUDIT_POLICY)
    with pytest.raises(DriftError, match="share an RAI policy"):
        run(FakeClient(), cfg, make_settings())


# --- digest rejection -------------------------------------------------------------------------


def test_digest_rejection_stops_and_never_falls_back_to_a_tag() -> None:
    from azure.core.exceptions import HttpResponseError

    client = FakeClient()
    client.agents.create_error = HttpResponseError(
        message="InvalidImageReference: image must specify a tag; digest sha256 references "
        "are not supported"
    )
    with pytest.raises(DigestRejectedError, match="STOP"):
        run(client, make_cfg(), make_settings())
    assert client.agents.created == []


def test_other_service_errors_are_not_mislabelled_as_a_digest_problem() -> None:
    from azure.core.exceptions import HttpResponseError

    from containment_demo.deploy import DeploymentError

    client = FakeClient()
    client.agents.create_error = HttpResponseError(message="Quota exceeded for hosted agents")
    with pytest.raises(DeploymentError) as excinfo:
        run(client, make_cfg(), make_settings())
    assert not isinstance(excinfo.value, DigestRejectedError)


# --- report ---------------------------------------------------------------------------------


def test_report_records_both_agents_and_one_image() -> None:
    report = run(FakeClient(), make_cfg(), make_settings())
    import json

    payload = json.loads(report.to_json())
    assert payload["image"] == IMAGE
    assert {a["policy_mode"] for a in payload["agents"]} == {"audit", "enforced"}
    assert {a["rai_policy_name"] for a in payload["agents"]} == {AUDIT_POLICY, ENFORCED_POLICY}


# --- the real SDK, if it happens to be installed ------------------------------------------------


def test_real_sdk_models_accept_our_keyword_arguments() -> None:
    """Guards against the SDK surface moving under us. No network, no credentials."""
    models = pytest.importorskip(
        "azure.ai.projects.models",
        reason="azure-ai-projects is an optional 'deploy' extra; not needed for unit tests",
    )
    cfg = make_cfg()
    audit, _ = plan(cfg)
    definition = build_definition(models, cfg, make_settings(), audit)
    assert definition.rai_config.rai_policy_name == AUDIT_POLICY
    assert definition.container_configuration.image == IMAGE
    assert definition["kind"] == "hosted"
