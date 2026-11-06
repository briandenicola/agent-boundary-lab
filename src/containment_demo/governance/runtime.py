"""Pre-tool-call governance for the published ACS 0.3.1b1 contract."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import logging
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from containment_demo.settings import GovernanceMode, Settings
from containment_demo.telemetry import emit_governance_evidence

logger = logging.getLogger(__name__)
OPA_VERSION = "1.9.0"
_REASON = re.compile(r"[A-Za-z0-9_.:-]{1,96}")


@runtime_checkable
class Control(Protocol):
    async def evaluate_intervention_point(
        self, intervention_point: str, snapshot: dict[str, object], mode: str
    ) -> object: ...


class PolicyResult(BaseModel):
    model_config = ConfigDict(strict=True)

    verdict: Literal["allow", "deny", "warn", "escalate", "transform"]
    reason: str | None
    has_transform: bool
    transform_applied: bool
    transformed_args: object = None


@dataclass(frozen=True)
class Evaluation:
    verdict: str
    reason_code: str
    error: bool = False


def _load_control(settings: Settings) -> tuple[Control, str, str]:
    """Load only local, pre-tool-call Rego artifacts; SDK validates the manifest."""
    sdk = importlib.import_module("agent_control_specification")
    manifest_path = settings.governance_manifest
    if manifest_path is None:
        raise ValueError("governance manifest is missing")
    manifest_path = manifest_path.resolve(strict=True)
    content = manifest_path.read_bytes()
    sdk.validate_manifest(content)
    manifest = sdk.parse_manifest(content)
    if not isinstance(manifest, dict):
        raise ValueError("governance manifest must be an object")
    if manifest.get("extends") or manifest.get("annotators"):
        raise ValueError("governance supports local manifests without extends or annotators")
    points = manifest.get("intervention_points")
    policies = manifest.get("policies")
    metadata = manifest.get("metadata")
    if not isinstance(points, dict) or set(points) != {"pre_tool_call"}:
        raise ValueError("governance requires exactly the pre_tool_call intervention point")
    if not isinstance(policies, dict) or len(policies) != 1:
        raise ValueError("governance requires one local Rego policy")
    policy_id, policy = next(iter(policies.items()))
    if not isinstance(policy_id, str) or not _REASON.fullmatch(policy_id):
        raise ValueError("invalid governance policy identifier")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("name"), str):
        raise ValueError("governance requires manifest metadata.name")
    name = metadata["name"]
    if not _REASON.fullmatch(name):
        raise ValueError("invalid governance manifest name")
    if not isinstance(policy, dict) or policy.get("type") != "rego":
        raise ValueError("governance requires a Rego policy")
    if set(policy) != {"type", "bundle", "query"} or not isinstance(policy["bundle"], str):
        raise ValueError("governance requires a local bundle and query")
    bundle = (manifest_path.parent / policy["bundle"]).resolve(strict=True)
    if not bundle.is_dir() or not bundle.is_relative_to(manifest_path.parent):
        raise ValueError("governance bundle must be a directory inside the manifest directory")
    digest = hashlib.sha256(content)
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError("governance bundle symlinks are unsupported")
        if path.is_file():
            digest.update(str(path.relative_to(bundle)).encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())

    opa_path = settings.governance_opa_path.resolve(strict=True)
    version = subprocess.run(  # noqa: S603
        [str(opa_path), "version"], capture_output=True, text=True, check=True, timeout=5
    )
    if f"Version: {OPA_VERSION}\n" not in version.stdout:
        raise ValueError(f"governance requires OPA {OPA_VERSION}")
    # The release captures these settings while constructing its native dispatcher.
    os.environ["ACS_OPA_PATH"] = str(opa_path)
    os.environ["ACS_OPA_TIMEOUT_MS"] = str(max(1, int(settings.governance_timeout_seconds * 1000)))
    control: object = sdk.AgentControl.from_path(str(manifest_path))
    if not isinstance(control, Control):
        raise TypeError("ACS runtime does not implement the verified evaluation contract")
    return control, f"{name}/{policy_id}", f"sha256:{digest.hexdigest()}"


def _normalize(raw: object, arguments_valid: bool) -> Evaluation:
    verdict = getattr(raw, "verdict", None)
    result = PolicyResult.model_validate(
        {
            "verdict": getattr(getattr(verdict, "decision", None), "value", None),
            "reason": getattr(verdict, "reason", None),
            "has_transform": getattr(verdict, "transform", None) is not None,
            "transform_applied": getattr(raw, "transformed_policy_target_applied", None),
            "transformed_args": getattr(raw, "transformed_policy_target", None),
        }
    )
    reason = result.reason or "policy_decision"
    if reason.startswith(("runtime_error:", "host_error:")):
        return Evaluation("error", "evaluation_failed", error=True)
    if not _REASON.fullmatch(reason):
        reason = "policy_decision"
    if not arguments_valid:
        return Evaluation("error", "invalid_tool_arguments", error=True)
    if result.verdict == "escalate":
        return Evaluation("deny", "approval_required")
    if result.verdict == "transform":
        if not result.has_transform or not result.transform_applied or result.transformed_args != {}:
            return Evaluation("error", "unsupported_transform", error=True)
        return Evaluation("transform", reason)
    if result.has_transform or result.transform_applied or result.transformed_args is not None:
        return Evaluation("error", "invalid_verdict", error=True)
    return Evaluation("allow" if result.verdict == "warn" else result.verdict, reason)


class Governance:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.control: Control | None = None
        self.policy_id = "unavailable"
        self.policy_version = "unavailable"
        self.initialization_failed = False

    async def before_tool(
        self,
        name: str,
        args: dict[str, Any],
        *,
        session_id: str,
        invocation_id: str,
        tool_call_id: str | None = None,
    ) -> dict[str, Any] | None:
        settings = self.settings
        if settings.governance_mode is GovernanceMode.DISABLED:
            return None
        started = time.monotonic()
        call_id = tool_call_id or f"tool-{uuid.uuid4()}"
        snapshot: dict[str, object] = {
            "agent": {"name": settings.agent_name, "version": settings.agent_version},
            "session": {"id": session_id},
            "demo_run_id": settings.demo_run_id,
            "invocation_id": invocation_id,
            # Both tools have zero business arguments. Never copy injected context/tokens.
            "tool_call": {"id": call_id, "name": name, "args": {}, "arguments_valid": not args},
        }
        try:
            if self.initialization_failed:
                evaluation = Evaluation("error", "initialization_failed", error=True)
            else:
                if self.control is None:
                    self.control, self.policy_id, self.policy_version = _load_control(settings)
                raw = await asyncio.wait_for(
                    self.control.evaluate_intervention_point("pre_tool_call", snapshot, "enforce"),
                    timeout=settings.governance_timeout_seconds,
                )
                evaluation = _normalize(raw, not args)
        except TimeoutError:
            evaluation = Evaluation("error", "evaluation_timeout", error=True)
        except (ValidationError, TypeError, AttributeError):
            evaluation = Evaluation("error", "invalid_verdict", error=True)
        except Exception as exc:
            # Native/OPA failures must not expose exception messages or snapshots.
            self.initialization_failed = self.control is None
            logger.error("governance evaluation failed (%s)", type(exc).__name__)
            evaluation = Evaluation("error", "evaluation_failed", error=True)

        blocked = settings.governance_mode is GovernanceMode.ENFORCED and (
            evaluation.verdict == "deny" or evaluation.error
        )
        action = "blocked" if blocked else "continue"
        if settings.governance_mode is GovernanceMode.AUDIT:
            action = "audit_continue"
        evidence = {
            "tool_name": name,
            "session_id": session_id,
            "invocation_id": invocation_id,
            "tool_call_id": call_id,
            "governance_mode": settings.governance_mode.value,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "acs_verdict": evaluation.verdict,
            "enforcement_action": action,
            "reason_code": evaluation.reason_code,
            "evaluation_duration_ms": round((time.monotonic() - started) * 1000, 2),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        emit_governance_evidence(settings, evidence)
        if not blocked:
            return None
        return {
            "tool_name": name,
            "demo_run_id": settings.demo_run_id,
            "policy_mode": settings.policy_mode.value,
            "succeeded": False,
            "http_status": None,
            "error_category": "governance_error" if evaluation.error else "governance_denied",
            "error_detail": evaluation.reason_code,
            "governance": evidence,
        }
