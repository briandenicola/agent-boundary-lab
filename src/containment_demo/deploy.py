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

**Do not take the status vocabulary from the SDK.** ``AgentVersionStatus``
(``models/_enums.py:380``) declares creating / active / failed / deleting / deleted and
is INCOMPLETE relative to the running service, which also returns ``running`` and, per
the reference implementation, ``starting`` and ``updating``. An earlier revision of this
file cited that enum here and used it to derive the success condition, and consequently
polled a healthy agent version for 45 minutes without ever accepting it. The authoritative
source for status values is observed service behaviour — see ``_READY_STATUSES`` below and
docs/compatibility.md B9b.

The SDK is imported lazily, in one place, so the unit tests run with no Azure package,
no credentials, and no network.
"""

from __future__ import annotations

import json
import logging
import math
import re
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
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

# Agent version statuses — taken from OBSERVED LIVE SERVICE BEHAVIOUR, not from a type.
#
# PRIMARY SOURCE: Brian's production deployer,
# briandenicola/banking-agent-foundry-orchestrator, src/agents/deployer/deploy.py
# lines 20-21, read 2026-10-08:
#
#     READY_STATUSES   = {"active", "running"}
#     PENDING_STATUSES = {"creating", "starting", "updating"}
#
# CORROBORATION: the Azure portal showed containment-demo-audit v1 as "Running" on
# 2026-10-08 while it was in fact healthy and serving.
#
# THE SDK ENUM IS INCOMPLETE AND MUST NOT BE TREATED AS AUTHORITATIVE.
# ``AgentVersionStatus`` (azure-ai-projects 2.8.0, models/_enums.py:380) declares only
# creating / active / failed / deleting / deleted. It contains no "running", "starting"
# or "updating". This module previously derived ``_TERMINAL_OK = "active"`` from that
# enum, and as a result polled a healthy version for 45 minutes without ever accepting
# it. A generated type definition describes what the SDK was generated against, not what
# the service returns today. See docs/compatibility.md B9b.
_READY_STATUSES = frozenset({"active", "running"})
_PENDING_STATUSES = frozenset({"creating", "starting", "updating"})
# Stricter than the reference, which fails fast only on "failed". A version being deleted
# or already deleted can never become ready, so waiting on it is pure dead time.
_FAILED_STATUSES = frozenset({"failed", "deleting", "deleted"})
_KNOWN_STATUSES = _READY_STATUSES | _PENDING_STATUSES | _FAILED_STATUSES


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


class UnrecognisedStatusError(DeploymentError):
    """The service reported a version status we have never seen.

    Not in ``_READY_STATUSES``, ``_PENDING_STATUSES`` or ``_FAILED_STATUSES``.
    Deliberately not treated as success and deliberately not waited on forever. Record
    the verbatim value in docs/compatibility.md B9b with the date observed, then decide
    which set it belongs in.
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
    agent_protocol_version: str = Field(
        default="2.0.0",
        description=(
            "Responses protocol version registered on the hosted agent. 'v1' was accepted "
            "at create time but rejected at invoke time (docs/compatibility.md B9d). "
            "2.0.0 is the version the platform named; UNVERIFIED until a live invoke succeeds."
        ),
    )

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
        default=120.0,
        gt=0,
        le=600,
        description="Bound on waiting for a version to reach a known-good status. "
        "120s because an observed healthy hosted-agent version provisioned in well under "
        "a minute (2026-10-08, containment-demo-audit v1), so 120s is already twice the "
        "only provisioning time we have measured. The 600s ceiling is five times that "
        "again and exists only so a genuinely degraded region can be waited out "
        "deliberately; the previous 3600s ceiling could hide a hang for an hour. There is "
        "no unbounded wait: a hung provision is a failure, not a pending success.",
    )
    deploy_poll_seconds: float = Field(
        default=3.0,
        gt=0,
        le=30,
        description="3s gives ~40 observations inside the default 120s budget, which is "
        "enough resolution to see a status transition rather than infer one.",
    )
    deploy_request_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        le=60,
        description="Per-request connect and read timeout. Kept well inside the overall "
        "budget: the poll loop is single-threaded and cannot observe its own deadline "
        "while blocked inside an HTTP call.",
    )
    deploy_retry_total: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Explicit cap on azure-core's retry policy. The default of 10 with a "
        "120s backoff ceiling lets a single call absorb many minutes, which is the one "
        "mechanism in this module that can defer the deadline past its bound.",
    )

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


