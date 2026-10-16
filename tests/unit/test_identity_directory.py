"""Mock Graph only: no credentials, tokens, tenant mutations or Azure calls."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from azure.core.credentials import AccessToken

from containment_demo import identity_directory as directory
from containment_demo.identity_probe import ProbeError, http_client

TENANT = "00000000-0000-4000-8000-000000000001"
CLIENT = "00000000-0000-4000-8000-000000000002"
SPONSOR = "00000000-0000-4000-8000-000000000003"
APP = "00000000-0000-4000-8000-000000000004"
IDS = {
    key: f"00000000-0000-4000-8000-00000000000{number}"
    for number, key in enumerate(directory.ORDER, start=5)
}


class Credential:
    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        assert scopes == ("https://graph.microsoft.com/.default",)
        return AccessToken("synthetic-bearer-do-not-log", 9999999999)


@pytest.fixture
def settings(tmp_path: Path) -> directory.Settings:
    certificate = tmp_path / "synthetic.pem"
    certificate.write_text("synthetic certificate; never loaded by mocked tests")
    certificate.chmod(0o600)
    return directory.Settings(TENANT, CLIENT, SPONSOR, certificate)


class Service:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.failure: tuple[str, str, int] | None = None
        self.uncertain: str | None = None
        self.keep_deleted = False
        self.ignore_patch = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.host == "graph.microsoft.com"
        assert request.url.scheme == "https"
        assert request.headers["OData-Version"] == "4.0"
        assert request.headers["Authorization"] == "Bearer synthetic-bearer-do-not-log"
        path = request.url.path.removeprefix("/v1.0/")
        key = next(
            key
            for key in directory.ORDER
            if path.endswith(f"microsoft.graph.{directory.TYPES[key][1]}")
        )
        if request.method != "POST":
            assert path == directory.instance(key, IDS[key])
        if self.failure is not None and (request.method, key) == self.failure[:2]:
            return httpx.Response(
                self.failure[2],
                json={"error": {"message": "synthetic-bearer-do-not-log"}},
            )
        if request.method == "POST":
            assert path == directory.collection(key)
            body = json.loads(request.content)
            obj = {**body, "id": IDS[key]}
            if key in ("blueprint", "principal"):
                obj["appId"] = APP
            self.objects[key] = obj
            if self.uncertain == key:
                raise httpx.ReadTimeout("synthetic-bearer-do-not-log", request=request)
            return httpx.Response(201, json=obj)
        if key not in self.objects:
            return httpx.Response(404, json={"error": {"code": "Request_ResourceNotFound"}})
        if request.method == "GET":
            return httpx.Response(200, json=self.objects[key])
        if request.method == "PATCH":
            if not self.ignore_patch:
                self.objects[key].update(json.loads(request.content))
            return httpx.Response(204)
        assert request.method == "DELETE"
        if not self.keep_deleted:
            del self.objects[key]
        return httpx.Response(204)


def graph(service: Service) -> directory.Graph:
    return directory.Graph(
        httpx.Client(transport=httpx.MockTransport(service), timeout=30, follow_redirects=False),
        Credential(),
    )


def test_full_typed_lifecycle(settings: directory.Settings, tmp_path: Path) -> None:
    service = Service()
    state = tmp_path / "directory.json"
    report = directory.run(graph(service), state, settings)
    assert report == directory.result("pass")
    assert report["foundry_delegation"] == "not_evaluated"
    assert report["i0_complete"] is False
    assert not service.objects
    assert state.stat().st_mode & 0o777 == 0o600
    journal = directory.load(state, settings)
    assert all(resource["deleted"] for resource in journal["resources"].values())
    posts = [r for r in service.requests if r.method == "POST"]
    assert len(posts) == 3
    assert json.loads(posts[0].content)["sponsors@odata.bind"] == [
        f"https://graph.microsoft.com/v1.0/users/{SPONSOR}"
    ]
    assert json.loads(posts[1].content) == {"appId": APP}
    assert json.loads(posts[2].content)["agentIdentityBlueprintId"] == APP
    assert [r.url.path for r in service.requests if r.method == "DELETE"] == [
        "/v1.0/servicePrincipals/" + IDS["agent"] + "/microsoft.graph.agentIdentity",
        "/v1.0/servicePrincipals/"
        + IDS["principal"]
        + "/microsoft.graph.agentIdentityBlueprintPrincipal",
        "/v1.0/applications/" + IDS["blueprint"] + "/microsoft.graph.agentIdentityBlueprint",
    ]
    assert "synthetic-bearer-do-not-log" not in state.read_text()
    assert all(
        "$select" in request.url.params for request in service.requests if request.method == "GET"
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
def test_rejected_creation_retains_cleanup_state(
    settings: directory.Settings, tmp_path: Path, status: int
) -> None:
    service = Service()
    service.failure = ("POST", "agent", status)
    state = tmp_path / "directory.json"
    with pytest.raises(directory.GraphError, match=f"http_{status}"):
        directory.run(graph(service), state, settings)
    journal = directory.load(state, settings)
    assert journal["pending"] is None
    assert set(journal["resources"]) == {"blueprint", "principal"}
    assert not any(r.method == "DELETE" for r in service.requests)
    service.failure = None
    directory.cleanup(graph(service), state, journal)
    assert not service.objects


@pytest.mark.parametrize("status", [408, 500, 502, 503])
def test_uncertain_http_creation_is_never_retried(
    settings: directory.Settings, tmp_path: Path, status: int
) -> None:
    service = Service()
    service.failure = ("POST", "agent", status)
    state = tmp_path / "directory.json"
    with pytest.raises(directory.GraphError):
        directory.run(graph(service), state, settings)
    journal = directory.load(state, settings)
    assert journal["pending"] == "agent"
    count = len(service.requests)
    with pytest.raises(ProbeError, match="manual_reconciliation"):
        directory.cleanup(graph(service), state, journal)
    with pytest.raises(ProbeError, match="journal_exists"):
        directory.run(graph(service), state, settings)
    assert len(service.requests) == count


def test_timeout_retains_uncertain_intent_before_post(
    settings: directory.Settings, tmp_path: Path
) -> None:
    service = Service()
    service.uncertain = "principal"
    state = tmp_path / "directory.json"
    with pytest.raises(httpx.ReadTimeout):
        directory.run(graph(service), state, settings)
    journal = directory.load(state, settings)
    assert journal["pending"] == "principal"
    assert "principal" not in journal["resources"]
    assert set(service.objects) == {"blueprint", "principal"}
    with pytest.raises(ProbeError, match="manual_reconciliation"):
        directory.cleanup(graph(service), state, journal)


def retained_objects(
    settings: directory.Settings, state: Path
) -> tuple[Service, directory.Graph, dict[str, Any]]:
    service = Service()
    service.failure = ("PATCH", "blueprint", 403)
    client = graph(service)
    with pytest.raises(directory.GraphError):
        directory.run(client, state, settings)
    service.failure = None
    return service, client, directory.load(state, settings)


@pytest.mark.parametrize("key", directory.ORDER)
def test_tampered_remote_ownership_blocks_all_deletion(
    settings: directory.Settings, tmp_path: Path, key: str
) -> None:
    state = tmp_path / "directory.json"
    service, client, journal = retained_objects(settings, state)
    if key == "principal":
        service.objects[key]["appId"] = CLIENT
    else:
        service.objects[key]["displayName"] = "unrelated-object"
    with pytest.raises(ProbeError, match="mismatch"):
        directory.cleanup(client, state, journal)
    assert not any(r.method == "DELETE" for r in service.requests)


@pytest.mark.parametrize("key", directory.ORDER)
def test_tampered_object_id_blocks_deletion(
    settings: directory.Settings, tmp_path: Path, key: str
) -> None:
    state = tmp_path / "directory.json"
    service, client, journal = retained_objects(settings, state)
    service.objects[key]["id"] = CLIENT
    with pytest.raises(ProbeError, match="object_id_mismatch"):
        directory.cleanup(client, state, journal)
    assert not any(r.method == "DELETE" for r in service.requests)


def test_failed_cleanup_can_resume(settings: directory.Settings, tmp_path: Path) -> None:
    state = tmp_path / "directory.json"
    service, client, journal = retained_objects(settings, state)
    service.failure = ("DELETE", "principal", 403)
    with pytest.raises(directory.GraphError):
        directory.cleanup(client, state, journal)
    journal = directory.load(state, settings)
    assert journal["resources"]["agent"]["deleted"]
    assert not journal["resources"]["principal"]["deleted"]
    service.failure = None
    directory.cleanup(client, state, journal)
    assert not service.objects
    assert (
        sum(
            r.method == "DELETE"
            and r.url.path == "/v1.0/" + directory.instance("agent", IDS["agent"])
            for r in service.requests
        )
        == 1
    )


def test_missing_recorded_object_is_cleanup_not_a_lifecycle_pass(
    settings: directory.Settings, tmp_path: Path
) -> None:
    state = tmp_path / "directory.json"
    service, client, journal = retained_objects(settings, state)
    del service.objects["agent"]
    directory.cleanup(client, state, journal)
    assert not service.objects


@pytest.mark.parametrize("ignored_operation", ["PATCH", "DELETE"])
def test_success_status_alone_does_not_pass(
    settings: directory.Settings, tmp_path: Path, ignored_operation: str
) -> None:
    service = Service()
    service.ignore_patch = ignored_operation == "PATCH"
    service.keep_deleted = ignored_operation == "DELETE"
    with pytest.raises(ProbeError, match="not_observed"):
        directory.run(graph(service), tmp_path / "directory.json", settings)


def test_wrong_tenant_or_client_cannot_load_journal(
    settings: directory.Settings, tmp_path: Path
) -> None:
    state = tmp_path / "directory.json"
    directory.run(graph(Service()), state, settings)
    for changed in (replace(settings, tenant_id=APP), replace(settings, client_id=APP)):
        with pytest.raises(ProbeError, match="context_or_schema"):
            directory.load(state, changed)


@pytest.mark.parametrize("change", ["orphan_agent", "missing_blueprint_app_id", "invalid_id"])
def test_malformed_journal_is_rejected_before_cleanup(
    settings: directory.Settings, tmp_path: Path, change: str
) -> None:
    state = tmp_path / "directory.json"
    _, _, journal = retained_objects(settings, state)
    if change == "orphan_agent":
        del journal["resources"]["blueprint"]
    elif change == "missing_blueprint_app_id":
        del journal["resources"]["blueprint"]["app_id"]
    else:
        journal["resources"]["agent"]["id"] = "../unrelated"
    directory.save(state, journal)
    with pytest.raises(ProbeError):
        directory.load(state, settings)


def test_private_files_and_lock(settings: directory.Settings, tmp_path: Path) -> None:
    state = tmp_path / "directory.json"
    directory.run(graph(Service()), state, settings)
    state.chmod(0o644)
    with pytest.raises(ProbeError, match="owner_only"):
        directory.load(state, settings)
    with directory.journal_lock(state), pytest.raises(ProbeError, match="journal_in_use"):
        with directory.journal_lock(state):
            pytest.fail("concurrent journal access")
    linked = tmp_path / "symlink.json"
    linked.symlink_to(state)
    with pytest.raises(OSError):
        directory.load(linked, settings)
    settings.certificate_path.chmod(0o644)
    with pytest.raises(ProbeError, match="certificate_must_be_owner_only"):
        replace(settings)


def test_client_tls_timeout_and_redirect_defaults() -> None:
    with http_client(30) as client:
        assert not client.follow_redirects
        assert client.timeout == httpx.Timeout(30)
        assert client._transport._pool._ssl_context.verify_mode != 0


def test_plan_is_offline_and_mutation_requires_approval(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(directory, "CertificateCredential", lambda **kw: pytest.fail("credentials"))
    monkeypatch.setattr(directory.sys, "argv", ["identity_directory", "plan"])
    assert directory.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["directory_lifecycle"] == "not_run"
    assert report["i0_complete"] is False
    for command in ("run", "cleanup"):
        monkeypatch.setattr(directory.sys, "argv", ["identity_directory", command])
        assert directory.main() == 2
        assert "explicit_approval" in capsys.readouterr().out


def test_error_output_never_prints_exception_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: directory.Settings,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("IDENTITY_TENANT_ID", TENANT)
    monkeypatch.setenv("IDENTITY_GRAPH_CLIENT_ID", CLIENT)
    monkeypatch.setenv("IDENTITY_SPONSOR_USER_ID", SPONSOR)
    monkeypatch.setenv("IDENTITY_GRAPH_CERTIFICATE_PATH", str(settings.certificate_path))
    monkeypatch.setattr(
        directory.sys,
        "argv",
        ["identity_directory", "run", "--approve", "--state", str(tmp_path / "directory.json")],
    )

    def fail(**kwargs: Any) -> None:
        raise directory.ClientAuthenticationError(message="synthetic-bearer-do-not-log")

    monkeypatch.setattr(directory, "CertificateCredential", fail)
    assert directory.main() == 2
    output = capsys.readouterr().out
    assert "synthetic-bearer-do-not-log" not in output
    assert "certificate_authentication_failed" in output


@pytest.mark.parametrize("status", [302, 401, 403, 500])
def test_graph_body_and_bearer_are_not_reported(status: int) -> None:
    def response(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            headers={"Location": "https://unrelated.invalid/"},
            json={"error": {"message": "synthetic-bearer-do-not-log"}},
        )

    with httpx.Client(transport=httpx.MockTransport(response), follow_redirects=False) as http:
        client = directory.Graph(http, Credential())
        with pytest.raises(directory.GraphError) as failure:
            client.request("POST", directory.collection("blueprint"), 201, {})
        assert str(failure.value) == f"directory_graph_http_{status}"


def test_approved_cli_uses_certificate_sdk_and_bounded_transport(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: directory.Settings,
    tmp_path: Path,
) -> None:
    service = Service()
    observed: dict[str, Any] = {}

    class ScopedCredential(Credential):
        def __enter__(self) -> ScopedCredential:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def credential(**kwargs: Any) -> ScopedCredential:
        observed.update(kwargs)
        return ScopedCredential()

    monkeypatch.setenv("IDENTITY_TENANT_ID", TENANT)
    monkeypatch.setenv("IDENTITY_GRAPH_CLIENT_ID", CLIENT)
    monkeypatch.setenv("IDENTITY_SPONSOR_USER_ID", SPONSOR)
    monkeypatch.setenv("IDENTITY_GRAPH_CERTIFICATE_PATH", str(settings.certificate_path))
    monkeypatch.setattr(directory, "CertificateCredential", credential)
    monkeypatch.setattr(
        directory,
        "http_client",
        lambda timeout: httpx.Client(transport=httpx.MockTransport(service), timeout=timeout),
    )
    monkeypatch.setattr(
        directory.sys,
        "argv",
        ["identity_directory", "run", "--approve", "--state", str(tmp_path / "directory.json")],
    )
    assert directory.main() == 0
    assert json.loads(capsys.readouterr().out)["directory_lifecycle"] == "pass"
    assert observed == {
        "tenant_id": TENANT,
        "client_id": CLIENT,
        "certificate_path": str(settings.certificate_path),
        "connection_timeout": 10,
        "read_timeout": 30,
        "retry_total": 0,
    }
    assert not service.objects


def test_tasks_keep_directory_probe_separate_from_foundry() -> None:
    root = Path(__file__).resolve().parents[2]
    taskfile = (root / "tasks/Taskfile.identity.yml").read_text()
    assert "PYTHONPATH: '{{.ROOT_DIR}}/src'" in taskfile
    assert "directory-plan:" in taskfile
    for target in ("directory-probe", "directory-cleanup"):
        block = taskfile.split(f"  {target}:", 1)[1].split("\n\n  ", 1)[0]
        assert "prompt:" in block
        assert "--approve" in block
        assert "identity_directory" in block
