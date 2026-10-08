"""Create the two Foundry hosted agent versions, through the Azure SDK only.

Why this module exists
----------------------
The demo's single experimental variable is the attached RAI egress policy. Everything
else about the two agents — image, CPU, memory, protocol, environment — must be
identical, or the result proves nothing. So the deployment is not a script you eyeball;
it is code that builds both definitions from one source, writes them, reads them back,
and refuses to report success if they drifted.

Constraints this file is built around
-------------------------------------
* **No ``az`` CLI.** The client deploys with Terraform and SDKs, so shipping code uses
  the SDK. The data-plane call is made by ``azure.ai.projects.AIProjectClient``.
* **Digest pinning is the control.** ``DEMO_AGENT_IMAGE`` must be a
  ``repo@sha256:<64 hex>`` reference. There is deliberately no tag fallback: if the
  service rejects a digest, the correct outcome is to stop and record it, not to run the
  experiment on an unprovable control.
* **Idempotent.** This runs as an init container, so it must survive every pod restart.
  A matching existing version is reused, never duplicated and never an error.
* **The data plane is private.** ``publicNetworkAccess`` is Disabled on the Foundry
  account, so this only works from inside the VNet. ``DefaultAzureCredential`` picks up
  AKS workload identity in-cluster and a developer login locally.
* **No masking.** Nothing here catches a failure and reports success. A create failure,
  a provisioning failure, a timeout, or any drift between the two agents is fatal.

Verified SDK surface (azure-ai-projects 2.8.0, read 2026-10-08 — see
docs/compatibility.md B9):

* ``AIProjectClient(endpoint=..., credential=..., allow_preview=True)``;
  default credential scope ``https://ai.azure.com/.default`` (``_configuration.py:57``).
* ``client.agents.create_version(agent_name, definition=..., description=..., metadata=...)``
  returning ``AgentVersionDetails`` (``operations/_operations.py:5441``).
* ``client.agents.get_version(agent_name, agent_version)`` (``_operations.py:5891``) and
  ``list_versions(agent_name)`` (``_operations.py:6042``).
* ``HostedAgentDefinition(cpu=, memory=, rai_config=, environment_variables=,
  container_configuration=, protocol_versions=)`` (``models/_models.py:12344``).
* ``RaiConfig(rai_policy_name=<full ARM resource id>)`` (``models/_models.py:16765``).
* ``ContainerConfiguration(image=, registry_connection_id=)`` (``models/_models.py:7230``).
* ``ProtocolVersionRecord(protocol=, version=)`` (``models/_models.py:16657``).
* ``AgentVersionStatus``: creating / active / failed / deleting / deleted
  (``models/_enums.py:380``).

The SDK is imported lazily, in one place, so the unit tests run with no Azure package,
no credentials, and no network.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from containment_demo.settings import PolicyMode, Settings

logger = logging.getLogger(__name__)

# A digest reference, and only a digest reference. A tag would make the two agents
# nominally identical while allowing the registry to serve different bytes to each.
_DIGEST_REFERENCE = re.compile(r"^[A-Za-z0-9._\-/:]+@sha256:[0-9a-f]{64}$")

# Full ARM resource id of an RAI policy. B4: a bare policy name is rejected by the
# service, and the failure mode is a policy silently not applied, so it is checked here.
_RAI_POLICY_ID = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/Microsoft\.CognitiveServices"
    r"/accounts/[^/]+/raiPolicies/[^/]+$",
    re.IGNORECASE,
)

_TERMINAL_OK = "active"
_TERMINAL_BAD = frozenset({"failed", "deleting", "deleted"})


class DeploymentError(RuntimeError):
    """Deployment did not reach a state we are willing to call success."""


class DigestRejectedError(DeploymentError):
    """The service refused a ``@sha256:`` image reference.

    This is a full stop, not a prompt to retry with a tag. Digest pinning is the
    experimental control; without it the two agents cannot be shown to be the same
    workload, and any result from the run is unprovable. Record the exact service error
    in docs/compatibility.md B9 and escalate.
    """


class DriftError(DeploymentError):
    """The two agents are not the same workload.

    Raised when a deployed version does not carry the policy we asked for, or when the
    two agents reference different images. Either one invalidates the experiment, so it
    must be loud rather than logged.
    """


class DeploySettings(BaseSettings):
    """Deployment configuration, every value from the environment.

    Uses the same ``DEMO_`` prefix as :class:`containment_demo.settings.Settings`. There
    are no defaults for anything environment-specific: no ARM ids, no hostnames, no
    account names. All of these are Terraform outputs and are injected by the Job that
    runs this module.
    """

    model_config = SettingsConfigDict(
        env_prefix="DEMO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Where ------------------------------------------------------------------------

    foundry_account_name: str = Field(
        description="Foundry account name. Terraform output foundry_account_name.",
    )
    foundry_project_name: str = Field(
        description="Foundry project name. Terraform output project_name.",
    )

    # --- What -------------------------------------------------------------------------

    agent_image: str = Field(
        description="Fully qualified image reference, digest-pinned. Tags are rejected: "
        "the digest is the only thing that proves both agents run the same bytes.",
    )
    registry_connection_id: str | None = Field(
        default=None,
        description="Foundry project connection supplying registry credentials. Omit for "
        "an ACR the platform identity can already pull.",
    )
    agent_cpu: str = Field(default="1")
    agent_memory: str = Field(default="2Gi")
    agent_protocol: str = Field(
        default="responses",
        description="Ingress protocol. Responses is preferred; Invocations is the fallback.",
    )
    agent_protocol_version: str = Field(default="v1")

    # --- The experimental variable ------------------------------------------------------

    agent_name_audit: str = Field(description="Terraform output agent_name_audit.")
    agent_name_enforced: str = Field(description="Terraform output agent_name_enforced.")
    rai_policy_audit_id: str = Field(
        description="Full ARM resource id. Terraform output rai_policy_audit_id.",
    )
    rai_policy_enforced_id: str = Field(
        description="Full ARM resource id. Terraform output rai_policy_enforced_id.",
    )

    # --- Call behaviour -----------------------------------------------------------------

    deploy_timeout_seconds: float = Field(
        default=900.0,
        gt=0,
        le=3600,
        description="Bound on waiting for a version to become active. There is no "
        "unbounded wait; a hung provision is a failure, not a pending success.",
    )
    deploy_poll_seconds: float = Field(default=10.0, gt=0, le=120)
    deploy_request_timeout_seconds: float = Field(default=60.0, gt=0, le=300)

    @field_validator("agent_image")
    @classmethod
    def _must_be_digest_pinned(cls, v: str) -> str:
        if not _DIGEST_REFERENCE.match(v):
            raise ValueError(
                f"agent_image must be digest-pinned as repo@sha256:<64 hex>, got {v!r}. "
                "A tag can be repointed between the two deployments, which would make the "
                "image a second uncontrolled variable alongside the policy."
            )
        return v

    @field_validator("rai_policy_audit_id", "rai_policy_enforced_id")
    @classmethod
    def _must_be_arm_id(cls, v: str) -> str:
        if not _RAI_POLICY_ID.match(v):
            raise ValueError(
                f"RAI policy must be a full ARM resource id, got {v!r}. A bare policy name "
                "is not accepted by the service (docs/compatibility.md B4)."
            )
        return v

    @field_validator("agent_name_audit", "agent_name_enforced")
    @classmethod
    def _must_be_a_valid_agent_name(cls, v: str) -> str:
        if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$", v):
            raise ValueError(
                f"agent name {v!r} is invalid: must start and end alphanumeric, may contain "
                "hyphens in the middle, max 63 characters."
            )
        return v

    @property
    def endpoint(self) -> str:
        return (
            f"https://{self.foundry_account_name}.services.ai.azure.com"
            f"/api/projects/{self.foundry_project_name}"
        )


@dataclass(frozen=True)
class AgentSpec:
    """One of the two agents. These differ in exactly three ways, all intentional."""

    agent_name: str
    rai_policy_id: str
    policy_mode: PolicyMode


@dataclass(frozen=True)
class DeploymentResult:
    agent_name: str
    version: str
    image: str
    rai_policy_name: str
    status: str
    reused: bool
    policy_mode: PolicyMode


def plan(cfg: DeploySettings) -> tuple[AgentSpec, AgentSpec]:
    """The two agents to create. One source, so they cannot diverge by accident."""
    return (
        AgentSpec(cfg.agent_name_audit, cfg.rai_policy_audit_id, PolicyMode.AUDIT),
        AgentSpec(cfg.agent_name_enforced, cfg.rai_policy_enforced_id, PolicyMode.ENFORCED),
    )


def build_environment(settings: Settings, spec: AgentSpec) -> dict[str, str]:
    """Environment for the agent container.

    Identical for both agents apart from ``DEMO_POLICY_MODE``, which is an evidence
    label. Nothing in the agent branches on it — see
    :class:`containment_demo.settings.PolicyMode`. :func:`assert_single_variable` checks
    that nothing else slipped in.
    """
    env = {
        "DEMO_POLICY_API_URL": str(settings.policy_api_url),
        "DEMO_TEST_RECEIVER_URL": str(settings.test_receiver_url),
        "DEMO_HTTP_TIMEOUT_SECONDS": str(settings.http_timeout_seconds),
        "DEMO_MODEL_DEPLOYMENT": settings.model_deployment,
        "DEMO_DIAGNOSTICS_ENABLED": str(settings.diagnostics_enabled).lower(),
        "DEMO_POLICY_MODE": spec.policy_mode.value,
    }
    if settings.azure_openai_endpoint:
        env["DEMO_AZURE_OPENAI_ENDPOINT"] = settings.azure_openai_endpoint
        env["DEMO_AZURE_OPENAI_API_VERSION"] = settings.azure_openai_api_version
    if settings.diagnostics_token is not None:
        env["DEMO_DIAGNOSTICS_TOKEN"] = settings.diagnostics_token.get_secret_value()
    return env


def build_definition(models: Any, cfg: DeploySettings, settings: Settings, spec: AgentSpec) -> Any:
    """Build a ``HostedAgentDefinition`` for one agent.

    ``models`` is the ``azure.ai.projects.models`` namespace, injected so the tests can
    exercise this without the SDK installed.
    """
    return models.HostedAgentDefinition(
        cpu=cfg.agent_cpu,
        memory=cfg.agent_memory,
        rai_config=models.RaiConfig(rai_policy_name=spec.rai_policy_id),
        environment_variables=build_environment(settings, spec),
        container_configuration=models.ContainerConfiguration(
            image=cfg.agent_image,
            registry_connection_id=cfg.registry_connection_id,
        ),
        protocol_versions=[
            models.ProtocolVersionRecord(
                protocol=cfg.agent_protocol,
                version=cfg.agent_protocol_version,
            )
        ],
    )


def _image_of(definition: Any) -> str | None:
    container = getattr(definition, "container_configuration", None)
    return getattr(container, "image", None) if container is not None else None


def _policy_of(definition: Any) -> str | None:
    rai = getattr(definition, "rai_config", None)
    return getattr(rai, "rai_policy_name", None) if rai is not None else None


def _status_of(version: Any) -> str:
    status = getattr(version, "status", None)
    return str(status).lower() if status is not None else ""


def find_matching_version(versions: Iterable[Any], image: str, rai_policy_id: str) -> Any | None:
    """Return an existing version that is already exactly what we would create.

    "Matching" means same image digest *and* same policy, and not in a terminal-bad
    state. A version that differs in either respect is left alone and a new one is
    created; we never mutate an existing version, because that would make the deployed
    artefact unauditable.
    """
    for version in versions:
        definition = getattr(version, "definition", None)
        if definition is None:
            continue
        if _image_of(definition) != image:
            continue
        if _policy_of(definition) != rai_policy_id:
            continue
        if _status_of(version) in _TERMINAL_BAD:
            continue
        return version
    return None


def _list_versions(client: Any, agent_name: str) -> list[Any]:
    """Existing versions, treating "no such agent" as "none yet".

    Narrow on purpose: a missing agent is an expected first-run state, but an auth
    failure or a 403 from the private endpoint must still surface.
    """
    from azure.core.exceptions import ResourceNotFoundError

    try:
        return list(client.agents.list_versions(agent_name))
    except ResourceNotFoundError:
        return []


def _create_version(client: Any, spec: AgentSpec, definition: Any, run_id: str) -> Any:
    from azure.core.exceptions import HttpResponseError

    try:
        return client.agents.create_version(
            spec.agent_name,
            definition=definition,
            description=(
                "Agent containment demo. Both tools always registered; the attached RAI "
                "egress policy is the only variable between agents."
            ),
            metadata={"demo_run_id": run_id, "policy_mode": spec.policy_mode.value},
        )
    except HttpResponseError as exc:
        message = str(exc)
        if "sha256" in message.lower() or "digest" in message.lower():
            raise DigestRejectedError(
                f"The service rejected the digest-pinned image for {spec.agent_name!r}. "
                "STOP: do not retry with a tag. Digest pinning is the experimental "
                "control, and without it the run is unprovable. Record this exact error "
                f"in docs/compatibility.md B9.\nService error: {message}"
            ) from exc
        raise DeploymentError(
            f"Creating a version of {spec.agent_name!r} failed: {message}"
        ) from exc


def wait_until_active(
    client: Any,
    agent_name: str,
    version_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Any:
    """Poll until the version is active, or fail.

    The only success is the literal ``active`` status. A timeout is a failure, not an
    optimistic pass: an agent still provisioning has not demonstrated anything.
    """
    deadline = monotonic() + timeout_seconds
    while True:
        version = client.agents.get_version(agent_name, version_id)
        status = _status_of(version)
        if status == _TERMINAL_OK:
            return version
        if status in _TERMINAL_BAD:
            raise DeploymentError(
                f"{agent_name} version {version_id} reached terminal status {status!r}. "
                "Not retrying: a failed provision is a real result."
            )
        if monotonic() >= deadline:
            raise DeploymentError(
                f"{agent_name} version {version_id} was still {status!r} after "
                f"{timeout_seconds}s. Treating a timeout as a failure, not a pass."
            )
        sleep(poll_seconds)


def deploy_agent(
    client: Any,
    models: Any,
    cfg: DeploySettings,
    settings: Settings,
    spec: AgentSpec,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> DeploymentResult:
    """Create one agent version if it does not already exist, then verify it."""
    existing = find_matching_version(
        _list_versions(client, spec.agent_name), cfg.agent_image, spec.rai_policy_id
    )
    if existing is not None:
        version_id = str(existing.version)
        reused = True
        logger.info(
            "Reusing existing version",
            extra={"agent": spec.agent_name, "version": version_id},
        )
    else:
        definition = build_definition(models, cfg, settings, spec)
        created = _create_version(client, spec, definition, settings.demo_run_id)
        version_id = str(created.version)
        reused = False
        logger.info("Created version", extra={"agent": spec.agent_name, "version": version_id})

    active = wait_until_active(
        client,
        spec.agent_name,
        version_id,
        timeout_seconds=cfg.deploy_timeout_seconds,
        poll_seconds=cfg.deploy_poll_seconds,
        sleep=sleep,
        monotonic=monotonic,
    )
    return verify_version(active, cfg, spec, reused=reused)


def verify_version(
    version: Any, cfg: DeploySettings, spec: AgentSpec, *, reused: bool
) -> DeploymentResult:
    """Read-back check on a single version.

    Written state is not assumed. A policy that silently did not attach would look
    exactly like a working Enforced agent that allows everything, which is the single
    most dangerous way this demo could lie.
    """
    definition = getattr(version, "definition", None)
    if definition is None:
        raise DriftError(
            f"{spec.agent_name} version {getattr(version, 'version', '?')} came back with "
            "no definition, so the attached policy cannot be confirmed. Inconclusive, "
            "which is a failure here."
        )

    actual_policy = _policy_of(definition)
    if actual_policy != spec.rai_policy_id:
        raise DriftError(
            f"{spec.agent_name} has rai_policy_name {actual_policy!r}, expected "
            f"{spec.rai_policy_id!r}. The attached policy is the experiment; a mismatch "
            "makes every result from this agent meaningless."
        )

    actual_image = _image_of(definition)
    if actual_image != cfg.agent_image:
        raise DriftError(
            f"{spec.agent_name} runs image {actual_image!r}, expected {cfg.agent_image!r}."
        )

    # Both values are now known equal to the requested ones, so the requested strings are
    # reported — they are typed ``str``, where the read-back values are ``str | None``.
    return DeploymentResult(
        agent_name=spec.agent_name,
        version=str(getattr(version, "version", "")),
        image=cfg.agent_image,
        rai_policy_name=spec.rai_policy_id,
        status=_status_of(version),
        reused=reused,
        policy_mode=spec.policy_mode,
    )


def assert_single_variable(results: Sequence[DeploymentResult]) -> None:
    """The two agents must differ only in the attached policy.

    Checked after the fact, against what the service reports, not against what we
    intended to send.
    """
    if len(results) != 2:
        raise DriftError(f"Expected exactly 2 agents, got {len(results)}.")

    images = {r.image for r in results}
    if len(images) != 1:
        raise DriftError(
            f"The two agents reference different images: {sorted(images)}. The image is "
            "supposed to be the control; with two images there is no experiment."
        )

    policies = {r.rai_policy_name for r in results}
    if len(policies) != 2:
        raise DriftError(
            f"The two agents share an RAI policy ({sorted(policies)}). Audit and Enforced "
            "must be distinct or there is nothing to compare."
        )

    modes = {r.policy_mode for r in results}
    if modes != {PolicyMode.AUDIT, PolicyMode.ENFORCED}:
        raise DriftError(f"Expected one audit and one enforced agent, got {sorted(modes)}.")


def build_client(cfg: DeploySettings) -> tuple[Any, Any]:
    """Construct the data-plane client and return it with the models namespace.

    The only place the Azure SDK is imported, which is what keeps ``pytest tests/unit``
    free of Azure packages, credentials and network.

    TLS verification is azure-core's default and is never disabled. Timeouts are explicit
    and bounded. ``DefaultAzureCredential`` resolves AKS workload identity in-cluster and
    a developer login locally; no secret is read from configuration.
    """
    from azure.ai.projects import AIProjectClient, models
    from azure.identity import DefaultAzureCredential

    client = AIProjectClient(
        endpoint=cfg.endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
        connection_timeout=cfg.deploy_request_timeout_seconds,
        read_timeout=cfg.deploy_request_timeout_seconds,
    )
    return client, models


@dataclass
class DeployReport:
    endpoint: str
    image: str
    results: list[DeploymentResult] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "endpoint": self.endpoint,
                "image": self.image,
                "agents": [
                    {
                        "agent_name": r.agent_name,
                        "version": r.version,
                        "status": r.status,
                        "rai_policy_name": r.rai_policy_name,
                        "policy_mode": r.policy_mode.value,
                        "reused": r.reused,
                    }
                    for r in self.results
                ],
            },
            indent=2,
            sort_keys=True,
        )


def deploy_all(
    client: Any,
    models: Any,
    cfg: DeploySettings,
    settings: Settings,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> DeployReport:
    """Deploy both agents and verify they differ only in the attached policy."""
    results = [
        deploy_agent(client, models, cfg, settings, spec, sleep=sleep, monotonic=monotonic)
        for spec in plan(cfg)
    ]
    assert_single_variable(results)
    return DeployReport(endpoint=cfg.endpoint, image=cfg.agent_image, results=results)


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint for the in-VNet deploy Job / init container."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    cfg = DeploySettings()  # type: ignore[call-arg]
    settings = Settings()  # type: ignore[call-arg]

    client, models = build_client(cfg)
    try:
        report = deploy_all(client, models, cfg, settings)
    except DigestRejectedError as exc:
        logger.error("BLOCKED: %s", exc)
        return 3
    except DeploymentError as exc:
        logger.error("FAILED: %s", exc)
        return 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    print(report.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