def _raw_status(version: Any) -> Any:
    """The status exactly as the SDK handed it over, untouched.

    Kept separate from the normalised form so that logs and error messages can quote the
    verbatim value. The verbatim value is the single most important diagnostic this
    module produces; normalising before logging it is how a 45-minute hang becomes
    unexplainable.
    """
    return getattr(version, "status", None)


def _normalise_status(raw: Any) -> str:
    """Normalise a status to the lowercase wire value for comparison.

    ``AgentVersionDetails.status`` is typed ``Optional[Union[str, AgentVersionStatus]]``
    and the SDK's behaviour differs by value. Verified 2026-10-08 against
    azure-ai-projects 2.8.0 by deserialising each case:

    * A value the enum knows is coerced to the enum member. ``"active"`` becomes
      ``AgentVersionStatus.ACTIVE``, and because that is a ``(str, Enum)`` mixin,
      ``str(member)`` returns ``'AgentVersionStatus.ACTIVE'``. The previous
      ``str(status).lower()`` therefore produced ``'agentversionstatus.active'``, which
      could never equal ``'active'`` — so this poller could not terminate on success even
      when the service said ``active``.
    * A value the enum does not know passes through as a plain ``str``, unmangled.
      ``"Running"`` deserialises to ``'Running'``; the ``CaseInsensitiveEnumMeta`` lookup
      raises rather than silently mapping it to something else.

    So ``.value`` is read first, with the raw object as the fallback. That is correct for
    both cases and loses nothing.
    """
    if raw is None:
        return ""
    value = getattr(raw, "value", raw)
    return str(value).strip().lower()


def _status_of(version: Any) -> str:
    return _normalise_status(_raw_status(version))


def _matching_versions(versions: Iterable[Any], image: str, rai_policy_id: str) -> Iterator[Any]:
    """Every listed version that looks reusable. LIST status is a hint, never a verdict."""
    for version in versions:
        definition = getattr(version, "definition", None)
        if definition is None:
            continue
        if _image_of(definition) != image:
            continue
        if _policy_of(definition) != rai_policy_id:
            continue
        if _status_of(version) not in _READY_STATUSES | _PENDING_STATUSES:
            continue
        yield version


def find_matching_version(versions: Iterable[Any], image: str, rai_policy_id: str) -> Any | None:
    """Return an existing version that is already exactly what we would create.

    "Matching" means same image digest *and* same policy *and* a status that can still
    become ready. A version that differs in either respect is left alone and a new one is
    created; we never mutate an existing version, because that would make the deployed
    artefact unauditable.

    The status filter is an allowlist of ready-or-pending, matching the reference
    implementation (``_find_matching_version``, reference lines 333-334 and 371-372),
    rather than a denylist of bad states. A version in an unrecognised status is
    therefore not reused: we do not know whether it can ever become ready, and adopting
    it would hide the unrecognised value instead of surfacing it. A pending version IS
    reused and then waited on, which is the stuck-``creating`` case.
    """
    return next(_matching_versions(versions, image, rai_policy_id), None)


def _confirmed_reusable(client: Any, agent_name: str, candidate: Any) -> Any | None:
    """Confirm a reuse candidate with a DIRECT get_version read.

    Observed 2026-10-09: list_versions reported containment-demo-audit:4 as active while
    get_version returned status 'failed' with error ImageError (ACR authentication /
    AcrPull). Reusing it crash-looped the init container. List status is not trustworthy
    for readiness. A permission fix does not heal a failed version; a new one is created.
    """
    version_id = str(candidate.version)
    direct = client.agents.get_version(agent_name, version_id)
    status = _status_of(direct)
    if status in _READY_STATUSES | _PENDING_STATUSES:
        return direct
    logger.warning(
        "%s: version %s looked reusable in list_versions but a direct read says status=%r "
        "(verbatim %r), service error: %s. Skipping it; a new version will be created.",
        agent_name,
        version_id,
        status,
        _raw_status(direct),
        _service_error_of(direct),
    )
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


