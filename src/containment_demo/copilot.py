"""Publish the owned ACS-denial agent through Foundry's native Microsoft 365 API."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator

from containment_demo.deploy import (
    DeploymentError,
    DriftError,
    _list_versions,
    build_client,
    configure_logging,
)
from containment_demo.governance.hosted import (
    SCENARIOS,
    STATE_DIRECTORY,
    HostedSettings,
    _owned,
    policy_facts,
    read_scenario,
    spec_for,
)
from containment_demo.settings import Settings

ENDPOINT_FIELDS = ("protocol_configuration", "authorization_schemes", "version_selector")
JOURNAL = Path.home() / ".copilot" / "publication.json"


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentDisplayName: str = Field(min_length=1, max_length=30)
    performBotRegistration: Literal[True] = True
    publishScope: Literal["Shared"]
    publishAsAutopilot: Literal[False] = False
    appVersion: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    shortDescription: str = Field(min_length=1, max_length=80)
    fullDescription: str = Field(min_length=1, max_length=4000)
    developerName: str = Field(min_length=1, max_length=32)
    developerWebsiteUrl: HttpUrl
    privacyUrl: HttpUrl
    termsOfUseUrl: HttpUrl

    @field_validator("developerWebsiteUrl", "privacyUrl", "termsOfUseUrl")
    @classmethod
    def https_metadata(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https" or value.username or value.password:
            raise ValueError("Public metadata URLs must use HTTPS without credentials")
        return value

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = self.model_dump(mode="json")
        if "replace-" in json.dumps(result).casefold():
            raise ValueError("Replace every example metadata placeholder before planning")
        return result


def endpoint_settings(agent: dict[str, Any]) -> dict[str, Any]:
    endpoint = agent.get("agent_endpoint")
    if not isinstance(endpoint, dict) or any(key not in endpoint for key in ENDPOINT_FIELDS):
        raise DriftError("Incomplete endpoint readback; refusing to replace unknown configuration")
    return {key: copy.deepcopy(endpoint[key]) for key in ENDPOINT_FIELDS}


def publication_endpoint(before: dict[str, Any], version: str) -> dict[str, Any]:
    after = copy.deepcopy(before)
    protocols = after["protocol_configuration"]
    schemes = after["authorization_schemes"]
    if not isinstance(protocols, dict) or "responses" not in protocols:
        raise DriftError("The existing hosted Responses endpoint is required")
    if (
        not isinstance(schemes, list)
        or not all(isinstance(item, dict) and isinstance(item.get("type"), str) for item in schemes)
        or not any(item["type"] in {"AzureRbac", "Entra"} for item in schemes)
    ):
        raise DriftError("Existing direct-client authorization must be preserved")
    if any(item["type"] == "BotServiceTenant" for item in schemes):
        raise DriftError("Refusing to replace an existing tenant-wide publication")
    activity = protocols.setdefault("activity", {})
    if not isinstance(activity, dict):
        raise DriftError("Unrecognized Activity protocol configuration")
    activity["enable_m365_public_endpoint"] = True
    if not any(item["type"] == "BotServiceRbac" for item in schemes):
        schemes.append({"type": "BotServiceRbac"})
    after["version_selector"] = {
        "version_selection_rules": [
            {"type": "FixedRatio", "agent_version": version, "traffic_percentage": 100}
        ]
    }
    return after


def save_journal(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="publication-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(record, indent=2) + "\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Publisher:
    def __init__(
        self, client: httpx.Client, token: SecretStr, endpoint: str, agent_name: str, journal: Path
    ) -> None:
        self.client = client
        self.token = token
        self.endpoint = endpoint
        self.agent_name = agent_name
        self.url = f"{endpoint}/agents/{agent_name}"
        self.journal = journal

    def request(self, method: str, suffix: str = "", body: Any = None) -> dict[str, Any]:
        response = self.client.request(
            method,
            self.url + suffix,
            params={"api-version": "v1"},
            headers={
                "Authorization": f"Bearer {self.token.get_secret_value()}",
                "Content-Type": (
                    "application/merge-patch+json" if method == "PATCH" else "application/json"
                ),
            },
            json=body,
        )
        if response.status_code == 403:
            message = (
                "Foundry returned HTTP 403. Verify the publishing user's Foundry project "
                "permissions and private connectivity. No automatic retry was performed."
            )
            try:
                payload = response.json()
            except json.JSONDecodeError:
                message += " The service error body was not JSON."
            else:
                error = payload.get("error", payload) if isinstance(payload, dict) else {}
                detail = error.get("message") if isinstance(error, dict) else None
                missing = (
                    re.search(
                        r"does not have permissions for "
                        r"(Microsoft\.CognitiveServices/[A-Za-z0-9_/*.-]+) actions",
                        detail,
                    )
                    if isinstance(detail, str)
                    else None
                )
                if missing:
                    message = (
                        f"Foundry returned HTTP 403: the publishing user lacks {missing[1]}. "
                        "Subscription Owner does not supply Foundry data-plane access. "
                        "Run task copilot:access to grant project-scoped Foundry User. "
                        "After propagation, retry copilot:plan; if a publish was already "
                        "attempted, inspect copilot:status before taking further action."
                    )
            raise httpx.HTTPStatusError(message, request=response.request, response=response)
        response.raise_for_status()
        if not response.content:
            return {}
        result: Any = response.json()
        if not isinstance(result, dict):
            raise DeploymentError(
                "Unrecognized Foundry response; inspect publication before retrying"
            )
        return result

    def load(self) -> dict[str, Any]:
        record: dict[str, Any] = json.loads(self.journal.read_text())
        if record["endpoint"] != self.endpoint or record["agent_name"] != self.agent_name:
            raise DriftError("Publication journal belongs to another project or agent")
        return record

    def plan(self, request: PublishRequest, facts: dict[str, Any]) -> dict[str, Any]:
        if self.journal.exists():
            record = self.load()
            if record["phase"] == "published":
                if request.payload() != record["request"]:
                    raise DriftError("An agent version update cannot change catalog metadata")
                if endpoint_settings(self.request("GET")) != record["after"]:
                    raise DriftError("Published endpoint changed; refusing to plan over it")
                if facts["version"] == record["facts"]["version"]:
                    raise DeploymentError("This agent version is already published; inspect status")
                record["upgrade_before"] = record["after"]
                record["after"] = publication_endpoint(record["after"], facts["version"])
                record["facts"] = facts
                record["phase"] = "upgrade_planned"
                save_journal(self.journal, record)
                return record
            if record["phase"] not in {"planned", "disabled"}:
                raise DeploymentError(
                    "Publication already started; inspect status, do not overwrite it"
                )
        before = endpoint_settings(self.request("GET"))
        if "activity" in before["protocol_configuration"] or any(
            item.get("type", "").startswith("BotService")
            for item in before["authorization_schemes"]
        ):
            raise DriftError("Agent already has a channel configuration not owned by this journal")
        record = {
            "endpoint": self.endpoint,
            "agent_name": self.agent_name,
            "facts": facts,
            "request": request.payload(),
            "before": before,
            "after": publication_endpoint(before, facts["version"]),
            "phase": "planned",
        }
        save_journal(self.journal, record)
        return record

    def publish(self, request: PublishRequest, facts: dict[str, Any]) -> dict[str, Any]:
        record = self.load()
        if record["phase"] == "published":
            published_version = record["facts"]["version"]
            if facts["version"] != published_version:
                raise DeploymentError(
                    f"Version {published_version} is already published; deployed version "
                    f"{facts['version']} has not been planned. Run task copilot:plan, "
                    "review the upgrade, then run task copilot:publish."
                )
            raise DeploymentError(
                f"Version {published_version} is already published. "
                "Run task copilot:status; no new publication is needed."
            )
        upgrading = record["phase"] == "upgrade_planned"
        if record["phase"] not in {"planned", "upgrade_planned"}:
            raise DeploymentError(
                "Publication has already been attempted. Inspect status; never blindly retry POST."
            )
        if facts != record["facts"] or request.payload() != record["request"]:
            raise DriftError("Agent or public metadata changed since the approved plan")
        before = record["upgrade_before"] if upgrading else record["before"]
        if endpoint_settings(self.request("GET")) != before:
            raise DriftError("Endpoint changed since planning; refusing to overwrite it")
        record["phase"] = "patch_requested"
        save_journal(self.journal, record)
        self.request("PATCH", body={"agent_endpoint": record["after"]})
        if endpoint_settings(self.request("GET")) != record["after"]:
            raise DriftError("Endpoint readback differs from the planned publication")
        if not upgrading:
            record["phase"] = "publish_requested"
            save_journal(self.journal, record)
            result = self.request("POST", "/microsoft365/publish", record["request"])
            if not isinstance(result.get("titleId"), str) or not result["titleId"]:
                raise DeploymentError(
                    "Publish returned no titleId; inspect before taking further action"
                )
            record["title_id"] = result["titleId"]
        record.pop("upgrade_before", None)
        record["phase"] = "published"
        save_journal(self.journal, record)
        if endpoint_settings(self.request("GET")) != record["after"]:
            raise DriftError("Publication changed the planned endpoint; inspect status")
        return record

    def ensure(self, request: PublishRequest, facts: dict[str, Any]) -> dict[str, Any]:
        if self.journal.exists():
            record = self.load()
            if record["phase"] == "published" and record["facts"] == facts:
                if (
                    request.payload() != record["request"]
                    or endpoint_settings(self.request("GET")) != record["after"]
                ):
                    raise DriftError("Published metadata or endpoint drifted; refusing changes")
                return record
            if record["phase"] == "upgrade_planned":
                return self.publish(request, facts)
        self.plan(request, facts)
        return self.publish(request, facts)

    def disable(self) -> dict[str, Any]:
        record = self.load()
        if record["phase"] in {"planned", "disabled"}:
            raise DeploymentError("No active publication change to restore")
        current = endpoint_settings(self.request("GET"))
        if current not in (record["after"], record["before"], record.get("upgrade_before")):
            raise DriftError(
                "Endpoint changed outside this publication; refusing to restore over it"
            )
        record["phase"] = "disable_requested"
        save_journal(self.journal, record)
        if current != record["before"]:
            self.request("PATCH", body={"agent_endpoint": record["before"]})
        if endpoint_settings(self.request("GET")) != record["before"]:
            raise DriftError("Original endpoint settings were not restored")
        record["phase"] = "disabled"
        save_journal(self.journal, record)
        return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["plan", "publish", "ensure", "status", "disable"])
    parser.add_argument("--metadata", required=True, help="Public app metadata JSON; never tokens")
    args = parser.parse_args(argv)
    configure_logging()
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            handler.setStream(sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    request = PublishRequest.model_validate_json(args.metadata)
    token = SecretStr(sys.stdin.read().strip())
    if not token.get_secret_value() or any(
        character.isspace() for character in token.get_secret_value()
    ):
        raise ValueError("A publishing user's Foundry token is required on standard input")
    cfg = HostedSettings()  # type: ignore[call-arg]
    scenario = next(item for item in SCENARIOS if item.name == "governance-denial")
    name = spec_for(cfg, scenario).agent_name
    with httpx.Client(timeout=60, follow_redirects=False) as http:
        publisher = Publisher(http, token, cfg.endpoint, name, JOURNAL)
        if args.action in {"plan", "publish", "ensure"}:
            deployment = json.loads((STATE_DIRECTORY / "deployment.json").read_text())
            candidates = [row for row in deployment["agents"] if row["scenario"] == scenario.name]
            if deployment["endpoint"] != cfg.endpoint or len(candidates) != 1:
                raise DriftError("Missing or ambiguous owned governance deployment")
            client, models = build_client(cfg)
            try:
                if any(not _owned(version, scenario) for version in _list_versions(client, name)):
                    raise DriftError("Agent contains a version outside this governance track")
                facts = read_scenario(
                    client,
                    models,
                    cfg,
                    Settings(),  # type: ignore[call-arg]
                    scenario,
                    candidates[0]["version"],
                )
            finally:
                client.close()
            facts["network"] = policy_facts(cfg, Settings())  # type: ignore[call-arg]
            operation = {
                "plan": publisher.plan,
                "publish": publisher.publish,
                "ensure": publisher.ensure,
            }[args.action]
            record = operation(request, facts)
        elif args.action == "disable":
            record = publisher.disable()
        else:
            record = publisher.load()
            record["endpoint_matches_plan"] = (
                endpoint_settings(publisher.request("GET")) == record["after"]
            )
        record["planned_endpoint_summary"] = {
            "protocols": sorted(record["after"]["protocol_configuration"]),
            "authorization_types": [
                scheme["type"] for scheme in record["after"]["authorization_schemes"]
            ],
            "activity_public": True,
            "pinned_version": record["facts"]["version"],
        }
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


if __name__ == "__main__":
    raise SystemExit(main())
