"""Isolated Foundry scenario versions; never update the tested baseline agents."""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr, field_validator

from containment_demo.deploy import (
    AgentSpec,
    DeploymentError,
    DeploySettings,
    DriftError,
    _list_versions,
    _status_of,
    build_client,
    build_definition,
    configure_logging,
    verify_version,
    wait_until_ready,
)
from containment_demo.governance.runtime import policy_fingerprint
from containment_demo.settings import GovernanceMode, PolicyMode, Settings

logger = logging.getLogger(__name__)
TRACK = "governance-g4"
STATE_DIRECTORY = Path.home() / ".governance"


class HostedSettings(DeploySettings):
    governance_all_policy_id: str
    governance_network_policy_id: str
    governance_audit_policy_id: str
    governance_policies_directory: Path = Path("/app/policies/acs")
    application_insights_connection_string: SecretStr

    @field_validator(
        "governance_all_policy_id", "governance_network_policy_id", "governance_audit_policy_id"
    )
    @classmethod
    def policy_id(cls, value: str) -> str:
        return DeploySettings._must_be_arm_id(value)


@dataclass(frozen=True)
class Scenario:
    name: str
    governance_mode: GovernanceMode
    manifest: str | None
    network: str
    broken_evaluator: bool = False


SCENARIOS = (
    Scenario("audit-control", GovernanceMode.AUDIT, "governance-deny.yaml", "all"),
    Scenario("governance-denial", GovernanceMode.ENFORCED, "governance-deny.yaml", "all"),
    Scenario("network-denial", GovernanceMode.ENFORCED, "network-allow.yaml", "network"),
    Scenario("success", GovernanceMode.ENFORCED, "network-allow.yaml", "all"),
    Scenario("evaluation-failure", GovernanceMode.ENFORCED, "network-allow.yaml", "all", True),
    Scenario("baseline-audit", GovernanceMode.DISABLED, None, "audit"),
    Scenario("baseline-enforced", GovernanceMode.DISABLED, None, "network"),
)


def spec_for(cfg: HostedSettings, scenario: Scenario) -> AgentSpec:
    name = f"{cfg.agent_name_audit}-gov-{scenario.name}"
    DeploySettings._must_be_a_valid_agent_name(name)
    policies = {
        "all": cfg.governance_all_policy_id,
        "network": cfg.governance_network_policy_id,
        "audit": cfg.governance_audit_policy_id,
    }
    if len(set(policies.values())) != 3:
        raise DriftError("Governance comparisons require three distinct dedicated RAI policies")
    if set(policies.values()) & {cfg.rai_policy_audit_id, cfg.rai_policy_enforced_id}:
        raise DriftError("Governance policies must not be the baseline policies")
    return AgentSpec(
        name,
        policies[scenario.network],
        PolicyMode.AUDIT if scenario.network == "audit" else PolicyMode.ENFORCED,
    )


def definition_for(models: Any, cfg: HostedSettings, settings: Settings, scenario: Scenario) -> Any:
    definition = build_definition(models, cfg, settings, spec_for(cfg, scenario))
    env = definition.environment_variables
    env["DEMO_GOVERNANCE_MODE"] = scenario.governance_mode.value
    env["DEMO_GOVERNANCE_OPA_PATH"] = (
        "/app/policies/acs/intentionally-missing-opa"
        if scenario.broken_evaluator
        else "/usr/local/bin/opa"
    )
    env["DEMO_GOVERNANCE_TIMEOUT_SECONDS"] = str(settings.governance_timeout_seconds)
    if scenario.manifest:
        env["DEMO_GOVERNANCE_MANIFEST"] = str(cfg.governance_policies_directory / scenario.manifest)
    return definition


def _same_configuration(actual: Any, expected: Any) -> bool:
    if actual is None:
        return False
    return (
        all(
            getattr(actual, key, None) == getattr(expected, key, None)
            for key in ("cpu", "memory", "environment_variables")
        )
        and getattr(actual.container_configuration, "image", None)
        == expected.container_configuration.image
        and getattr(actual.container_configuration, "registry_connection_id", None)
        == expected.container_configuration.registry_connection_id
        and getattr(actual.rai_config, "rai_policy_name", None)
        == expected.rai_config.rai_policy_name
        and [(p.protocol, p.version) for p in (actual.protocol_versions or [])]
        == [(p.protocol, p.version) for p in expected.protocol_versions]
    )


def _owned(version: Any, scenario: Scenario) -> bool:
    metadata = getattr(version, "metadata", None) or {}
    return metadata.get("demo_track") == TRACK and metadata.get("scenario") == scenario.name