def poll_attempts(timeout_seconds: float, poll_seconds: float) -> int:
    """How many polls fit in the budget.

    Derived from the two configured values so the iteration bound and the time budget
    cannot disagree with each other. At the defaults this is ceil(120 / 3) = 40.

    ``DeploySettings`` enforces ``poll_seconds > 0``; the guard here exists so that a
    caller passing zero gets one bounded poll rather than a ZeroDivisionError from inside
    a deployment.
    """
    if poll_seconds <= 0:
        return 1
    return max(1, math.ceil(timeout_seconds / poll_seconds))


def _service_error_of(version: Any) -> Any:
    """Whatever the service attached to a failure, for verbatim inclusion in the error.

    ``AgentVersionDetails`` (azure-ai-projects 2.8.0) declares NO ``error`` field, so
    ``getattr(version, "error")`` is None even when the wire body carries one. The model is
    a MutableMapping and keeps undeclared wire fields, so they are read by key. Verified
    2026-10-09 by deserialising {"status": "failed", "error": {...}}: getattr -> None,
    version["error"] -> the payload. That is why the log said "Service error: None".
    """
    for key in ("error", "last_error", "status_details"):
        value = getattr(version, key, None)
        if value is None and hasattr(version, "get"):
            value = version.get(key)
        if value is not None:
            return value
    return None


