"""Offline consolidated setup, credential hygiene and owned recovery."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
import pytest

from containment_demo import copilot_toolbox_oauth as oauth
from containment_demo import copilot_toolbox_setup as setup
from containment_demo.copilot import save_journal
from tests.unit.test_copilot_toolbox_oauth import (
    ACCOUNT,
    API,
    BASELINE_CLIENT,
    CLIENT,
    OBJECT,
    SCOPE,
    TENANT,
)

TAG = "agent-boundary-lab:copilot-toolbox:00000000-0000-4000-8000-000000000009"
CALLBACK = "https://global.consent.azure-apim.net/redirect/" + "a" * 32


class FakeBackend:
    def __init__(self, config, registration, directory):
        self.directory = directory
        self.endpoint = "https://foundry.services.ai.azure.com/api/projects/lab-copilot"
        self.project = ACCOUNT + "/projects/lab-copilot"
        self.connection_id = self.project + "/connections/copilot-policy-oauth"
        self.rule = ACCOUNT + "/managednetworks/default/outboundrules/copilot-toolbox-mcp"
        self.graph = "https://graph.microsoft.com/v1.0/applications/" + OBJECT
        self.app = {
            "id": OBJECT,
            "appId": CLIENT,
            "displayName": config.display_name,
            "tags": [TAG],
            "signInAudience": "AzureADMyOrg",
            "isFallbackPublicClient": False,
            "requiredResourceAccess": config.permissions,
            "passwordCredentials": [
                {
                    "keyId": BASELINE_CLIENT,
                    "endDateTime": "2099-01-01T00:00:00Z",
                }
            ],
            "web": {
                "redirectUris": ["https://existing.example.test/callback"],
                "homePageUrl": None,
                "logoutUrl": None,
                "implicitGrantSettings": {"enableIdTokenIssuance": False},
            },
        }
        self.rule_properties = self.connection = None
        self.stored: dict[str, Any] = {}
        self.versions: list[dict[str, Any]] = []
        self.writes: list[tuple[str, str]] = []
        self.passwords = 0
        self.lost_password = self.lost_toolbox = False
        self.lost_binding = False
        self.needs_consent = False
        self.private_value = ""
        self.removed: list[str] = []

    def state(self):
        return json.loads((self.directory / "configuration.json").read_text())

    def request(self, method, resource, *, body=None, absent=False):
        if method != "GET":
            self.writes.append((method, resource))
        if resource == self.graph:
            if method == "PATCH":
                assert self.state()["callback_phase"] == "patch_requested"
                self.app["web"]["redirectUris"] = body["web"]["redirectUris"]
                self.app["web"]["redirectUriSettings"] = [{"uri": CALLBACK}]
            return copy.deepcopy(self.app)
        if resource == self.graph + "/addPassword":
            assert self.state()["credential"]["phase"] == "create_requested"
            self.passwords += 1
            key = f"00000000-0000-4000-8000-{self.passwords + 10:012d}"
            self.app["passwordCredentials"].append(
                {
                    "keyId": key,
                    "endDateTime": body["passwordCredential"]["endDateTime"],
                }
            )
            if self.lost_password:
                raise ValueError("Synthetic lost password response")
            self.private_value = uuid4().hex + uuid4().hex
            return {"keyId": key, "secretText": self.private_value}
        if resource == self.graph + "/removePassword":
            key = body["keyId"]
            assert key != BASELINE_CLIENT
            self.removed.append(key)
            self.app["passwordCredentials"] = [
                row for row in self.app["passwordCredentials"] if row["keyId"] != key
            ]
            return None
        if resource == self.rule.rsplit("/outboundrules/", 1)[0]:
            assert method == "GET"
            return {
                "properties": {"managedNetwork": {"isolationMode": "AllowOnlyApprovedOutbound"}}
            }
        if resource == self.rule:
            if method == "PUT":
                assert self.state()["network"]["phase"] == "create_requested"
                self.rule_properties = {**body["properties"], "status": "Active"}
            elif method == "DELETE":
                assert self.state()["phase"] == "teardown_requested"
                self.rule_properties = None
            return (
                None
                if self.rule_properties is None
                else {"properties": copy.deepcopy(self.rule_properties)}
            )
        if resource == self.connection_id:
            if method == "PUT":
                assert self.state()["credential"]["phase"] == "binding_requested"
                self.connection = copy.deepcopy(body["properties"])
                stored = self.connection.pop("credentials")
                self.stored = {
                    "clientid": stored["clientId"],
                    "clientsecret": stored["clientSecret"],
                }
                self.connection["redirectUrl"] = CALLBACK
            return (
                None if self.connection is None else {"properties": copy.deepcopy(self.connection)}
            )
        raise AssertionError((method, resource))

    def helper(self, action, **values):
        if action == "credential":
            if self.lost_binding:
                raise ValueError("Synthetic lost binding response")
            assert values["connection_id"] == self.connection_id
            digest = values.get("digest")
            return {
                "credential_verified": (
                    values["client_id"] == self.stored["clientid"]
                    and (
                        digest is None
                        or digest
                        == hashlib.sha256(self.stored["clientsecret"].encode()).hexdigest()
                    )
                )
            }
        assert action in {"versions", "create"}
        if action == "create":
            assert self.state()["toolbox"]["phase"] == "create_requested"
            self.versions.append(
                {
                    "version": str(len(self.versions) + 1),
                    "metadata": values["metadata"],
                    "tools": [values["tool"]],
                }
            )
            self.writes.append(("POST", "toolbox"))
            if self.lost_toolbox:
                raise ValueError("Synthetic lost toolbox response")
        return {"versions": copy.deepcopy(self.versions)}

    def discovery(self, endpoint):
        assert "/versions/" in endpoint
        if self.needs_consent:
            return {
                "consent_link": "https://logic-test.consent.azure-apihub.net/login?data=synthetic"
            }
        return {"tools": [{"name": "policy___get_servicing_policy", "require_approval": "never"}]}


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = oauth.Configuration(
        ACCOUNT,
        TENANT,
        "lab-copilot-oauth",
        f"api://{API}",
        "Policy.Read",
        API,
        SCOPE,
        BASELINE_CLIENT,
    )
    registration = {
        "client_id": CLIENT,
        "object_id": OBJECT,
        "ownership_tag": TAG,
        "phase": "ready",
    }
    deployment = {
        "project_id": ACCOUNT + "/projects/lab-copilot",
        "mcp_app_name": "lab-copilot-mcp",
        "mcp_url": "https://lab-copilot-mcp.environment.azurecontainerapps.io/mcp",
    }
    backend = FakeBackend(config, registration, oauth.DIRECTORY)

    def instance():
        return setup.Setup(config, registration, deployment, backend)

    return SimpleNamespace(
        config=config,
        registration=registration,
        deployment=deployment,
        backend=backend,
        instance=instance,
    )


def test_one_setup_configures_every_prerequisite_and_repeat_only_reads(configured):
    backend = configured.backend
    before_web = copy.deepcopy(backend.app["web"])
    first = configured.instance().run()
    writes = copy.deepcopy(backend.writes)
    second = configured.instance().run()
    assert first == second
    assert backend.writes == writes
    assert backend.passwords == 1
    assert first["phase"] == "ready"
    assert first["toolbox_policy_tool"] == "policy___get_servicing_policy"
    assert "/versions/1/mcp?api-version=v1" in first["toolbox_endpoint"]
    assert backend.app["web"]["redirectUris"] == [*before_web["redirectUris"], CALLBACK]
    assert backend.app["web"]["implicitGrantSettings"] == before_web["implicitGrantSettings"]
    assert BASELINE_CLIENT in {row["keyId"] for row in backend.app["passwordCredentials"]}
    assert backend.private_value not in setup.JOURNAL.read_text()
    assert setup.JOURNAL.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("operation", ["password", "binding", "toolbox"])
def test_uncertain_creates_never_duplicate_and_only_toolbox_can_recover(configured, operation):
    backend = configured.backend
    setattr(backend, "lost_" + operation, True)
    with pytest.raises(ValueError, match="lost"):
        configured.instance().run()
    writes = copy.deepcopy(backend.writes)
    if operation in {"password", "binding"}:
        with pytest.raises(ValueError, match="no addPassword retry"):
            configured.instance().run()
    else:
        assert configured.instance().run()["phase"] == "ready"
    assert backend.writes == writes
    assert backend.passwords == 1


def test_consent_stops_safely_and_same_setup_resumes_without_new_credentials(configured):
    backend = configured.backend
    backend.needs_consent = True
    with pytest.raises(ValueError, match="Consent required"):
        configured.instance().run()
    assert backend.state()["phase"] == "consent_required"
    page = oauth.DIRECTORY / "consent.html"
    assert page.stat().st_mode & 0o777 == 0o600
    assert "consent.azure-apihub.net" in page.read_text()
    writes = copy.deepcopy(backend.writes)
    backend.needs_consent = False
    assert configured.instance().run()["phase"] == "ready"
    assert backend.writes == writes
    assert not page.exists()


def test_expiring_owned_credential_is_renewed_without_deleting_existing_credentials(configured):
    backend = configured.backend
    first = configured.instance().run()
    old_key = first["credential"]["key_id"]
    expiry = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    first["credential"]["expires_at"] = expiry
    next(row for row in backend.app["passwordCredentials"] if row["keyId"] == old_key)[
        "endDateTime"
    ] = expiry
    save_journal(setup.JOURNAL, first)
    second = configured.instance().run()
    assert second["credential"]["key_id"] != old_key
    assert backend.passwords == 2
    assert backend.removed == [old_key]
    assert BASELINE_CLIENT in {row["keyId"] for row in backend.app["passwordCredentials"]}
    writes = copy.deepcopy(backend.writes)
    configured.instance().run()
    assert backend.writes == writes


def test_verified_legacy_portal_connection_and_rule_are_adopted_not_recreated(configured):
    backend = configured.backend
    old = configured.instance().run()
    portal_id = backend.project + "/connections/portal-owned"
    backend.connection_id = portal_id
    backend.versions[0]["version"] = "2"
    backend.versions[0]["tools"][0]["project_connection_id"] = portal_id
    save_journal(
        oauth.DIRECTORY / "oauth-credential.json",
        {
            "phase": "credential_verified",
            "object_id": OBJECT,
            "client_id": CLIENT,
            "connection_id": portal_id,
            "key_id": old["credential"]["key_id"],
            "expires_at": old["credential"]["expires_at"],
        },
    )
    save_journal(
        oauth.DIRECTORY / "network-probe.json",
        {
            "phase": "retained_verified",
            "rule_url": "https://management.azure.com" + backend.rule,
            "destination": old["network"]["destination"],
        },
    )
    setup.JOURNAL.unlink()
    writes = copy.deepcopy(backend.writes)
    adopted = configured.instance().run()
    assert adopted["connection_name"] == "portal-owned"
    assert adopted["toolbox"]["version"] == "2"
    assert backend.writes == writes


@pytest.mark.parametrize("drift", ["journal", "rule", "connection", "version"])
def test_foreign_or_drifted_resources_are_not_modified(configured, drift):
    backend = configured.backend
    state = configured.instance().run()
    writes = copy.deepcopy(backend.writes)
    if drift == "journal":
        state["ownership_tag"] = "foreign"
        save_journal(setup.JOURNAL, state)
    elif drift == "rule":
        backend.rule_properties["destination"] = "*.example.test"
    elif drift == "connection":
        backend.connection["metadata"]["ownership_tag"] = "foreign"
    else:
        backend.versions[0]["metadata"]["ownership_tag"] = "foreign"
    with pytest.raises(ValueError):
        configured.instance().run()
    assert backend.writes == writes


def test_down_removes_only_the_owned_exact_host_and_prevents_recreation(configured):
    backend = configured.backend
    configured.instance().run()
    before = len(backend.writes)
    configured.instance().down()
    configured.instance().down()
    assert backend.writes[before:] == [("DELETE", backend.rule)]
    with pytest.raises(ValueError, match="teardown is pending"):
        configured.instance().run()


def test_helper_checks_credentials_privately_with_the_real_sdk_field_contract(
    configured,
    monkeypatch,
    capsys,
):
    import azure.ai.projects
    import azure.identity

    value = uuid4().hex
    connection = SimpleNamespace(
        id=configured.backend.connection_id,
        credentials={"clientid": CLIENT, "clientsecret": value},
    )
    client = SimpleNamespace(
        connections=SimpleNamespace(get=lambda name, *, include_credentials: connection)
    )
    monkeypatch.setattr(azure.ai.projects, "AIProjectClient", lambda **kwargs: nullcontext(client))
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: nullcontext(object()))
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "action": "credential",
                    "endpoint": configured.backend.endpoint,
                    "name": "copilot-policy-oauth",
                    "connection_id": connection.id,
                    "client_id": CLIENT,
                    "digest": hashlib.sha256(value.encode()).hexdigest(),
                }
            )
        ),
    )
    setup.helper()
    output = capsys.readouterr().out
    assert json.loads(output) == {"credential_verified": True}
    assert value not in output


@pytest.mark.parametrize("consent", [False, True])
def test_helper_discovery_reuses_real_rpc_parser_without_a_business_call(
    configured, monkeypatch, capsys, consent
):
    import azure.ai.projects
    import azure.identity

    requests = []
    link = "https://logic-test.consent.azure-apihub.net/login?data=synthetic"
    body = {"jsonrpc": "2.0", "id": 1}
    if consent:
        body["error"] = {
            "code": -32006,
            "message": json.dumps(
                {
                    "errors": [
                        {
                            "error": {
                                "code": "CONSENT_REQUIRED",
                                "message": link,
                            }
                        }
                    ]
                }
            ),
        }
    else:
        body["result"] = {
            "tools": [
                {
                    "name": "policy___get_servicing_policy",
                    "_meta": {"tool_configuration": {"require_approval": "never"}},
                }
            ]
        }

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(
        azure.ai.projects, "AIProjectClient", lambda **kwargs: nullcontext(object())
    )
    monkeypatch.setattr(azure.identity, "DefaultAzureCredential", lambda: nullcontext(object()))
    monkeypatch.setattr(setup.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            json.dumps(
                {
                    "action": "discover",
                    "endpoint": configured.backend.endpoint,
                    "toolbox_endpoint": configured.backend.endpoint
                    + "/toolboxes/policy/versions/2/mcp",
                    "token": uuid4().hex,
                }
            )
        ),
    )
    setup.helper()
    result = json.loads(capsys.readouterr().out)
    assert result == (
        {"consent_link": link}
        if consent
        else {"tools": [{"name": "policy___get_servicing_policy", "require_approval": "never"}]}
    )
    assert [request["method"] for request in requests] == ["tools/list"]


def test_failed_recheck_revokes_ready_status(configured):
    configured.instance().run()
    configured.backend.versions[0]["metadata"]["ownership_tag"] = "foreign"
    with pytest.raises(ValueError):
        configured.instance().run()
    assert configured.backend.state()["phase"] == "configuring"


def test_rebuild_ignores_retired_legacy_journals(configured):
    old = configured.instance().run()
    save_journal(
        oauth.DIRECTORY / "oauth-credential.json",
        {
            "phase": "credential_verified",
            "object_id": OBJECT,
            "client_id": CLIENT,
            "connection_id": old["connection_id"],
            "key_id": old["credential"]["key_id"],
            "expires_at": old["credential"]["expires_at"],
        },
    )
    save_journal(
        oauth.DIRECTORY / "network-probe.json",
        {
            "phase": "retained_verified",
            "destination": old["network"]["destination"],
            "rule_url": "https://management.azure.com" + configured.backend.rule,
        },
    )
    old["phase"] = "deleted"
    save_journal(setup.JOURNAL, old)
    registration = {
        "object_id": str(uuid4()),
        "client_id": str(uuid4()),
        "ownership_tag": "agent-boundary-lab:copilot-toolbox:" + str(uuid4()),
        "phase": "ready",
    }
    backend = FakeBackend(configured.config, registration, oauth.DIRECTORY)
    backend.app.update(
        id=registration["object_id"],
        appId=registration["client_id"],
        tags=[registration["ownership_tag"]],
    )
    backend.graph = "https://graph.microsoft.com/v1.0/applications/" + registration["object_id"]
    fresh = setup.Setup(
        configured.config,
        registration,
        configured.deployment,
        backend,
    ).run()
    assert fresh["phase"] == "ready"
    assert fresh["legacy_migration"] is False
    assert fresh["context"]["client_id"] == registration["client_id"]
    assert backend.passwords == 1
