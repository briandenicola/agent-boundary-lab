"""Owner-run, journaled configuration of the isolated OAuth toolbox."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from azure.core.exceptions import AzureError

from containment_demo import copilot_toolbox_oauth as oauth
from containment_demo.copilot import save_journal

JOURNAL = oauth.DIRECTORY / "configuration.json"
CONNECTION_API = "2026-05-15-preview"
NETWORK_API = "2025-10-01-preview"


def _expiry(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Credential expiry must have a timezone")
    return result


class Backend:
    def __init__(self, credential: Any, http: httpx.Client, endpoint: str) -> None:
        self.credential = credential
        self.http = http
        self.endpoint = endpoint
        kubectl = shutil.which("kubectl")
        if kubectl is None:
            raise ValueError("kubectl is required for the private configuration helper")
        self.kubectl = kubectl
        self.namespace = oauth.command(
            "terraform", "-chdir=infra/cloud", "output", "-raw", "kubernetes_namespace"
        )
        self.pod = (oauth.DIRECTORY / "pod").read_text().strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.pod):
            raise ValueError("Invalid isolated helper pod")

    def request(self, method: str, resource: str, *, body: Any = None, absent: bool = False) -> Any:
        graph = resource.startswith("https://graph.microsoft.com/v1.0/applications/")
        if not graph and not resource.startswith("/subscriptions/"):
            raise ValueError("Configuration request is outside Graph/ARM")
        base = "https://graph.microsoft.com" if graph else "https://management.azure.com"
        url = resource if graph else base + resource
        params = (
            None
            if graph
            else {"api-version": NETWORK_API if "/managednetworks/" in resource else CONNECTION_API}
        )
        response = self.http.request(
            method,
            url,
            params=params,
            headers={
                "Authorization": "Bearer " + self.credential.get_token(base + "/.default").token
            },
            json=body,
        )
        if absent and response.status_code == 404:
            return None
        response.raise_for_status()
        if response.status_code == 204 or (response.status_code == 202 and not response.content):
            return None
        return response.json()

    def helper(self, action: str, **values: Any) -> dict[str, Any]:
        result = subprocess.run(  # noqa: S603 - fixed executable; secrets travel only on stdin
            [
                self.kubectl,
                "-n",
                self.namespace,
                "exec",
                "-i",
                self.pod,
                "--",
                "env",
                "PYTHONPATH=/home/agent/.copilot-toolbox/source",
                "/opt/deploy-venv/bin/python",
                "-m",
                "containment_demo.copilot_toolbox_setup",
                "helper",
            ],
            input=json.dumps({"action": action, "endpoint": self.endpoint, **values}),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
        if result.returncode:
            try:
                details = json.loads(result.stdout)
            except json.JSONDecodeError:
                details = {}
            reason = details.get("error", "") if isinstance(details, dict) else ""
            status = details.get("status_code") if isinstance(details, dict) else None
            diagnostic = (
                reason
                if isinstance(reason, str) and re.fullmatch(r"[A-Za-z_]{1,80}", reason)
                else "unknown_error"
            )
            if isinstance(status, int) and 100 <= status <= 599:
                diagnostic += f"; HTTP {status}"
            raise ValueError(f"Private helper {action} failed: {diagnostic}; no credential output")
        reply: dict[str, Any] = json.loads(result.stdout)
        if not isinstance(reply, dict):
            raise ValueError("Invalid private helper response")
        return reply

    def discovery(self, endpoint: str) -> dict[str, Any]:
        return self.helper(
            "discover",
            toolbox_endpoint=endpoint,
            token=self.credential.get_token("https://ai.azure.com/.default").token,
        )


class Setup:
    def __init__(
        self,
        config: oauth.Configuration,
        registration: dict[str, Any],
        deployment: dict[str, Any],
        backend: Backend,
        journal: Path = JOURNAL,
    ) -> None:
        self.config, self.registration, self.backend, self.journal = (
            config,
            registration,
            backend,
            journal,
        )
        self.actions: dict[str, str] = {}
        prefix = config.display_name.removesuffix("-copilot-oauth")
        project = config.account_id + "/projects/" + prefix + "-copilot"
        app = prefix[:20] + "-copilot-mcp"
        url = urlparse(deployment["mcp_url"])
        if (
            deployment["project_id"] != project
            or deployment["mcp_app_name"] != app
            or url.scheme != "https"
            or url.username
            or url.password
            or url.port
            or url.path != "/mcp"
            or url.query
            or url.fragment
            or not url.hostname
            or not url.hostname.startswith(app + ".")
            or not url.hostname.endswith(".azurecontainerapps.io")
        ):
            raise ValueError("Configuration requires the convention-named isolated project/MCP")
        self.host = url.hostname
        self.project = project
        self.graph = "https://graph.microsoft.com/v1.0/applications/" + registration["object_id"]
        self.rule = config.account_id + "/managednetworks/default/outboundrules/copilot-toolbox-mcp"
        self.context = {
            "project_id": project,
            "mcp_url": deployment["mcp_url"],
            "client_id": registration["client_id"],
            "object_id": registration["object_id"],
        }
        self.migrate_legacy = not journal.exists()
        if journal.exists():
            state = json.loads(journal.read_text())
            self.migrate_legacy = state.get("legacy_migration", False)
            if state["phase"] == "deleted":
                state = {}
                self.migrate_legacy = False
            elif (
                state["context"] != self.context
                or state["ownership_tag"] != registration["ownership_tag"]
            ):
                raise ValueError("Configuration journal belongs to another project/client")
        else:
            state = {}
        self.state: dict[str, Any] = state

    def save(self) -> None:
        save_journal(self.journal, self.state)

    def application(self) -> dict[str, Any]:
        app: dict[str, Any] = self.backend.request("GET", self.graph)
        oauth.validate_application(app, self.config, self.registration)
        return app

    def initialize(self) -> None:
        if self.state:
            if self.state["phase"] in {"teardown_requested", "network_removed"}:
                raise ValueError("Configuration teardown is pending; finish down before setup")
            self.state["phase"] = "configuring"
            self.save()
            return
        self.state = {
            "phase": "configuring",
            "context": self.context,
            "ownership_tag": self.registration["ownership_tag"],
            "connection_name": "copilot-policy-oauth",
            "legacy_migration": self.migrate_legacy,
        }
        legacy = oauth.DIRECTORY / "oauth-credential.json"
        if self.migrate_legacy and legacy.exists():
            old = json.loads(legacy.read_text())
            if (
                old["phase"] != "credential_verified"
                or old["object_id"] != self.registration["object_id"]
                or old["client_id"] != self.registration["client_id"]
                or not old["connection_id"].startswith(self.project + "/connections/")
            ):
                raise ValueError("Legacy credential intent is uncertain or outside this project")
            name = old["connection_id"].rsplit("/", 1)[1]
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", name):
                raise ValueError("Invalid legacy connection name")
            self.state.update(
                connection_name=name,
                credential={
                    "phase": "verified",
                    "key_id": oauth.identifier(old["key_id"]),
                    "expires_at": old["expires_at"],
                },
            )
        self.save()

    def network(self) -> None:
        parent = self.rule.rsplit("/outboundrules/", 1)[0]
        mode = self.backend.request("GET", parent)["properties"]["managedNetwork"]["isolationMode"]
        if mode != "AllowOnlyApprovedOutbound":
            raise ValueError("Require the existing default-deny managed network; do not change it")
        actual = self.backend.request("GET", self.rule, absent=True)
        self.actions["network"] = "Created" if actual is None else "Reused"
        owned = self.state.get("network")
        if not owned:
            legacy = oauth.DIRECTORY / "network-probe.json"
            if self.migrate_legacy and legacy.exists():
                previous = json.loads(legacy.read_text())
                if (
                    previous["phase"] not in {"active", "retained_verified"}
                    or previous["rule_url"] != "https://management.azure.com" + self.rule
                    or previous["destination"] != self.host
                ):
                    raise ValueError("Legacy network intent is uncertain or differs")
                owned = {"phase": "adopted", "id": self.rule, "destination": self.host}
            elif actual is not None:
                raise ValueError(
                    "Existing exact-host rule has no ownership journal; refusing adoption"
                )
            else:
                owned = {"phase": "create_requested", "id": self.rule, "destination": self.host}
            self.state["network"] = owned
            self.save()
        if owned["id"] != self.rule or owned["destination"] != self.host:
            raise ValueError("Owned network rule scope drifted")
        if actual is None:
            if owned["phase"] != "create_requested":
                raise ValueError("Owned network rule is missing; inspect before recreation")
            self.backend.request(
                "PUT",
                self.rule,
                body={
                    "properties": {
                        "type": "FQDN",
                        "category": "UserDefined",
                        "destination": self.host,
                    }
                },
            )
        deadline = time.monotonic() + 300
        while True:
            response = self.backend.request("GET", self.rule, absent=True)
            actual = response["properties"] if response is not None else None
            if actual is not None and (
                actual["type"] != "FQDN"
                or actual["destination"] != self.host
                or actual.get("category") != "UserDefined"
            ):
                raise ValueError("Owned exact-host rule differs; refusing update")
            if actual is not None and actual.get("status") == "Active":
                break
            if (
                actual is not None and actual.get("status") == "Failed"
            ) or time.monotonic() >= deadline:
                raise ValueError("Exact-host rule is not active; retain the configuration journal")
            time.sleep(10)
        owned["phase"] = "ready"
        self.save()

    def connection_properties(self) -> dict[str, Any]:
        authority = f"https://login.microsoftonline.com/{self.config.tenant_id}/oauth2/v2.0"
        return {
            "category": "RemoteTool",
            "authType": "OAuth2",
            "target": self.context["mcp_url"],
            "isSharedToAll": False,
            "metadata": {
                "type": "custom_MCP",
                "oAuthProvider": "custom",
                "demo_track": "copilot-toolbox",
                "ownership_tag": self.registration["ownership_tag"],
            },
            "authorizationUrl": authority + "/authorize",
            "tokenUrl": authority + "/token",
            "refreshUrl": authority + "/token",
            "scopes": [
                self.config.audience.rstrip("/") + "/" + self.config.scope,
                "offline_access",
            ],
        }

    def check_connection(self, properties: dict[str, Any]) -> str:
        expected = self.connection_properties()
        if any(
            properties.get(key) != value for key, value in expected.items() if key != "metadata"
        ):
            raise ValueError("Owned OAuth connection settings drifted")
        if any(
            properties.get("metadata", {}).get(key) != value
            for key, value in expected["metadata"].items()
        ):
            raise ValueError("OAuth connection ownership/provider metadata differs")
        callback = properties.get("redirectUrl", "")
        if not re.fullmatch(
            r"https://global\.consent\.azure-apim\.net/redirect/[0-9a-f]{32}", callback
        ):
            raise ValueError("Foundry did not return a verified callback URL")
        return str(callback)

    def connection(self) -> None:
        resource = self.project + "/connections/" + self.state["connection_name"]
        actual = self.backend.request("GET", resource, absent=True)
        self.actions["connection"] = "Created" if actual is None else "Reused"
        credential = self.state.get("credential")
        app = self.application()
        if credential and credential["phase"] != "verified":
            raise ValueError(
                "Credential write outcome is uncertain; no addPassword retry attempted"
            )
        if credential:
            keys = {row["keyId"]: row for row in app["passwordCredentials"]}
            if credential["key_id"] not in keys or _expiry(
                keys[credential["key_id"]]["endDateTime"]
            ) != _expiry(credential["expires_at"]):
                raise ValueError("Owned credential is missing or its expiry drifted")
            if actual is None:
                raise ValueError(
                    "Verified credential's connection is missing; inspect before repair"
                )
            self.check_connection(actual["properties"])
            if _expiry(credential["expires_at"]) <= datetime.now(UTC) + timedelta(days=7):
                self.state["retire_key_id"] = credential["key_id"]
                credential = None
        elif actual is not None:
            raise ValueError(
                "Connection exists without verified binding ownership; refusing overwrite"
            )
        if credential is None:
            self.actions["credential"] = "Renewed" if actual is not None else "Created"
            previous = [row["keyId"] for row in app["passwordCredentials"]]
            credential = {
                "phase": "create_requested",
                "display_name": "copilot-toolbox-" + str(uuid4()),
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "previous_key_ids": previous,
            }
            self.state["credential"] = credential
            self.save()
            password = self.backend.request(
                "POST",
                self.graph + "/addPassword",
                body={
                    "passwordCredential": {
                        "displayName": credential["display_name"],
                        "endDateTime": credential["expires_at"],
                    }
                },
            )
            secret = password["secretText"]
            credential.update(phase="binding_requested", key_id=oauth.identifier(password["keyId"]))
            self.save()
            properties = self.connection_properties()
            if actual is not None:
                properties = {
                    key: value
                    for key, value in actual["properties"].items()
                    if key in {*properties, "sharedUserList", "expiryTime"}
                }
            properties["credentials"] = {
                "clientId": self.registration["client_id"],
                "clientSecret": secret,
            }
            self.backend.request("PUT", resource, body={"properties": properties})
            verified = self.backend.helper(
                "credential",
                name=self.state["connection_name"],
                connection_id=resource,
                client_id=self.registration["client_id"],
                digest=hashlib.sha256(secret.encode()).hexdigest(),
            )
            del secret, password
            if verified.get("credential_verified") is not True:
                raise ValueError("Stored credential failed private verification; retain intent")
            after = self.application()
            if {row["keyId"] for row in after["passwordCredentials"]} != (
                set(previous) | {credential["key_id"]}
            ):
                raise ValueError("Credential inventory changed unexpectedly")
            credential["phase"] = "verified"
            self.save()
        else:
            self.actions["credential"] = "Reused"
            if (
                self.backend.helper(
                    "credential",
                    name=self.state["connection_name"],
                    connection_id=resource,
                    client_id=self.registration["client_id"],
                ).get("credential_verified")
                is not True
            ):
                raise ValueError("Owned connection's stored client credential differs")
        actual = self.backend.request("GET", resource)
        callback = self.check_connection(actual["properties"])
        app = self.application()
        web = app["web"]
        self.actions["callback"] = "Reused"
        if callback not in web["redirectUris"]:
            self.actions["callback"] = "Registered"
            self.state["callback_phase"] = "patch_requested"
            self.save()
            redirects = [*web["redirectUris"], callback]
            self.backend.request("PATCH", self.graph, body={"web": {"redirectUris": redirects}})
            updated = self.application()["web"]
            if set(updated["redirectUris"]) != set(redirects) or any(
                updated.get(key) != web.get(key)
                for key in ("homePageUrl", "logoutUrl", "implicitGrantSettings")
            ):
                raise ValueError("Application callback/web configuration readback differs")
        old_key = self.state.get("retire_key_id")
        if old_key is not None:
            if old_key == credential["key_id"]:
                raise ValueError("Refusing to retire the active credential")
            if old_key in {row["keyId"] for row in self.application()["passwordCredentials"]}:
                self.backend.request(
                    "POST", self.graph + "/removePassword", body={"keyId": old_key}
                )
            if old_key in {row["keyId"] for row in self.application()["passwordCredentials"]}:
                raise ValueError("Retired credential is still present")
            del self.state["retire_key_id"]
        self.state.update(callback=callback, callback_phase="verified", connection_id=resource)
        self.save()

    def toolbox(self) -> None:
        tool = {
            "type": "mcp",
            "server_label": "policy",
            "server_url": self.context["mcp_url"],
            "require_approval": "never",
            "project_connection_id": self.state["connection_id"],
        }
        metadata = {
            "demo_track": "copilot-toolbox",
            "ownership_tag": self.registration["ownership_tag"],
        }
        versions = self.backend.helper("versions", name="copilot-policy")["versions"]
        if any(
            row["metadata"].get("ownership_tag") != metadata["ownership_tag"] for row in versions
        ):
            raise ValueError("Toolbox contains a foreign version; no mutation attempted")
        matches = [
            row for row in versions if row["tools"] == [tool] and row["metadata"] == metadata
        ]
        recorded = self.state.get("toolbox")
        if recorded and recorded.get("version"):
            matches = [row for row in matches if row["version"] == recorded["version"]]
        if not matches:
            if recorded:
                raise ValueError(
                    "Toolbox creation is uncertain or recorded version drifted; no retry"
                )
            self.state["toolbox"] = {"phase": "create_requested"}
            self.actions["toolbox"] = "Created"
            self.save()
            self.backend.helper("create", name="copilot-policy", tool=tool, metadata=metadata)
            versions = self.backend.helper("versions", name="copilot-policy")["versions"]
            matches = [
                row for row in versions if row["tools"] == [tool] and row["metadata"] == metadata
            ]
        else:
            self.actions["toolbox"] = "Reused"
        if len(matches) != 1 or not re.fullmatch(r"[1-9][0-9]*", matches[0]["version"]):
            raise ValueError("Matching immutable toolbox version is missing or ambiguous")
        version = matches[0]["version"]
        endpoint = (
            self.backend.endpoint
            + f"/toolboxes/copilot-policy/versions/{version}/mcp?api-version=v1"
        )
        self.state["toolbox"] = {"phase": "ready", "name": "copilot-policy", "version": version}
        self.state["toolbox_endpoint"] = endpoint
        self.save()

    def run(self) -> dict[str, Any]:
        self.application()
        self.initialize()
        self.network()
        self.connection()
        self.toolbox()
        result = self.backend.discovery(self.state["toolbox_endpoint"])
        if result.get("consent_link"):
            self.state["phase"] = "consent_required"
            self.save()
            consent_page(result["consent_link"])
            raise ValueError(
                "Consent required: open .task/copilot-toolbox/consent.html, then rerun infra-up"
            )
        if result.get("tools") != [
            {"name": "policy___get_servicing_policy", "require_approval": "never"}
        ]:
            raise ValueError(
                "Delegated discovery/approval failed; no business or model call was made"
            )
        self.state.update(phase="ready", toolbox_policy_tool=result["tools"][0]["name"])
        self.save()
        (oauth.DIRECTORY / "consent.html").unlink(missing_ok=True)
        return self.state

    def down(self) -> None:
        if not self.state:
            if self.backend.request("GET", self.rule, absent=True) is not None:
                raise ValueError("Consolidate existing network ownership with infra-up before down")
            return
        if self.state["phase"] == "deleted":
            return
        owned = self.state.get("network")
        if not owned or owned["id"] != self.rule or owned["destination"] != self.host:
            raise ValueError("No matching network ownership record; refusing teardown")
        actual = self.backend.request("GET", self.rule, absent=True)
        if actual is not None:
            properties = actual["properties"]
            if (
                properties["type"] != "FQDN"
                or properties["destination"] != self.host
                or properties.get("category") != "UserDefined"
            ):
                raise ValueError("Network rule drifted; refusing deletion")
            self.state["phase"] = "teardown_requested"
            self.save()
            self.backend.request("DELETE", self.rule)
            deadline = time.monotonic() + 300
            while self.backend.request("GET", self.rule, absent=True) is not None:
                if time.monotonic() >= deadline:
                    raise ValueError("Network removal is pending; retain journal and rerun down")
                time.sleep(10)
        elif self.state["phase"] not in {"teardown_requested", "network_removed"}:
            raise ValueError("Network rule missing without recorded removal intent")
        self.state["phase"] = "network_removed"
        self.save()


def consent_page(link: str) -> None:
    parsed = urlparse(link)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port
        or not parsed.hostname
        or not parsed.hostname.endswith((".consent.azure-apihub.net", ".consent.azure-apim.net"))
        or len(link) > 8192
        or any(character.isspace() or ord(character) < 32 for character in link)
    ):
        raise ValueError("Consent URL is outside the verified Azure consent hosts")
    page = oauth.DIRECTORY / "consent.html"
    descriptor = os.open(page, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(
            '<!doctype html><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\';">'
            "<title>Authorize synthetic policy lookup</title><p>"
            '<a rel="noreferrer noopener" href="'
            + html.escape(link, quote=True)
            + '">Open Microsoft consent with an authorized demo account</a></p>'
        )


def helper() -> None:
    import hmac

    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import MCPToolboxTool
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential

    from containment_demo.toolbox import ConsentRequired, _envelope

    request = json.load(sys.stdin)
    action = request["action"]
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=request["endpoint"], credential=credential) as client,
    ):
        if action == "credential":
            connection = client.connections.get(request["name"], include_credentials=True)
            stored = connection.credentials
            secret = stored["clientsecret"]
            valid = (
                connection.id == request["connection_id"]
                and stored["clientid"] == request["client_id"]
                and isinstance(secret, str)
                and bool(secret)
                and secret != "synthetic-invalid-probe-only"  # noqa: S105 - invalid probe sentinel
            )
            if "digest" in request:
                valid = valid and hmac.compare_digest(
                    hashlib.sha256(secret.encode()).hexdigest(), request["digest"]
                )
            print(json.dumps({"credential_verified": valid}))
        elif action in {"versions", "create"}:
            if action == "create":
                client.toolboxes.create_version(
                    name=request["name"],
                    metadata=request["metadata"],
                    tools=[
                        MCPToolboxTool(
                            server_label=request["tool"]["server_label"],
                            server_url=request["tool"]["server_url"],
                            require_approval=request["tool"]["require_approval"],
                            project_connection_id=request["tool"]["project_connection_id"],
                        )
                    ],
                )
            try:
                versions = list(client.toolboxes.list_versions(request["name"], limit=100))
            except ResourceNotFoundError:
                versions = []
            print(
                json.dumps(
                    {
                        "versions": [
                            {
                                "version": row.version,
                                "metadata": row.metadata,
                                "tools": [tool.as_dict() for tool in row.tools],
                            }
                            for row in versions
                        ]
                    }
                )
            )
        elif action == "discover":
            with httpx.Client(timeout=45, follow_redirects=False) as http:
                with http.stream(
                    "POST",
                    request["toolbox_endpoint"],
                    headers={
                        "Authorization": "Bearer " + request["token"],
                        "Accept": "application/json, text/event-stream",
                    },
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                ) as response:
                    response.raise_for_status()
                    data = b""
                    for chunk in response.iter_bytes():
                        data += chunk
                        if len(data) > 65536:
                            raise ValueError("Toolbox discovery response exceeds limit")
                        if "text/event-stream" in response.headers.get("content-type", ""):
                            data = data.replace(b"\r\n", b"\n")
                            if b"\n\n" in data:
                                break
                    if data.startswith(b"data:"):
                        data = data[5:].strip()
                    try:
                        result = _envelope(json.loads(data), 1)
                    except ConsentRequired as error:
                        print(json.dumps({"consent_link": error.link}))
                    else:
                        print(
                            json.dumps(
                                {
                                    "tools": [
                                        {
                                            "name": tool["name"],
                                            "require_approval": tool.get("_meta", {})
                                            .get("tool_configuration", {})
                                            .get("require_approval"),
                                        }
                                        for tool in result["tools"]
                                    ]
                                }
                            )
                        )
        else:
            raise ValueError("Unknown isolated configuration helper operation")


def main(argv: list[str] | None = None) -> int:
    from azure.identity import AzureCliCredential

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "down", "finish-down", "helper"])
    args = parser.parse_args(argv)
    try:
        if args.action == "helper":
            helper()
            return 0
        config = oauth.discover()
        registration = oauth.load(oauth.JOURNAL, config)
        oauth.DIRECTORY.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor = os.open(oauth.DIRECTORY / "oauth.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == "finish-down":
                if registration["phase"] != "deleted":
                    raise ValueError("Finish isolated infrastructure/client teardown first")
                if not JOURNAL.exists():
                    return 0
                state = json.loads(JOURNAL.read_text())
                if (
                    state["phase"] != "network_removed"
                    or registration["phase"] != "deleted"
                    or state["ownership_tag"] != registration["ownership_tag"]
                ):
                    raise ValueError("Finish isolated infrastructure/client teardown first")
                state["phase"] = "deleted"
                save_journal(JOURNAL, state)
                return 0
            deployment = json.loads(
                oauth.command(
                    "terraform", "-chdir=infra/copilot-toolbox", "output", "-json", "deployment"
                )
            )
            endpoint = (
                "https://"
                + config.account_id.rsplit("/", 1)[1]
                + ".services.ai.azure.com/api/projects/"
                + deployment["project_name"]
            )
            with (
                AzureCliCredential(subscription=config.account_id.split("/")[2]) as credential,
                httpx.Client(timeout=45, follow_redirects=False) as http,
            ):
                backend = Backend(credential, http, endpoint)
                setup = Setup(config, registration, deployment, backend)
                if args.action == "down":
                    setup.down()
                    print(
                        "Owned exact-host rule removed; project resources are removed by Terraform."
                    )
                else:
                    state = setup.run()
                    print(
                        f"{setup.actions['network']} exact-host rule: "
                        f"copilot-toolbox-mcp ({setup.host})\n"
                        f"{setup.actions['connection']} OAuth connection: "
                        f"{state['connection_id']}\n"
                        f"{setup.actions['callback']} callback: {state['callback']}\n"
                        f"{setup.actions['credential']} owned credential: "
                        f"{state['credential']['key_id']} "
                        f"(expires {state['credential']['expires_at']})\n"
                        f"{setup.actions['toolbox']} toolbox: "
                        f"copilot-policy v{state['toolbox']['version']}\n"
                        f"  Tool: {state['toolbox_policy_tool']}\n"
                        "  Delegated discovery verified; no business/model call invoked."
                    )
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        subprocess.SubprocessError,
        httpx.HTTPError,
        AzureError,
        ImportError,
    ) as error:
        if args.action == "helper":
            status = (
                error.response.status_code
                if isinstance(error, httpx.HTTPStatusError)
                else getattr(error, "status_code", None)
            )
            print(json.dumps({"error": type(error).__name__, "status_code": status}))
        elif isinstance(error, AzureError):
            print("Isolated configuration blocked: Azure credential/SDK failure", file=sys.stderr)
        else:
            print(f"Isolated configuration blocked: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
