"""Offline publication, ownership and uncertain-write guards."""

from __future__ import annotations

import copy
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from containment_demo import copilot
from containment_demo.copilot import Publisher, PublishRequest, publication_endpoint
from containment_demo.deploy import DeploymentError, DriftError

ENDPOINT = "https://synthetic.services.ai.azure.com/api/projects/demo"
NAME = "containment-demo-audit-gov-governance-denial"
BEFORE = {
    "protocol_configuration": {"responses": {"retained": True}, "a2a": {}},
    "authorization_schemes": [{"type": "AzureRbac"}, {"type": "AgentBlueprint", "retained": True}],
    "version_selector": {"version_selection_rules": [{"type": "Latest"}]},
}
FACTS = {"version": "2", "image": "example.azurecr.io/demo@sha256:" + "a" * 64}


@pytest.fixture
def metadata() -> PublishRequest:
    return PublishRequest(
        agentDisplayName="ACS Servicing Demo",
        publishScope="Shared",
        appVersion="1.0.0",
        shortDescription="Synthetic demo",
        fullDescription="Synthetic records only.",
        developerName="Demo owner",
        developerWebsiteUrl="https://example.com",  # type: ignore[arg-type]
        privacyUrl="https://example.com/privacy",  # type: ignore[arg-type]
        termsOfUseUrl="https://example.com/terms",  # type: ignore[arg-type]
    )


class Service:
    def __init__(self) -> None:
        self.endpoint = copy.deepcopy(BEFORE)
        self.calls: list[httpx.Request] = []
        self.timeout_publish = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.url.params["api-version"] == "v1"
        assert request.headers["authorization"] == "Bearer synthetic-token"
        if request.method == "PATCH":
            assert request.headers["content-type"] == "application/merge-patch+json"
            self.endpoint = json.loads(request.content)["agent_endpoint"]
        elif request.method == "POST":
            assert request.url.path.endswith("/microsoft365/publish")
            if self.timeout_publish:
                raise httpx.ReadTimeout("response lost", request=request)
            return httpx.Response(200, json={"titleId": "synthetic-title"})
        return httpx.Response(200, json={"agent_endpoint": self.endpoint})


@pytest.fixture
def publisher(tmp_path: Path):
    service = Service()
    with httpx.Client(transport=httpx.MockTransport(service.handle)) as client:
        yield (
            Publisher(
                client, SecretStr("synthetic-token"), ENDPOINT, NAME, tmp_path / "publication.json"
            ),
            service,
        )


def test_plan_only_reads_and_preserves_every_existing_protocol_and_scheme(
    publisher: Any, metadata: PublishRequest
) -> None:
    pub, service = publisher
    before = copy.deepcopy(BEFORE)
    record = pub.plan(metadata, FACTS)
    assert [call.method for call in service.calls] == ["GET"]
    assert service.endpoint == before == BEFORE
    assert record["after"]["protocol_configuration"] == {
        **before["protocol_configuration"],
        "activity": {"enable_m365_public_endpoint": True},
    }
    assert record["after"]["authorization_schemes"] == [
        *before["authorization_schemes"],
        {"type": "BotServiceRbac"},
    ]
    assert pub.journal.stat().st_mode & 0o777 == 0o600


def test_publish_pins_owned_version_and_disable_restores_only_that_endpoint(
    publisher: Any, metadata: PublishRequest
) -> None:
    pub, service = publisher
    pub.plan(metadata, FACTS)
    record = pub.publish(metadata, FACTS)
    assert record["phase"] == "published"
    assert record["title_id"] == "synthetic-title"
    assert service.endpoint["version_selector"]["version_selection_rules"] == [
        {"type": "FixedRatio", "agent_version": "2", "traffic_percentage": 100}
    ]
    post = next(call for call in service.calls if call.method == "POST")
    assert json.loads(post.content) == metadata.payload()
    assert pub.disable()["phase"] == "disabled"
    assert service.endpoint == BEFORE
    assert all(call.method != "DELETE" for call in service.calls)


def test_uncertain_publication_is_never_retried(publisher: Any, metadata: PublishRequest) -> None:
    pub, service = publisher
    pub.plan(metadata, FACTS)
    service.timeout_publish = True
    with pytest.raises(httpx.ReadTimeout):
        pub.publish(metadata, FACTS)
    assert pub.load()["phase"] == "publish_requested"
    with pytest.raises(DeploymentError, match="never blindly retry"):
        pub.publish(metadata, FACTS)
    assert sum(call.method == "POST" for call in service.calls) == 1
    with pytest.raises(DeploymentError, match="already started"):
        pub.plan(metadata, FACTS)


