"""Isolated project deployment/publication; never modify the HTTP comparison agents."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, HttpUrl, SecretStr, model_validator

from containment_demo.copilot import Publisher, PublishRequest, endpoint_settings, save_journal
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
from containment_demo.governance.hosted import HostedSettings, _same_configuration
from containment_demo.settings import PolicyMode, Settings, validate_toolbox

TRACK = "copilot-toolbox"
DIRECTORY = Path.home() / ".copilot-toolbox"


class Configuration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_name: str
    project_id: str
    agent_name: str
    mcp_url: HttpUrl
    mcp_app_name: str
    rai_policy_id: str
    agent_image: str
    toolbox_endpoint: HttpUrl
    toolbox_policy_tool: str

    @model_validator(mode="after")
    def valid(self) -> Configuration:
        DeploySettings._must_be_digest_pinned(self.agent_image)
        DeploySettings._must_be_arm_id(self.rai_policy_id)
        DeploySettings._must_be_a_valid_agent_name(self.agent_name)
        DeploySettings._must_be_a_valid_agent_name(self.project_name)
        validate_toolbox(self.toolbox_endpoint, self.toolbox_policy_tool)
        if "/versions/" not in (self.toolbox_endpoint.path or ""):
            raise ValueError("Pin an immutable toolbox version")
        if "/containment-demo-copilot-toolbox-agent@" not in self.agent_image:
            raise ValueError("Require the separate Copilot agent image repository")
        if (
            self.mcp_url.scheme != "https"
            or self.mcp_url.username
            or self.mcp_url.password
            or self.mcp_url.path != "/mcp"
            or self.mcp_url.query
            or self.mcp_url.fragment
        ):
            raise ValueError("Require the dedicated HTTPS MCP endpoint")
        return self

    def deployment_settings(self, baseline: HostedSettings) -> DeploySettings:
        account = baseline.rai_policy_enforced_id.rsplit("/raiPolicies/", 1)[0]
        if (
            self.project_name == baseline.foundry_project_name
            or self.project_id != f"{account}/projects/{self.project_name}"
            or self.agent_name in {baseline.agent_name_audit, baseline.agent_name_enforced}
            or not self.rai_policy_id.startswith(account + "/raiPolicies/")
            or self.rai_policy_id
            in {
                baseline.rai_policy_audit_id,
                baseline.rai_policy_enforced_id,
                baseline.governance_all_policy_id,
                baseline.governance_network_policy_id,
                baseline.governance_audit_policy_id,
            }
        ):
            raise DriftError("Require a separate project, agent and policy in the approved account")
        cfg = DeploySettings.model_validate(
            {
                **baseline.model_dump(),
                "foundry_project_name": self.project_name,
                "agent_image": self.agent_image,
            }
        )
        if not str(self.toolbox_endpoint).startswith(cfg.endpoint + "/toolboxes/"):
            raise DriftError("Toolbox is outside the isolated project")
        return cfg

    @property
    def spec(self) -> AgentSpec:
        return AgentSpec(self.agent_name, self.rai_policy_id, PolicyMode.ENFORCED)


def definition_for(
    models: Any, cfg: DeploySettings, settings: Settings, config: Configuration
) -> Any:
    definition = build_definition(models, cfg, settings, config.spec)
    definition.environment_variables.update(
        {
            "TOOLBOX_ENDPOINT": str(config.toolbox_endpoint),
            "DEMO_TOOLBOX_POLICY_TOOL": config.toolbox_policy_tool,
            "DEMO_GOVERNANCE_MODE": "enforced",
            "DEMO_GOVERNANCE_MANIFEST": "/app/policies/acs/governance-deny.yaml",
            "DEMO_GOVERNANCE_OPA_PATH": "/usr/local/bin/opa",
            "DEMO_GOVERNANCE_TIMEOUT_SECONDS": str(settings.governance_timeout_seconds),
        }
    )
    return definition


def owned(version: Any) -> bool:
    return (getattr(version, "metadata", None) or {}).get("demo_track") == TRACK


def read_version(
    client: Any,
    models: Any,
    cfg: DeploySettings,
    settings: Settings,
    config: Configuration,
    version: str,
) -> dict[str, Any]:
    actual = client.agents.get_version(config.agent_name, version)
    verify_version(actual, cfg, config.spec, reused=True)
    if (
        not owned(actual)
        or not _same_configuration(actual.definition, definition_for(models, cfg, settings, config))
        or _status_of(actual) not in {"active", "running"}
    ):
        raise DriftError("Isolated agent ownership, configuration or readiness differs")
    return {
        "project": config.project_name,
        "agent_name": config.agent_name,
        "version": str(actual.version),
        "image": cfg.agent_image,
        "rai_policy_id": config.rai_policy_id,
        "toolbox_endpoint": str(config.toolbox_endpoint),
        "toolbox_policy_tool": config.toolbox_policy_tool,
        "mcp_url": str(config.mcp_url),
        "status": _status_of(actual),
        "runtime_result": "unverified",
    }


def network_facts(
    baseline: HostedSettings,
    settings: Settings,
    config: Configuration,
) -> dict[str, Any]:
    from azure.identity import DefaultAzureCredential

    telemetry = next(
        part.split("=", 1)[1]
        for part in baseline.application_insights_connection_string.get_secret_value().split(";")
        if part.startswith("IngestionEndpoint=")
    )
    hosts = {
        config.toolbox_endpoint.host,
        settings.test_receiver_host,
        urlparse(telemetry).hostname,
    }
    with (
        DefaultAzureCredential() as credential,
        httpx.Client(timeout=30, follow_redirects=False) as client,
    ):
        token = credential.get_token("https://management.azure.com/.default").token

        def get(resource: str, api: str) -> dict[str, Any]:
            response = client.get(
                f"https://management.azure.com{resource}",
                params={"api-version": api},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            body: dict[str, Any] = response.json()
            return body

        original = get(baseline.rai_policy_enforced_id, "2026-05-15-preview")["properties"]
        actual = get(config.rai_policy_id, "2026-05-15-preview")["properties"]
        capability_hosts = get(config.project_id + "/capabilityHosts", "2025-06-01")
        connection_path = "/connections/appinsights-connection"
        baseline_insights = get(
            f"{baseline.rai_policy_enforced_id.rsplit('/raiPolicies/', 1)[0]}"
            f"/projects/{baseline.foundry_project_name}{connection_path}",
            "2026-05-15-preview",
        )["properties"]
        insights = get(config.project_id + connection_path, "2026-05-15-preview")["properties"]
    ready = capability_hosts["value"]
    if (
        capability_hosts.get("nextLink")
        or len(ready) != 1
        or ready[0]["properties"]["provisioningState"] != "Succeeded"
        or ready[0]["properties"]["capabilityHostKind"] != "Agents"
    ):
        raise DeploymentError("BLOCKED: isolated project capability host is not ready")
    if (
        insights.get("category") != "AppInsights"
        or insights.get("authType") != "ApiKey"
        or any(insights.get(key) != baseline_insights.get(key) for key in ("target", "metadata"))
        or not insights.get("target")
        or insights.get("isSharedToAll") is not False
    ):
        raise DriftError("Isolated project must reuse the baseline telemetry destination")
    if any(
        actual.get(key) != original.get(key) for key in ("basePolicyName", "mode", "contentFilters")
    ):
        raise DriftError("Copilot policy content safety differs from the baseline")
    egress = actual["egressPolicy"]
    rules = egress["rules"]
    if (
        egress["mode"] != "Enforced"
        or egress["defaultAction"] != "Deny"
        or len(rules) != len(hosts)
        or {rule["match"]["host"] for rule in rules} != hosts
        or any(
            rule["ruleType"] != "Fqdn"
            or set(rule["match"]) != {"host"}
            or rule["action"] != {"actionType": "Allow"}
            for rule in rules
        )
    ):
        raise DriftError("Copilot egress policy differs from the isolated toolbox contract")
    return {"hosts": sorted(hosts), "project_capability_host": "Succeeded"}


def load_deployment(journal: Path, cfg: DeploySettings, config: Configuration) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(journal.read_text())
    if (
        record["endpoint"] != cfg.endpoint
        or record["configuration"] != config.model_dump(mode="json")
        or record["phase"] != "ready"
    ):
        raise DriftError(
            "Missing ready deployment or configuration drift; inspect the saved journal"
        )
    return record


def publication_facts(cfg: DeploySettings, config: Configuration) -> dict[str, Any]:
    from azure.identity import DefaultAzureCredential

    journal = DIRECTORY / "publication.json"
    if not journal.exists():
        return {"phase": "not_journaled"}
    with (
        DefaultAzureCredential() as credential,
        httpx.Client(timeout=30, follow_redirects=False) as http,
    ):
        token = SecretStr(credential.get_token("https://ai.azure.com/.default").token)
        publisher = Publisher(http, token, cfg.endpoint, config.agent_name, journal)
        record = publisher.load()
        if record["phase"] not in {"planned", "upgrade_planned", "published", "disabled"}:
            raise DeploymentError("Uncertain publication journal; inspect before retrying")
        expected = (
            record["after"]
            if record["phase"] == "published"
            else record["upgrade_before"]
            if record["phase"] == "upgrade_planned"
            else record["before"]
        )
        if endpoint_settings(publisher.request("GET")) != expected:
            raise DriftError("Isolated publication endpoint differs from its journal")
    return {
        "phase": record["phase"],
        "published_version": record["facts"]["version"] if record["phase"] == "published" else None,
        "title_id": record.get("title_id"),
        "conversation_result": "unverified",
    }


def deploy(
    client: Any,
    models: Any,
    cfg: DeploySettings,
    settings: Settings,
    config: Configuration,
    journal: Path,
) -> dict[str, Any]:
    versions = _list_versions(client, config.agent_name)
    if any(not owned(version) for version in versions):
        raise DriftError("Agent contains a version outside this isolated track")
    previous = None
    if journal.exists():
        previous = json.loads(journal.read_text())
        if previous["endpoint"] != cfg.endpoint or previous["phase"] not in {"ready", "waiting"}:
            raise DeploymentError(
                "Uncertain or foreign deployment journal; inspect before retrying"
            )
    expected = definition_for(models, cfg, settings, config)
    matches = []
    for candidate in versions:
        actual = client.agents.get_version(config.agent_name, str(candidate.version))
        if (
            owned(actual)
            and _same_configuration(actual.definition, expected)
            and _status_of(actual) in {"active", "running", "creating", "starting", "updating"}
        ):
            matches.append(str(actual.version))
    if len(matches) > 1:
        raise DriftError("Multiple matching versions; inspect instead of choosing arbitrarily")
    if (
        previous is not None
        and previous["phase"] == "waiting"
        and (
            previous["configuration"] != config.model_dump(mode="json")
            or matches != [previous["version"]]
        )
    ):
        raise DriftError("Pending deployment changed; do not create a replacement automatically")
    record = {
        "endpoint": cfg.endpoint,
        "configuration": config.model_dump(mode="json"),
        "phase": "create_requested",
    }
    if matches:
        version = matches[0]
    else:
        save_journal(journal, record)
        created = client.agents.create_version(
            config.agent_name,
            definition=expected,
            description="Isolated Copilot OAuth toolbox demo; not the HTTP containment baseline.",
            metadata={"demo_track": TRACK},
        )
        version = str(created.version)
    record.update(phase="waiting", version=version)
    save_journal(journal, record)
    wait_until_ready(
        client,
        config.agent_name,
        version,
        timeout_seconds=cfg.deploy_timeout_seconds,
        poll_seconds=cfg.deploy_poll_seconds,
    )
    record["facts"] = read_version(client, models, cfg, settings, config, version)
    record["phase"] = "ready"
    save_journal(journal, record)
    return record


def delete_versions(
    client: Any, cfg: DeploySettings, config: Configuration, *, apply: bool
) -> None:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential

    publication = DIRECTORY / "publication.json"
    if publication.exists():
        record = json.loads(publication.read_text())
        if (
            record["endpoint"] != cfg.endpoint
            or record["agent_name"] != config.agent_name
            or record["phase"] not in {"planned", "disabled"}
        ):
            raise DeploymentError("Disable the isolated publication before teardown")
    versions = _list_versions(client, config.agent_name)
    if len(versions) > 20 or any(not owned(version) for version in versions):
        raise DriftError("Teardown exceeds the isolated owned versions")
    if versions:
        # Refuse to delete a still-published or externally modified endpoint.
        with (
            DefaultAzureCredential() as credential,
            httpx.Client(timeout=30, follow_redirects=False) as http,
        ):
            token = SecretStr(credential.get_token("https://ai.azure.com/.default").token)
            publisher = Publisher(
                http, token, cfg.endpoint, config.agent_name, DIRECTORY / "publication.json"
            )
            endpoint = publisher.request("GET").get("agent_endpoint", {})
            if (
                "activity" in endpoint.get("protocol_configuration", {})
                or any(
                    item.get("type", "").startswith("BotService")
                    for item in endpoint.get("authorization_schemes", [])
                )
                or not endpoint.get("protocol_configuration")
            ):
                raise DeploymentError("Disable the isolated publication before teardown")
    if not apply:
        return
    for version in versions:
        actual = client.agents.get_version(config.agent_name, str(version.version))
        if not owned(actual):
            raise DriftError("Version ownership changed since teardown preflight")
        client.agents.delete_version(config.agent_name, str(version.version), force=False)
    deadline = time.monotonic() + cfg.deploy_timeout_seconds
    pending = {str(version.version) for version in versions}
    while pending:
        for version in tuple(pending):
            if time.monotonic() >= deadline:
                raise DeploymentError("Isolated version deletion timed out")
            try:
                actual = client.agents.get_version(config.agent_name, version)
            except ResourceNotFoundError:
                pending.remove(version)
                continue
            if _status_of(actual) == "deleted":
                pending.remove(version)
        if pending:
            time.sleep(cfg.deploy_poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["up", "status", "plan", "publish", "disable", "check-down", "down"]
    )
    parser.add_argument("--config", required=True, help="Non-secret isolated deployment JSON")
    parser.add_argument("--metadata", help="Public app metadata JSON; never tokens")
    args = parser.parse_args(argv)
    configure_logging()
    config = Configuration.model_validate_json(args.config)
    baseline = HostedSettings()  # type: ignore[call-arg]
    cfg = config.deployment_settings(baseline)
    settings = Settings()  # type: ignore[call-arg]
    journal = DIRECTORY / "deployment.json"
    if args.action == "disable":
        token = SecretStr(sys.stdin.read().strip())
        if not token.get_secret_value() or any(c.isspace() for c in token.get_secret_value()):
            raise ValueError("Publishing requires a user Foundry token on standard input")
        with httpx.Client(timeout=60, follow_redirects=False) as http:
            publisher = Publisher(
                http, token, cfg.endpoint, config.agent_name, DIRECTORY / "publication.json"
            )
            record = publisher.disable()
        print(
            json.dumps(
                {
                    key: value
                    for key, value in record.items()
                    if key not in {"before", "after", "upgrade_before"}
                },
                indent=2,
            )
        )
        return 0
    client, models = build_client(cfg)
    try:
        if args.action in {"check-down", "down"}:
            delete_versions(client, cfg, config, apply=args.action == "down")
            return 0
        network = network_facts(baseline, settings, config)
        if args.action == "up":
            record = deploy(client, models, cfg, settings, config, journal)
        else:
            deployment = load_deployment(journal, cfg, config)
            facts = read_version(client, models, cfg, settings, config, deployment["version"])
            facts["network"] = network
            if args.action == "status":
                record = {"facts": facts, "publication": publication_facts(cfg, config)}
            else:
                token = SecretStr(sys.stdin.read().strip())
                if not token.get_secret_value() or any(
                    c.isspace() for c in token.get_secret_value()
                ):
                    raise ValueError("Publishing requires a user Foundry token on standard input")
                with httpx.Client(timeout=60, follow_redirects=False) as http:
                    publisher = Publisher(
                        http, token, cfg.endpoint, config.agent_name, DIRECTORY / "publication.json"
                    )
                    if args.metadata is None:
                        raise ValueError("Public app metadata is required")
                    request = PublishRequest.model_validate_json(args.metadata)
                    record = (
                        publisher.plan(request, facts)
                        if args.action == "plan"
                        else publisher.publish(request, facts)
                    )
                record = {
                    key: value
                    for key, value in record.items()
                    if key not in {"before", "after", "upgrade_before"}
                }
        print(json.dumps({**record, "network": network}, indent=2))
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
