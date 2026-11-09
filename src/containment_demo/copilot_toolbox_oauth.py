"""Owner-run registration of the isolated toolbox's confidential OAuth client."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from containment_demo.copilot import save_journal

DIRECTORY = Path(".task/copilot-toolbox")
JOURNAL = DIRECTORY / "oauth-application.json"


def command(*args: str) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed executable and argv; no shell
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
            env={**os.environ, "AZURE_AUTO_UPGRADE_ENABLE": "false"},
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"{args[0]} failed: {exc.stderr.strip()}") from exc
    return result.stdout.strip()


def az(*args: str) -> Any:
    return json.loads(command("az", *args, "--only-show-errors", "--output", "json"))


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
    ):
        raise ValueError("Expected a complete Entra identifier")
    return value.lower()


@dataclass(frozen=True)
class Configuration:
    account_id: str
    tenant_id: str
    display_name: str
    audience: str
    scope: str
    api_client_id: str
    scope_id: str
    baseline_clients: str

    @property
    def permissions(self) -> list[dict[str, Any]]:
        return [
            {
                "resourceAppId": self.api_client_id,
                "resourceAccess": [{"id": self.scope_id, "type": "Scope"}],
            }
        ]

    @property
    def context(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "audience": self.audience,
            "scope": self.scope,
            "permissions": self.permissions,
        }


def discover() -> Configuration:
    tenant = identifier(os.environ.get("ARM_TENANT_ID"))
    subscription = identifier(os.environ.get("ARM_SUBSCRIPTION_ID"))
    login = az("account", "show")
    if (
        identifier(login["tenantId"]) != tenant
        or identifier(login["id"]) != subscription
        or login["state"] != "Enabled"
    ):
        raise ValueError("Azure CLI must match the configured enabled tenant/subscription")

    def output(name: str) -> str:
        return command("terraform", "-chdir=infra/cloud", "output", "-raw", name)

    account = output("foundry_account_id")
    parts = account.split("/")
    if (
        len(parts) != 9
        or parts[1] != "subscriptions"
        or identifier(parts[2]) != subscription
        or parts[3] != "resourceGroups"
        or parts[5:8] != ["providers", "Microsoft.CognitiveServices", "accounts"]
    ):
        raise ValueError("Baseline Foundry account must belong to the configured subscription")
    name = output("resource_name")
    if not re.fullmatch(r"[a-zA-Z0-9-]{1,200}", name):
        raise ValueError("Invalid baseline resource name")
    rows = az(
        "containerapp",
        "show",
        "--resource-group",
        parts[4],
        "--name",
        output("policy_api_app_name"),
        "--query",
        "properties.template.containers[0].env[?name=='POLICY_API_AUTH_MODE' || "
        "name=='POLICY_API_TENANT_ID' || name=='POLICY_API_AUDIENCE' || "
        "name=='POLICY_API_SCOPE' || name=='POLICY_API_CLIENT_IDS']",
    )
    settings = {row["name"]: row["value"] for row in rows}
    if (
        len(settings) != 5
        or len(rows) != 5
        or not all(isinstance(value, str) and value for value in settings.values())
        or settings["POLICY_API_AUTH_MODE"] != "delegated"
        or identifier(settings["POLICY_API_TENANT_ID"]) != tenant
    ):
        raise ValueError("Require the baseline's complete delegated API configuration")
    api = az("ad", "app", "show", "--id", settings["POLICY_API_AUDIENCE"])
    api_id = identifier(api["appId"])
    if settings["POLICY_API_AUDIENCE"] not in [api_id, *api["identifierUris"]]:
        raise ValueError("API registration does not match the baseline audience")
    scopes = [
        row
        for row in api["api"]["oauth2PermissionScopes"]
        if row["value"] == settings["POLICY_API_SCOPE"] and row["isEnabled"] is True
    ]
    if len(scopes) != 1:
        raise ValueError("Require exactly one enabled delegated scope matching the baseline")
    return Configuration(
        account,
        tenant,
        f"{name}-copilot-oauth",
        settings["POLICY_API_AUDIENCE"],
        settings["POLICY_API_SCOPE"],
        api_id,
        identifier(scopes[0]["id"]),
        settings["POLICY_API_CLIENT_IDS"],
    )


def load(journal: Path, config: Configuration) -> dict[str, Any]:
    if not journal.exists():
        raise ValueError("Run task acs:up to register the client; no manual client ID is needed")
    record: dict[str, Any] = json.loads(journal.read_text())
    if (
        record["context"] != config.context
        or record["track"] != "copilot-toolbox"
        or not record["ownership_tag"].startswith("agent-boundary-lab:copilot-toolbox:")
    ):
        raise ValueError("OAuth journal does not belong to this baseline configuration")
    identifier(record["ownership_tag"].rsplit(":", 1)[1])
    return record


def validate_application(
    app: dict[str, Any], config: Configuration, record: dict[str, Any]
) -> None:
    client = identifier(app["appId"])
    identifier(app["id"])
    if (
        app["displayName"] != config.display_name
        or record["ownership_tag"] not in app["tags"]
        or app["signInAudience"] != "AzureADMyOrg"
        or app["isFallbackPublicClient"] is not False
        or app["requiredResourceAccess"] != config.permissions
        or client == config.api_client_id
        or client in config.baseline_clients.lower()
        or (record.get("client_id") is not None and record["client_id"] != client)
        or (record.get("object_id") is not None and record["object_id"] != app["id"])
    ):
        raise ValueError("OAuth application ownership, isolation or delegated permissions drifted")


def named_applications(config: Configuration) -> list[dict[str, Any]]:
    apps: list[dict[str, Any]] = az(
        "ad", "app", "list", "--display-name", config.display_name, "--all"
    )
    if not isinstance(apps, list):
        raise ValueError("Incomplete application list")
    return [app for app in apps if app["displayName"] == config.display_name]


def setup(config: Configuration, journal: Path = JOURNAL) -> str:
    if journal.exists():
        record = load(journal, config)
        if record["phase"] not in {"create_requested", "created", "ready", "deleted"}:
            raise ValueError("OAuth deletion is pending; finish teardown before creating a client")
        if record["phase"] == "deleted":
            if named_applications(config):
                raise ValueError(
                    "Application remains after recorded teardown; inspect before reuse"
                )
            record = {}
    else:
        record = {}
    if not record:
        if named_applications(config):
            raise ValueError("An existing app has this name; refusing to adopt or modify it")
        record = {
            "track": "copilot-toolbox",
            "context": config.context,
            "ownership_tag": f"agent-boundary-lab:copilot-toolbox:{uuid4()}",
            "phase": "create_requested",
        }
        save_journal(journal, record)
        request = journal.with_name("oauth-application-request.json")
        save_journal(
            request,
            {
                "displayName": config.display_name,
                "description": "Dedicated Copilot toolbox OAuth client; not the Web UI/OBO client.",
                "signInAudience": "AzureADMyOrg",
                "isFallbackPublicClient": False,
                "tags": [record["ownership_tag"]],
                "requiredResourceAccess": config.permissions,
            },
        )
        try:
            app = az(
                "rest",
                "--method",
                "POST",
                "--url",
                "https://graph.microsoft.com/v1.0/applications",
                "--headers",
                "Content-Type=application/json",
                "--body",
                f"@{request}",
            )
        finally:
            request.unlink(missing_ok=True)
    elif record.get("object_id"):
        app = az("ad", "app", "show", "--id", record["object_id"])
    else:
        apps = named_applications(config)
        if len(apps) != 1:
            raise ValueError(
                "Uncertain application-create outcome; inspect Entra and retain the journal. "
                "No create retry was attempted."
            )
        app = apps[0]
    validate_application(app, config, record)
    record.update(
        object_id=identifier(app["id"]), client_id=identifier(app["appId"]), phase="created"
    )
    save_journal(journal, record)
    validate_application(az("ad", "app", "show", "--id", record["object_id"]), config, record)
    record["phase"] = "ready"
    save_journal(journal, record)
    return str(record["client_id"])


def client_id(config: Configuration, journal: Path = JOURNAL) -> str:
    record = load(journal, config)
    if record["phase"] != "ready":
        raise ValueError("OAuth application is not ready; rerun task acs:up to recover setup")
    client = identifier(record["client_id"])
    override = os.environ.get("COPILOT_TOOLBOX_OAUTH_CLIENT_ID")
    if override and identifier(override) != client:
        raise ValueError(
            "Unset COPILOT_TOOLBOX_OAUTH_CLIENT_ID; it conflicts with the owned client"
        )
    validate_application(az("ad", "app", "show", "--id", record["object_id"]), config, record)
    return client


def teardown(config: Configuration, journal: Path = JOURNAL) -> None:
    state = Path("infra/copilot-toolbox/terraform.tfstate")
    if not state.exists() or any(
        row["mode"] == "managed" for row in json.loads(state.read_text())["resources"]
    ):
        raise ValueError("Destroy the isolated infrastructure before deleting its OAuth client")
    if not journal.exists():
        return
    record = load(journal, config)
    if record["phase"] == "deleted":
        return
    client = identifier(record["client_id"])
    apps = az("ad", "app", "list", "--filter", f"appId eq '{client}'", "--all")
    if not isinstance(apps, list) or len(apps) > 1:
        raise ValueError("Ambiguous OAuth application readback; no delete attempted")
    if not apps:
        if record["phase"] != "delete_requested":
            raise ValueError("Owned OAuth app is missing without a recorded delete request")
    else:
        validate_application(apps[0], config, record)
        record["phase"] = "delete_requested"
        save_journal(journal, record)
        command("az", "ad", "app", "delete", "--id", record["object_id"], "--only-show-errors")
        if az("ad", "app", "list", "--filter", f"appId eq '{client}'", "--all"):
            raise ValueError("OAuth deletion is not yet visible; retain the journal and rerun down")
    record["phase"] = "deleted"
    save_journal(journal, record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "client-id", "down"])
    args = parser.parse_args()
    try:
        config = discover()
        DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(DIRECTORY / "oauth.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "down":
                teardown(config)
                print("Owned OAuth client teardown complete; baseline applications unchanged.")
            elif args.action == "client-id":
                print(client_id(config))
            else:
                previous = load(JOURNAL, config)["phase"] if JOURNAL.exists() else None
                client = setup(config)
                record = load(JOURNAL, config)
                action = (
                    "Created"
                    if previous in {None, "deleted"}
                    else "Reused"
                    if previous == "ready"
                    else "Recovered"
                )
                print(
                    f"{action} Entra app registration: {config.display_name}\n"
                    f"  Client ID: {client}\n"
                    f"  Object ID: {record['object_id']}\n"
                    f"  Tenant ID: {config.tenant_id}\n"
                    f"  Requested delegated permission: {config.audience}/{config.scope}"
                )
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as exc:
        print(f"OAuth setup blocked: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