@pytest.mark.parametrize("change", ["endpoint", "version", "metadata"])
def test_changed_plan_stops_before_first_write(
    publisher: Any, metadata: PublishRequest, change: str
) -> None:
    pub, service = publisher
    pub.plan(metadata, FACTS)
    facts = FACTS
    if change == "endpoint":
        service.endpoint["protocol_configuration"]["mcp"] = {}
    elif change == "version":
        facts = {**FACTS, "version": "3"}
    else:
        metadata = metadata.model_copy(update={"agentDisplayName": "Another name"})
    with pytest.raises(DriftError):
        pub.publish(metadata, facts)
    assert all(call.method == "GET" for call in service.calls)


def test_disable_refuses_to_overwrite_unrelated_changes(
    publisher: Any, metadata: PublishRequest
) -> None:
    pub, service = publisher
    pub.plan(metadata, FACTS)
    pub.publish(metadata, FACTS)
    service.endpoint["protocol_configuration"]["mcp"] = {}
    count = len(service.calls)
    with pytest.raises(DriftError, match="outside this publication"):
        pub.disable()
    assert [call.method for call in service.calls[count:]] == ["GET"]


def test_existing_channel_is_not_silently_adopted(publisher: Any, metadata: PublishRequest) -> None:
    pub, service = publisher
    service.endpoint["protocol_configuration"]["activity"] = {}
    with pytest.raises(DriftError, match="not owned"):
        pub.plan(metadata, FACTS)
    assert not pub.journal.exists()


def test_tenant_publication_cannot_be_enabled_by_metadata(metadata: PublishRequest) -> None:
    with pytest.raises(ValidationError):
        PublishRequest.model_validate({**metadata.payload(), "publishScope": "Tenant"})
    before = copy.deepcopy(BEFORE)
    before["authorization_schemes"].append({"type": "BotServiceTenant"})
    with pytest.raises(DriftError, match="tenant-wide"):
        publication_endpoint(before, "2")


def test_foreign_journal_cannot_control_another_agent(
    publisher: Any, metadata: PublishRequest
) -> None:
    pub, service = publisher
    pub.plan(metadata, FACTS)
    pub.agent_name = "another-agent"
    with pytest.raises(DriftError, match="another project or agent"):
        pub.disable()
    assert all(call.method == "GET" for call in service.calls)


def test_missing_publishing_user_token_has_no_identity_fallback(
    metadata: PublishRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(ValueError, match="publishing user's Foundry token"):
        copilot.main(["publish", "--metadata", json.dumps(metadata.payload())])


def test_placeholder_url_is_rejected_after_url_hostname_normalization(
    metadata: PublishRequest,
) -> None:
    request = PublishRequest.model_validate(
        {**metadata.payload(), "privacyUrl": "https://REPLACE-owner.example.com/privacy"}
    )
    with pytest.raises(ValueError, match="placeholder"):
        request.payload()


def test_rejected_endpoint_patch_never_reaches_publish(
    tmp_path: Path, metadata: PublishRequest
) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "PATCH":
            return httpx.Response(403, json={"error": "authorization denied"})
        return httpx.Response(200, json={"agent_endpoint": BEFORE})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        pub = Publisher(
            client, SecretStr("synthetic-token"), ENDPOINT, NAME, tmp_path / "publication.json"
        )
        pub.plan(metadata, FACTS)
        with pytest.raises(httpx.HTTPStatusError):
            pub.publish(metadata, FACTS)
        assert pub.load()["phase"] == "patch_requested"
    assert calls == ["GET", "GET", "PATCH"]


def test_missing_foundry_data_action_is_actionable_without_exposing_identity(
    tmp_path: Path, metadata: PublishRequest
) -> None:
    action = "Microsoft.CognitiveServices/accounts/AIServices/agents/read"
    identity = "00000000-0000-4000-8000-000000000001"

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": "UserError",
                    "message": f"Identity(object id: {identity}) does not have permissions for "
                    f"{action} actions. See the RBAC documentation.",
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        pub = Publisher(
            client, SecretStr("synthetic-token"), ENDPOINT, NAME, tmp_path / "publication.json"
        )
        with pytest.raises(httpx.HTTPStatusError) as error:
            pub.plan(metadata, FACTS)
    assert action in str(error.value)
    assert "task copilot:access" in str(error.value)
    assert identity not in str(error.value)
    assert "synthetic-token" not in str(error.value)
    assert not pub.journal.exists()