def policy_facts(cfg: HostedSettings, settings: Settings) -> dict[str, Any]:
    """Read actual policies/network; never equate requested settings with applied controls."""
    from azure.identity import DefaultAzureCredential

    account = cfg.rai_policy_enforced_id.rsplit("/raiPolicies/", 1)[0]
    with (
        DefaultAzureCredential() as credential,
        httpx.Client(timeout=30, follow_redirects=False) as client,
    ):
        token = credential.get_token("https://management.azure.com/.default").token

        def get(resource: str, api_version: str) -> dict[str, Any]:
            response = client.get(
                f"https://management.azure.com{resource}",
                params={"api-version": api_version},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            return body

        baseline = get(cfg.rai_policy_enforced_id, "2026-05-15-preview")["properties"]
        telemetry_host = urlparse(
            next(
                part.split("=", 1)[1]
                for part in cfg.application_insights_connection_string.get_secret_value().split(";")
                if part.startswith("IngestionEndpoint=")
            )
        ).hostname
        if not telemetry_host:
            raise DriftError("Existing telemetry ingestion hostname is unavailable")
        facts = {}
        for key, policy_id in {
            "all": cfg.governance_all_policy_id,
            "network": cfg.governance_network_policy_id,
            "audit": cfg.governance_audit_policy_id,
        }.items():
            actual = get(policy_id, "2026-05-15-preview")["properties"]
            if any(
                actual.get(field) != baseline.get(field)
                for field in ("basePolicyName", "mode", "contentFilters")
            ):
                raise DriftError(f"{key}: content safety differs from the baseline")
            egress = actual["egressPolicy"]
            expected_hosts = {settings.policy_api_host, telemetry_host}
            if key == "all":
                expected_hosts.add(settings.test_receiver_host)
            rules = egress["rules"]
            hosts = {rule["match"]["host"] for rule in rules}
            if (
                hosts != expected_hosts
                or len(rules) != len(expected_hosts)
                or any(
                    rule["ruleType"] != "Fqdn"
                    or set(rule["match"]) != {"host"}
                    or rule["action"] != {"actionType": "Allow"}
                    for rule in rules
                )
                or egress["defaultAction"] != "Deny"
                or egress["mode"] != ("Audit" if key == "audit" else "Enforced")
            ):
                raise DriftError(f"{key}: actual egress configuration differs from the scenario")
            facts[key] = {"id": policy_id, "mode": egress["mode"], "hosts": sorted(hosts)}
        network = get(f"{account}/managednetworks/default", "2025-10-01-preview")
        mode = network["properties"]["managedNetwork"]["isolationMode"]
        if mode == "AllowOnlyApprovedOutbound":
            outbound = get(f"{account}/managednetworks/default/outboundrules", "2025-10-01-preview")
            destinations = {
                item["properties"]["destination"]
                for item in outbound["value"]
                if item["properties"]["type"] == "FQDN"
            }
            if not {settings.policy_api_host, settings.test_receiver_host} <= destinations:
                raise DriftError("Managed network does not independently allow both API hosts")
        elif mode != "AllowInternetOutbound":
            raise DriftError(f"Unverified managed-network isolation mode: {mode}")
        return {"policies": facts, "managed_network_mode": mode}


def read_scenario(
    client: Any,
    models: Any,
    cfg: HostedSettings,
    settings: Settings,
    scenario: Scenario,
    version_id: str,
) -> dict[str, Any]:
    spec = spec_for(cfg, scenario)
    actual = client.agents.get_version(spec.agent_name, version_id)
    verify_version(actual, cfg, spec, reused=True)
    if not _owned(actual, scenario) or not _same_configuration(
        actual.definition, definition_for(models, cfg, settings, scenario)
    ):
        raise DriftError(f"{scenario.name}: read-back configuration or ownership mismatch")
    if _status_of(actual) not in {"active", "running"}:
        raise DeploymentError(f"{scenario.name}: version is not ready")
    env = actual.definition.environment_variables
    policy_id = policy_version = "unavailable"
    if scenario.manifest and not scenario.broken_evaluator:
        path = cfg.governance_policies_directory / scenario.manifest
        content = path.read_bytes()
        manifest = importlib.import_module("yaml").safe_load(content)
        policy_name, policy = next(iter(manifest["policies"].items()))
        policy_id = f"{manifest['metadata']['name']}/{policy_name}"
        policy_version = policy_fingerprint(content, path.parent / policy["bundle"])
    return {
        "scenario": scenario.name,
        "agent_name": spec.agent_name,
        "version": str(actual.version),
        "image": actual.definition.container_configuration.image,
        "rai_policy_id": actual.definition.rai_config.rai_policy_name,
        "governance_mode": env["DEMO_GOVERNANCE_MODE"],
        "manifest": env.get("DEMO_GOVERNANCE_MANIFEST"),
        "opa_path": env["DEMO_GOVERNANCE_OPA_PATH"],
        "status": _status_of(actual),
        "policy_id": policy_id,
        "policy_version": policy_version,
    }


def deploy_scenarios(
    client: Any, models: Any, cfg: HostedSettings, settings: Settings
) -> dict[str, Any]:
    # Check all names before the first write, not after partially adopting mixed-purpose agents.
    existing = {}
    for scenario in SCENARIOS:
        spec = spec_for(cfg, scenario)
        existing[scenario.name] = _list_versions(client, spec.agent_name)
        if any(not _owned(v, scenario) for v in existing[scenario.name]):
            raise DriftError(f"{spec.agent_name}: existing version is not owned by this track")
    results = []
    for scenario in SCENARIOS:
        spec = spec_for(cfg, scenario)
        expected = definition_for(models, cfg, settings, scenario)
        version_id = None
        for candidate in existing[scenario.name]:
            direct = client.agents.get_version(spec.agent_name, str(candidate.version))
            if (
                _owned(direct, scenario)
                and _status_of(direct) in {"active", "running", "creating", "starting", "updating"}
                and _same_configuration(direct.definition, expected)
            ):
                version_id = str(direct.version)
                break
        if version_id is None:
            created = client.agents.create_version(
                spec.agent_name,
                definition=expected,
                description="Isolated ACS/application versus Foundry/platform control comparison.",
                metadata={"demo_track": TRACK, "scenario": scenario.name},
            )
            version_id = str(created.version)
        wait_until_ready(
            client,
            spec.agent_name,
            version_id,
            timeout_seconds=cfg.deploy_timeout_seconds,
            poll_seconds=cfg.deploy_poll_seconds,
        )
        results.append(read_scenario(client, models, cfg, settings, scenario, version_id))
    return {"run_kind": "hosted_configuration", "endpoint": cfg.endpoint, "agents": results}


def deletion_plan(client: Any, cfg: HostedSettings) -> list[tuple[str, str]]:
    from azure.core.exceptions import ResourceNotFoundError

    versions = []
    for scenario in SCENARIOS:
        name = spec_for(cfg, scenario).agent_name
        for listed in _list_versions(client, name):
            try:
                actual = client.agents.get_version(name, str(listed.version))
            except ResourceNotFoundError:
                continue
            if not _owned(actual, scenario):
                raise DriftError(f"{name}: refusing teardown of a non-track version")
            versions.append((name, str(actual.version)))
    if len(versions) > 50:
        raise DeploymentError("More than 50 versions: review teardown scope before proceeding")
    return versions


def delete_scenarios(client: Any, cfg: HostedSettings) -> None:
    from azure.core.exceptions import ResourceNotFoundError

    versions = deletion_plan(client, cfg)
    for name, version in versions:
        client.agents.delete_version(name, version, force=False)
        logger.info("Requested deletion of %s:%s; no force or baseline deletion", name, version)
    deadline = time.monotonic() + cfg.deploy_timeout_seconds
    pending = set(versions)
    while pending:
        for name, version in tuple(pending):
            if time.monotonic() >= deadline:
                raise DeploymentError("Governance deletion did not finish within the time budget")
            try:
                actual = client.agents.get_version(name, version)
            except ResourceNotFoundError:
                pending.remove((name, version))
                continue
            if _status_of(actual) == "deleted":
                pending.remove((name, version))
        if pending:
            time.sleep(cfg.deploy_poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "status", "check-down", "down"])
    parser.add_argument("--report", default=str(STATE_DIRECTORY / "deployment.json"))
    args = parser.parse_args(argv)
    configure_logging()
    if args.action == "status":
        for handler in logging.getLogger().handlers:
            if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
                handler.setStream(sys.stderr)
        logging.getLogger("httpx").setLevel(logging.WARNING)
    STATE_DIRECTORY.mkdir(mode=0o700, exist_ok=True)
    cfg = HostedSettings()  # type: ignore[call-arg]
    settings = Settings()  # type: ignore[call-arg]
    client, models = build_client(cfg)
    try:
        if args.action == "up":
            network = policy_facts(cfg, settings)
            report = deploy_scenarios(client, models, cfg, settings)
            report["network"] = network
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        elif args.action == "status":
            report = json.loads(Path(args.report).read_text())
            report["network"] = policy_facts(cfg, settings)
            report["agents"] = [
                read_scenario(
                    client,
                    models,
                    cfg,
                    settings,
                    scenario,
                    next(r["version"] for r in report["agents"] if r["scenario"] == scenario.name),
                )
                for scenario in SCENARIOS
            ]
        elif args.action == "check-down":
            print(json.dumps({"owned_versions": deletion_plan(client, cfg)}))
            return 0
        else:
            delete_scenarios(client, cfg)
            return 0
        print(json.dumps(report, indent=2), flush=True)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
