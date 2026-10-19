"""Persistent setup against a fake Graph; no credentials, directory or Azure access."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from containment_demo import identity_directory as directory
from containment_demo import identity_setup as setup
from containment_demo.identity_probe import ProbeError, load_config

TENANT, CLIENT, OPERATOR, ALLOWED, DENIED, RESOURCE, APP, SCOPE = (
    str(UUID(int=number)) for number in range(1, 9)
)


@pytest.fixture
def inputs() -> setup.Inputs:
    return setup.Inputs(
        tenant_id=TENANT,
        allowed_user_id=ALLOWED,
        denied_user_id=DENIED,
        foundry_endpoint="https://synthetic.services.ai.azure.com/api/projects/synthetic",
        agent_name="containment-demo-audit",
        foundry_audience=APP,
        foundry_delegated_scope="synthetic.invoke",
        foundry_api_service_principal_id=RESOURCE,
        aks_oidc_issuer_url=f"https://synthetic.oic.prod-aks.azure.com/{TENANT}/{CLIENT}/",
        incoming_scope_id=SCOPE,
        probe_name="calm-otter-1234-identity-probe",
        namespace="agent-boundary-lab",
        image="synthetic.azurecr.io/agent@sha256:" + "a" * 64,
        sidecar_image="mcr.microsoft.com/entra-sdk/auth-sidecar@sha256:" + "b" * 64,
    )


@pytest.fixture
def settings() -> directory.Settings:
    return directory.Settings(TENANT, CLIENT, OPERATOR)


class Graph:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.created: list[str] = []
        self.failure: tuple[str, int] | None = None
        self.unknown: str | None = None
        self.keep_deleted = False
        self.ignore_patch = False
        self.contract_resource: dict[str, Any] = {
            "id": RESOURCE,
            "appId": APP,
            "servicePrincipalNames": ["https://ai.azure.com"],
            "oauth2PermissionScopes": [
                {"id": SCOPE, "value": "synthetic.invoke", "isEnabled": True}
            ],
        }

    def request(
        self,
        method: str,
        path: str,
        status: int | tuple[int, ...],
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.requests.append((method, path, copy.deepcopy(body)))
        bare = path.split("?", 1)[0]
        if method == "GET" and bare == f"servicePrincipals/{RESOURCE}":
            return copy.deepcopy(self.contract_resource)
        if method == "GET" and path.startswith("servicePrincipals?$filter="):
            return {"value": [copy.deepcopy(self.contract_resource)]}
        if method == "POST":
            key = setup.ORDER[len(self.created)]
            if self.failure is not None and self.failure[0] == key:
                raise directory.GraphError(self.failure[1])
            assert body is not None
            value = {k: copy.deepcopy(v) for k, v in body.items() if not k.endswith("@odata.bind")}
            object_id = (
                APP
                if key == "inheritance"
                else f"grant_{len(self.created)}"
                if key in setup.GRANTS
                else str(UUID(int=100 + len(self.created)))
            )
            value["id"] = object_id
            if key in ("browser", "blueprint"):
                value["appId"] = str(UUID(int=200 + len(self.created)))
            if key == "blueprint":
                instance = directory.instance("blueprint", object_id)
            elif key == "blueprint_principal":
                instance = directory.instance("principal", object_id)
            elif key == "agent":
                instance = directory.instance("agent", object_id)
            else:
                instance = f"{bare}/{object_id}"
            self.objects[instance] = value
            self.created.append(key)
            if self.unknown == key:
                raise ProbeError("directory_graph_transport_failed")
            return copy.deepcopy(value)
        if bare not in self.objects:
            raise directory.GraphError(404)
        if method == "GET":
            return copy.deepcopy(self.objects[bare])
        if method == "PATCH":
            if not self.ignore_patch:
                assert body is not None
                self.objects[bare].update(copy.deepcopy(body))
            return {}
        assert method == "DELETE"
        if not self.keep_deleted:
            del self.objects[bare]
        return {}


def test_persistent_setup_and_reverse_cleanup(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
) -> None:
    graph = Graph()
    state = tmp_path / "state.json"
    result = setup.run(graph, state, inputs, settings)
    assert result == setup.report("configured")
    assert result["i0_complete"] is False
    assert graph.created == list(setup.ORDER)
    assert len(graph.objects) == len(setup.ORDER)
    assert not any(method == "DELETE" for method, _, _ in graph.requests)
    journal = setup.load(state, inputs, settings)
    config_file = tmp_path / "config.json"
    setup.configure(config_file, journal, inputs)
    config = load_config(config_file)
    assert config.agent_client_id == journal["resources"]["agent"]["id"]
    assert config.blueprint_client_id == journal["resources"]["blueprint"]["app_id"]
    assert config.browser_client_id == journal["resources"]["browser"]["app_id"]
    assert state.stat().st_mode & 0o777 == config_file.stat().st_mode & 0o777 == 0o600
    grants = [
        body
        for method, path, body in graph.requests
        if method == "POST" and path == "oauth2PermissionGrants"
    ]
    assert len(grants) == 4
    assert all(grant is not None and grant["consentType"] == "Principal" for grant in grants)
    assert {grant["principalId"] for grant in grants if grant} == {ALLOWED, DENIED}
    assert all(
        grant["clientId"] == journal["resources"]["blueprint_principal"]["id"]
        for grant in grants
        if grant and grant["scope"] == inputs.foundry_delegated_scope
    )
    inheritance = next(
        body
        for method, path, body in graph.requests
        if method == "POST" and path.endswith("inheritablePermissions")
    )
    assert inheritance is not None
    assert inheritance["inheritableRoles"]["kind"] == "none"
    assert inheritance["inheritableScopes"]["kind"] == "allAllowed"
    expected_deletions = [setup.instance(journal, inputs, key) for key in reversed(setup.ORDER)]
    setup.cleanup(graph, state, journal, inputs)
    assert not graph.objects
    assert [path for method, path, _ in graph.requests if method == "DELETE"] == expected_deletions
    assert all(
        resource["deleted"]
        for resource in setup.load(state, inputs, settings)["resources"].values()
    )
    with pytest.raises(ProbeError, match="incomplete"):
        setup.configure(config_file, journal, inputs)


@pytest.mark.parametrize("key", setup.ORDER)
def test_definitive_failure_is_cleanable_without_retry(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
    key: str,
) -> None:
    graph = Graph()
    graph.failure = (key, 403)
    state = tmp_path / "state.json"
    with pytest.raises(directory.GraphError):
        setup.run(graph, state, inputs, settings)
    journal = setup.load(state, inputs, settings)
    assert journal["pending"] is None and not journal["complete"]
    count = len(graph.requests)
    with pytest.raises(ProbeError, match="journal_exists"):
        setup.run(graph, state, inputs, settings)
    assert len(graph.requests) == count
    setup.cleanup(graph, state, journal, inputs)
    assert not graph.objects


@pytest.mark.parametrize("status", [408, 500, 502])
def test_uncertain_creation_blocks_retry_and_cleanup(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
    status: int,
) -> None:
    graph = Graph()
    graph.failure = ("agent", status)
    state = tmp_path / "state.json"
    with pytest.raises(directory.GraphError):
        setup.run(graph, state, inputs, settings)
    journal = setup.load(state, inputs, settings)
    assert journal["pending"] == "agent"
    count = len(graph.requests)
    with pytest.raises(ProbeError, match="manual_reconciliation"):
        setup.cleanup(graph, state, journal, inputs)
    with pytest.raises(ProbeError, match="journal_exists"):
        setup.run(graph, state, inputs, settings)
    assert len(graph.requests) == count


def test_transport_failure_persists_intent(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
) -> None:
    graph = Graph()
    graph.unknown = "federation"
    state = tmp_path / "state.json"
    with pytest.raises(ProbeError, match="transport"):
        setup.run(graph, state, inputs, settings)
    assert setup.load(state, inputs, settings)["pending"] == "federation"
    assert len(graph.objects) == 6


@pytest.mark.parametrize(
    "field", ["id", "appId", "servicePrincipalNames", "oauth2PermissionScopes"]
)
def test_invalid_foundry_contract_creates_no_objects(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
    field: str,
) -> None:
    graph = Graph()
    graph.contract_resource[field] = [] if field.endswith(("Names", "Scopes")) else CLIENT
    state = tmp_path / "state.json"
    with pytest.raises(ProbeError):
        setup.run(graph, state, inputs, settings)
    assert not graph.created
    journal = setup.load(state, inputs, settings)
    setup.cleanup(graph, state, journal, inputs)
    assert len(graph.requests) == 1


@pytest.mark.parametrize("change", ["operator", "graph_client", "inputs"])
def test_journal_is_bound_to_context(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
    change: str,
) -> None:
    state = tmp_path / "state.json"
    setup.run(Graph(), state, inputs, settings)
    if change == "operator":
        settings = replace(settings, sponsor_user_id=DENIED)
    elif change == "graph_client":
        settings = replace(settings, client_id=DENIED)
    else:
        inputs = replace(inputs, agent_name="different-agent")
    with pytest.raises(ProbeError, match="context_or_schema"):
        setup.load(state, inputs, settings)


@pytest.mark.parametrize("key", ["browser", "agent", "federation", "inheritance", *setup.GRANTS])
def test_cleanup_checks_every_object_before_deleting_any(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
    key: str,
) -> None:
    graph = Graph()
    state = tmp_path / "state.json"
    setup.run(graph, state, inputs, settings)
    journal = setup.load(state, inputs, settings)
    value = graph.objects[setup.instance(journal, inputs, key)]
    if key in setup.GRANTS:
        value["principalId"] = OPERATOR
    elif key == "federation":
        value["subject"] = "system:serviceaccount:unrelated:unrelated"
    elif key == "inheritance":
        value["inheritableRoles"]["kind"] = "allAllowed"
    else:
        value["displayName"] = "unrelated"
    with pytest.raises(ProbeError, match="ownership_or_configuration"):
        setup.cleanup(graph, state, journal, inputs)
    assert not any(method == "DELETE" for method, _, _ in graph.requests)


def test_missing_audience_update_is_not_success(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
) -> None:
    graph = Graph()
    graph.ignore_patch = True
    with pytest.raises(ProbeError, match="audience_update_not_observed"):
        setup.run(graph, tmp_path / "state.json", inputs, settings)
    assert graph.created == list(setup.ORDER[:3])


def test_unobserved_deletion_stops(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
) -> None:
    graph = Graph()
    state = tmp_path / "state.json"
    setup.run(graph, state, inputs, settings)
    graph.keep_deleted = True
    with pytest.raises(ProbeError, match="deletion_not_observed"):
        setup.cleanup(graph, state, setup.load(state, inputs, settings), inputs)
    assert len([method for method, _, _ in graph.requests if method == "DELETE"]) == 1


@pytest.mark.parametrize(
    "issuer",
    [
        "http://synthetic.oic.prod-aks.azure.com/",
        f"https://synthetic.oic.prod-aks.azure.com/{CLIENT}/{TENANT}/",
        f"https://unrelated.invalid/{TENANT}/{CLIENT}/",
    ],
)
def test_federation_is_same_tenant_and_aks(inputs: setup.Inputs, issuer: str) -> None:
    with pytest.raises(ProbeError, match="same_tenant_aks"):
        replace(inputs, aks_oidc_issuer_url=issuer)


def test_contract_inventory_is_read_only() -> None:
    graph = Graph()
    result = setup.contract(graph)
    assert result["identity_setup"] == "not_evaluated"
    assert result["foundry_resource_service_principal_id"] == RESOURCE
    assert result["enabled_delegated_scopes"] == [{"value": "synthetic.invoke", "id": SCOPE}]
    assert result["i0_complete"] is False
    assert len(graph.requests) == 1 and graph.requests[0][0] == "GET"


def test_approval_before_file_or_graph_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["identity_setup", "run", "--inputs", "missing.json"])
    assert setup.main() == 2
    assert json.loads(capsys.readouterr().out)["detail"] == "setup_requires_explicit_approval"


def test_private_input_file(inputs: setup.Inputs, tmp_path: Path) -> None:
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(asdict(inputs)))
    path.chmod(0o644)
    with pytest.raises(ProbeError, match="owner_only"):
        setup.load_inputs(path)
    path.chmod(0o600)
    assert setup.load_inputs(path) == inputs


def test_incomplete_setup_cannot_export(
    inputs: setup.Inputs,
    settings: directory.Settings,
    tmp_path: Path,
) -> None:
    graph = Graph()
    state = tmp_path / "state.json"
    setup.run(graph, state, inputs, settings)
    journal = setup.load(state, inputs, settings)
    journal["complete"] = False
    with pytest.raises(ProbeError, match="incomplete"):
        setup.configure(tmp_path / "config.json", journal, inputs)


def test_disabled_foundry_scope_is_not_consentable(inputs: setup.Inputs) -> None:
    graph = Graph()
    graph.contract_resource["oauth2PermissionScopes"][0]["isEnabled"] = False
    with pytest.raises(ProbeError, match="scope_not_published"):
        setup.preflight(graph, inputs)
    with pytest.raises(ProbeError, match="no_published_enabled"):
        setup.contract(graph)
    assert all(method == "GET" for method, _, _ in graph.requests)


def test_duplicate_published_scope_is_ambiguous(inputs: setup.Inputs) -> None:
    graph = Graph()
    graph.contract_resource["oauth2PermissionScopes"] *= 2
    with pytest.raises(ProbeError, match="scope_not_published"):
        setup.preflight(graph, inputs)


def test_supported_terraform_surface_and_owner_task_order() -> None:
    root = Path(__file__).resolve().parents[2]
    terraform = "\n".join(path.read_text() for path in (root / "infra/identity-probe").glob("*.tf"))
    assert "msgraph_resource" not in terraform and 'source  = "microsoft/msgraph"' not in terraform
    assert 'resource "random_pet" "this"' in terraform
    assert 'resource "random_id" "this"' in terraform
    assert "principal_id         = var.allowed_user_id" in terraform
    assert "principal_id         = var.denied_user_id" not in terraform
    taskfile = (root / "tasks/Taskfile.identity.yml").read_text()
    setup_task = taskfile.split("\n  setup:\n", 1)[1].split("\n  configure:", 1)[0]
    assert "test ! -e" in setup_task
    assert setup_task.index("apply -input=false") < setup_task.index("-Action Setup ")
    cleanup_task = taskfile.split("\n  setup-down:\n", 1)[1].split("\n  test:", 1)[0]
    assert cleanup_task.index("task: setup-cleanup") < cleanup_task.index("destroy -input=false")