def wait_until_ready(
    client: Any,
    agent_name: str,
    version_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Any:
    """Poll until the version reports a ready status, or fail. Bounded by iteration count.

    Modelled directly on Brian's production deployer
    (briandenicola/banking-agent-foundry-orchestrator, src/agents/deployer/deploy.py
    lines 417-433), which is working against this same service.

    Three properties, each one a thing this function previously got wrong:

    **It is a bounded loop, not ``while True``.** A ``for`` over a computed attempt count
    cannot fail to terminate. The previous version used ``while True`` with a wall-clock
    deadline and did not terminate for 45 minutes on 2026-10-08 despite a 900s bound, for
    reasons never established. A bounded loop removes that entire failure class rather
    than relying on an explanation. The wall-clock deadline is kept as well, as whichever
    trips first, but the iteration bound is the structural guarantee.

    **It logs the status on every single poll**, flushed, with agent, version, attempt and
    elapsed time. The previous version computed the status and logged nothing, so a
    healthy deployment and a hung one produced byte-identical output: silence. The status
    string is the single most important diagnostic this module produces.

    **Ready means ready as the service reports it**, from ``_READY_STATUSES``, which comes
    from observed live behaviour rather than from the SDK's incomplete enum.

    A timeout is a FAILURE and never an optimistic pass: a version that has not reported
    ready has demonstrated nothing.
    """
    started = monotonic()
    deadline = started + timeout_seconds
    attempts = poll_attempts(timeout_seconds, poll_seconds)
    status = ""
    raw: Any = None
    unrecognised: str | None = None

    for attempt in range(1, attempts + 1):
        version = client.agents.get_version(agent_name, version_id)
        raw = _raw_status(version)
        status = _normalise_status(raw)
        elapsed = monotonic() - started

        # Every poll, unconditionally. This is the line whose absence cost 45 minutes.
        logger.info(
            "%s: version %s status=%r attempt=%d/%d elapsed=%.1fs",
            agent_name,
            version_id,
            status,
            attempt,
            attempts,
            elapsed,
        )

        if status in _READY_STATUSES:
            logger.info(
                "%s: version %s is ready (status=%r) after %.1fs",
                agent_name,
                version_id,
                status,
                elapsed,
            )
            return version

        if status in _FAILED_STATUSES:
            raise DeploymentError(
                f"{agent_name}: version {version_id} reached terminal status {status!r} "
                f"after {elapsed:.1f}s. "
                f"Service error (code/message): {_service_error_of(version)!r}. "
                "Not retrying: a failed provision is a real result."
            )

        if status not in _KNOWN_STATUSES:
            # Loudly, every time it is seen -- not once and then silently tolerated.
            unrecognised = status
            logger.warning(
                "%s: version %s UNRECOGNISED status %r (verbatim %r) attempt=%d/%d. "
                "Not in ready %s, pending %s or failed %s. Not treating it as success. "
                "Record the verbatim value in docs/compatibility.md B9b.",
                agent_name,
                version_id,
                status,
                raw,
                attempt,
                attempts,
                sorted(_READY_STATUSES),
                sorted(_PENDING_STATUSES),
                sorted(_FAILED_STATUSES),
            )

        if monotonic() >= deadline:
            break

        sleep(poll_seconds)

    if unrecognised is not None:
        raise UnrecognisedStatusError(
            f"{agent_name}: version {version_id} reported status {unrecognised!r} "
            f"(verbatim {raw!r}), which is in none of the known sets "
            f"({sorted(_KNOWN_STATUSES)}), and was still reporting it after "
            f"{attempts} polls / {timeout_seconds}s. Refusing to guess: widening the "
            "ready set to make a run pass would invalidate every result from it. Record "
            "this exact string in docs/compatibility.md B9b with today's date, then "
            "decide which set it belongs in."
        )
    raise DeploymentError(
        f"{agent_name}: timed out waiting for version {version_id} to become ready. "
        f"Last status {status!r} after {attempts} polls / {timeout_seconds}s. "
        "Treating a timeout as a failure, not a pass."
    )


# The old name, kept because the semantics are unchanged for callers: wait for the
# version to be usable, or raise.
wait_until_active = wait_until_ready


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
    existing = None
    for candidate in _matching_versions(
        _list_versions(client, spec.agent_name), cfg.agent_image, spec.rai_policy_id
    ):
        existing = _confirmed_reusable(client, spec.agent_name, candidate)
        if existing is not None:
            break
    if existing is not None:
        version_id = str(existing.version)
        reused = True
        # %-args, not `extra=`. `extra` populates LogRecord attributes that the default
        # formatter never renders, so these lines previously printed no agent or version.
        logger.info(
            "%s: reusing existing version %s (status=%r)",
            spec.agent_name,
            version_id,
            _status_of(existing),
        )
    else:
        definition = build_definition(models, cfg, settings, spec)
        created = _create_version(client, spec, definition, settings.demo_run_id)
        version_id = str(created.version)
        reused = False
        logger.info(
            "%s: created version %s (status=%r)",
            spec.agent_name,
            version_id,
            _status_of(created),
        )

    ready = wait_until_ready(
        client,
        spec.agent_name,
        version_id,
        timeout_seconds=cfg.deploy_timeout_seconds,
        poll_seconds=cfg.deploy_poll_seconds,
        sleep=sleep,
        monotonic=monotonic,
    )
    return verify_version(ready, cfg, spec, reused=reused)


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
        retry_total=cfg.deploy_retry_total,
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


def configure_logging() -> None:
    """Make our own lines visible and stop the SDK from burying them.

    azure-core's ``http_logging_policy`` logs request and response headers for every
    call. During the 2026-10-08 incident that filled the init container's log while the
    one line that mattered — the observed status — was never emitted at all, so the
    container looked busy and healthy while telling us nothing. Our lines are INFO; the
    SDK's per-request chatter is turned down to WARNING.

    ``force=True`` because a library import may already have installed a root handler.
    Output is unbuffered line-by-line so ``kubectl logs -f`` shows progress live, which
    is what ``flush=True`` buys the reference implementation.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
        force=True,
    )
    for noisy in (
        "azure.core.pipeline.policies.http_logging_policy",
        "azure.identity",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(line_buffering=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint for the in-VNet deploy Job / init container."""
    configure_logging()
    cfg = DeploySettings()  # type: ignore[call-arg]
    settings = Settings()  # type: ignore[call-arg]

    logger.info(
        "deploying image %s to %s (timeout=%.0fs poll=%.0fs -> %d polls max)",
        cfg.agent_image,
        cfg.endpoint,
        cfg.deploy_timeout_seconds,
        cfg.deploy_poll_seconds,
        poll_attempts(cfg.deploy_timeout_seconds, cfg.deploy_poll_seconds),
    )

    client, models = build_client(cfg)
    try:
        report = deploy_all(client, models, cfg, settings)
    except DigestRejectedError as exc:
        logger.error("BLOCKED: %s", exc)
        return 3
    except UnrecognisedStatusError as exc:
        logger.error("BLOCKED, unrecognised status: %s", exc)
        return 4
    except DeploymentError as exc:
        logger.error("FAILED: %s", exc)
        return 1
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    print(report.to_json(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
