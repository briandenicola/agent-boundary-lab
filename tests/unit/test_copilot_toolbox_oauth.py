"""Offline registration, isolation and uncertain-write recovery checks."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from containment_demo import copilot_toolbox_oauth as oauth

TENANT = "00000000-0000-4000-8000-000000000001"
SUBSCRIPTION = "00000000-0000-4000-8000-000000000002"
API = "00000000-0000-4000-8000-000000000003"
SCOPE = "00000000-0000-4000-8000-000000000004"
CLIENT = "00000000-0000-4000-8000-000000000005"
OBJECT = "00000000-0000-4000-8000-000000000006"
BASELINE_CLIENT = "00000000-0000-4000-8000-000000000007"
ACCOUNT = (
    f"/subscriptions/{SUBSCRIPTION}/resourceGroups/lab"
    "/providers/Microsoft.CognitiveServices/accounts/foundry"
)


@pytest.fixture
def directory(monkeypatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARM_TENANT_ID", TENANT)
    monkeypatch.setenv("ARM_SUBSCRIPTION_ID", SUBSCRIPTION)
    monkeypatch.delenv("COPILOT_TOOLBOX_OAUTH_CLIENT_ID", raising=False)
    state: dict[str, Any] = {
        "apps": [],
        "posts": 0,
        "deletes": 0,
        "login": {"tenantId": TENANT, "id": SUBSCRIPTION, "state": "Enabled"},
        "env": {
            "POLICY_API_AUTH_MODE": "delegated",
            "POLICY_API_TENANT_ID": TENANT,
            "POLICY_API_AUDIENCE": f"api://{API}",
            "POLICY_API_SCOPE": "Policy.Read",
            "POLICY_API_CLIENT_IDS": BASELINE_CLIENT,
        },
        "api": {
            "appId": API,
            "identifierUris": [f"api://{API}"],
            "api": {
                "oauth2PermissionScopes": [{"id": SCOPE, "value": "Policy.Read", "isEnabled": True}]
            },
        },
    }

    def fake_az(*args: str) -> Any:
        if args == ("account", "show"):
            return copy.deepcopy(state["login"])
        if args[:2] == ("containerapp", "show"):
            assert args[args.index("--resource-group") + 1] == "lab"
            assert args[args.index("--name") + 1] == "baseline-policy"
            return [{"name": key, "value": value} for key, value in state["env"].items()]
        if args[:3] == ("ad", "app", "show"):
            target = args[args.index("--id") + 1]
            if target == f"api://{API}":
                return copy.deepcopy(state["api"])
            if state.pop("fail_readback", False):
                raise ValueError("Readback unavailable")
            return copy.deepcopy(next(app for app in state["apps"] if app["id"] == target))
        if args[:3] == ("ad", "app", "list"):
            return copy.deepcopy(state["apps"])
        assert args[:3] == ("rest", "--method", "POST")
        assert args[args.index("--url") + 1] == "https://graph.microsoft.com/v1.0/applications"
        request = Path(args[args.index("--body") + 1][1:])
        assert request.stat().st_mode & 0o777 == 0o600
        assert oauth.JOURNAL.stat().st_mode & 0o777 == 0o600
        assert json.loads(oauth.JOURNAL.read_text())["phase"] == "create_requested"
        body = json.loads(request.read_text())
        assert set(body) == {
            "displayName",
            "description",
            "signInAudience",
            "isFallbackPublicClient",
            "tags",
            "requiredResourceAccess",
        }
        state["posts"] += 1
        app = {**body, "id": OBJECT, "appId": CLIENT}
        if not state.get("no_create"):
            state["apps"].append(app)
        if state.get("lost_response"):
            raise ValueError("Create response lost")
        return copy.deepcopy(app)

    def fake_command(*args: str) -> str:
        if args[0] == "terraform":
            return {
                "foundry_account_id": ACCOUNT,
                "resource_name": "lab",
                "policy_api_app_name": "baseline-policy",
            }[args[-1]]
        assert args == ("az", "ad", "app", "delete", "--id", OBJECT, "--only-show-errors")
        assert json.loads(oauth.JOURNAL.read_text())["phase"] == "delete_requested"
        state["deletes"] += 1
        state["apps"] = []
        return ""

    monkeypatch.setattr(oauth, "az", fake_az)
    monkeypatch.setattr(oauth, "command", fake_command)
    return state


def test_registration_is_private_minimal_idempotent_and_resolves_without_an_export(directory):
    config = oauth.discover()
    assert oauth.setup(config) == CLIENT
    assert oauth.setup(config) == CLIENT
    assert oauth.client_id(config) == CLIENT
    assert directory["posts"] == 1
    assert directory["apps"][0]["requiredResourceAccess"] == [
        {"resourceAppId": API, "resourceAccess": [{"id": SCOPE, "type": "Scope"}]}
    ]
    assert not (oauth.DIRECTORY / "oauth-application-request.json").exists()
    record = json.loads(oauth.JOURNAL.read_text())
    assert record["phase"] == "ready"
    assert set(record) == {"track", "context", "ownership_tag", "phase", "object_id", "client_id"}


@pytest.mark.parametrize("created", [False, True])
def test_lost_create_response_never_reposts_and_recovers_only_the_owned_app(directory, created):
    config = oauth.discover()
    directory.update(lost_response=True, no_create=not created)
    with pytest.raises(ValueError, match="response lost"):
        oauth.setup(config)
    assert json.loads(oauth.JOURNAL.read_text())["phase"] == "create_requested"
    if created:
        assert oauth.setup(config) == CLIENT
    else:
        with pytest.raises(ValueError, match="No create retry"):
            oauth.setup(config)
    assert directory["posts"] == 1
    assert not (oauth.DIRECTORY / "oauth-application-request.json").exists()


def test_failed_readback_preserves_the_known_id_for_resume(directory):
    config = oauth.discover()
    directory["fail_readback"] = True
    with pytest.raises(ValueError, match="Readback"):
        oauth.setup(config)
    assert json.loads(oauth.JOURNAL.read_text())["object_id"] == OBJECT
    assert oauth.setup(config) == CLIENT
    assert directory["posts"] == 1


def test_existing_name_is_not_adopted_or_modified(directory):
    directory["apps"] = [{"displayName": "lab-copilot-oauth"}]
    with pytest.raises(ValueError, match="refusing to adopt"):
        oauth.setup(oauth.discover())
    assert directory["posts"] == 0
    assert not oauth.JOURNAL.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tags", []),
        ("signInAudience", "AzureADMultipleOrgs"),
        ("isFallbackPublicClient", True),
        ("requiredResourceAccess", []),
        ("appId", BASELINE_CLIENT),
    ],
)
def test_plan_and_setup_reject_application_drift_without_mutation(directory, field, value):
    config = oauth.discover()
    oauth.setup(config)
    directory["apps"][0][field] = value
    with pytest.raises(ValueError, match="drifted"):
        oauth.client_id(config)
    with pytest.raises(ValueError, match="drifted"):
        oauth.setup(config)
    assert directory["posts"] == 1
    assert directory["deletes"] == 0


def test_missing_or_foreign_journal_and_conflicting_override_fail_closed(directory, monkeypatch):
    config = oauth.discover()
    with pytest.raises(ValueError, match="oauth-setup first"):
        oauth.client_id(config)
    oauth.setup(config)
    with pytest.raises(ValueError, match="does not belong"):
        oauth.client_id(replace(config, tenant_id=CLIENT))
    monkeypatch.setenv("COPILOT_TOOLBOX_OAUTH_CLIENT_ID", BASELINE_CLIENT)
    with pytest.raises(ValueError, match="conflicts"):
        oauth.client_id(config)
    assert directory["posts"] == 1


@pytest.mark.parametrize("invalid", ["tenant", "subscription", "scope", "auth_mode"])
def test_invalid_baseline_contract_blocks_before_any_mutation(directory, invalid):
    if invalid == "tenant":
        directory["env"]["POLICY_API_TENANT_ID"] = CLIENT
    elif invalid == "subscription":
        directory["login"]["id"] = CLIENT
    elif invalid == "scope":
        directory["api"]["api"]["oauth2PermissionScopes"][0]["isEnabled"] = False
    else:
        directory["env"]["POLICY_API_AUTH_MODE"] = "none"
    with pytest.raises(ValueError):
        oauth.discover()
    assert directory["posts"] == 0
    assert not oauth.JOURNAL.exists()


def test_teardown_requires_destroyed_infrastructure_and_deletes_only_the_owned_app(directory):
    config = oauth.discover()
    oauth.setup(config)
    state = Path("infra/copilot-toolbox/terraform.tfstate")
    state.parent.mkdir(parents=True)
    for resources in (None, [{"mode": "managed"}]):
        if resources is not None:
            state.write_text(json.dumps({"resources": resources}))
        with pytest.raises(ValueError, match="Destroy the isolated infrastructure"):
            oauth.teardown(config)
        assert directory["deletes"] == 0
    state.write_text(json.dumps({"resources": []}))
    oauth.teardown(config)
    oauth.teardown(config)
    assert directory["deletes"] == 1
    assert json.loads(oauth.JOURNAL.read_text())["phase"] == "deleted"
    assert oauth.setup(config) == CLIENT
    assert directory["posts"] == 2
