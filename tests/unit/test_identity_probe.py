"""Real signature validation and mocked transports; no Entra, Azure or model calls."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from containment_demo import identity_probe as probe

ROOT = Path(__file__).resolve().parents[2]
TENANT = "00000000-0000-4000-8000-000000000001"
BLUEPRINT = "00000000-0000-4000-8000-000000000002"
BROWSER = "00000000-0000-4000-8000-000000000003"
AGENT = "00000000-0000-4000-8000-000000000004"
ALLOWED = "00000000-0000-4000-8000-000000000005"
DENIED = "00000000-0000-4000-8000-000000000006"


@pytest.fixture
def config() -> probe.Config:
    return probe.Config(
        tenant_id=TENANT,
        blueprint_client_id=BLUEPRINT,
        browser_client_id=BROWSER,
        agent_client_id=AGENT,
        allowed_user_id=ALLOWED,
        denied_user_id=DENIED,
        foundry_endpoint="https://test.services.ai.azure.com/api/projects/test-project",
        agent_name="containment-demo-audit",
        foundry_audience="https://ai.azure.com",
        # Synthetic API scope; not a claim that Foundry publishes this permission.
        foundry_delegated_scope="synthetic.invoke",
        probe_name="gentle-fox-ab12-identity-probe",
        namespace="agent-boundary-lab",
        image="test.azurecr.io/agent@sha256:" + "a" * 64,
        sidecar_image="mcr.microsoft.com/entra-sdk/auth-sidecar@sha256:" + "b" * 64,
    )


@pytest.mark.parametrize(
    ("case", "expected_user", "expected_result"),
    [("allowed", ALLOWED, "invocation succeeds"), ("denied", DENIED, "HTTP 403")],
)
def test_login_explains_expected_account_before_authentication(
    config: probe.Config,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
    expected_user: str,
    expected_result: str,
) -> None:
    from azure.core.exceptions import ClientAuthenticationError

    observed = []

    class Credential:
        def __init__(self, **kwargs: Any) -> None:
            assert kwargs == {
                "tenant_id": config.tenant_id,
                "client_id": config.browser_client_id,
            }

        def get_token(self, scope: str) -> None:
            output = capsys.readouterr().out
            assert f"{case.upper()} test-user sign-in" in output
            assert f"Expected user object ID: {expected_user}" in output
            assert f"Tenant: {TENANT}" in output
            assert f"Expected Foundry result: {expected_result}" in output
            assert scope == f"api://{BLUEPRINT}/{probe.INPUT_SCOPE}"
            observed.append("authentication")
            raise ClientAuthenticationError(message="MUST-NOT-APPEAR-IN-OUTPUT")

        def close(self) -> None:
            observed.append("closed")

    monkeypatch.setattr(probe, "load_config", lambda _: config)
    monkeypatch.setattr("azure.identity.DeviceCodeCredential", Credential)
    monkeypatch.setattr(
        sys,
        "argv",
        ["identity_probe", "login", "--config", str(tmp_path / "config.json"), "--case", case],
    )
    assert probe.main() == 2
    assert observed == ["authentication", "closed"]
    assert "MUST-NOT-APPEAR-IN-OUTPUT" not in capsys.readouterr().out
    assert not list(tmp_path.glob("*.jwt"))


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def claims(*, incoming: bool, user: str = ALLOWED) -> dict[str, Any]:
    return {
        "aud": BLUEPRINT if incoming else "https://ai.azure.com",
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "tid": TENANT,
        "oid": user,
        "azp": BROWSER if incoming else AGENT,
        "scp": "access_as_user" if incoming else "synthetic.invoke",
        "nbf": int(time.time()) - 10,
        "exp": int(time.time()) + 300,
    }


def signed(key: rsa.RSAPrivateKey, payload: dict[str, Any]) -> str:
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test"})


def keys(key: rsa.RSAPrivateKey) -> dict[str, Any]:
    public = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [{**public, "kid": "test", "use": "sig"}]}


def test_login_reports_wrong_test_user_specifically(
    config: probe.Config, signing_key: rsa.RSAPrivateKey
) -> None:
    token = signed(signing_key, claims(incoming=True, user=ALLOWED))
    with pytest.raises(probe.ProbeError, match=r"^delegated_user_mismatch$"):
        probe.delegated_claims(
            token,
            keys(signing_key),
            config,
            audience=BLUEPRINT,
            scope=probe.INPUT_SCOPE,
            user_id=DENIED,
            client_id=BROWSER,
        )


def exercise(
    config: probe.Config,
    key: rsa.RSAPrivateKey,
    *,
    changed: dict[str, Any] | None = None,
    sidecar_status: int = 200,
    denied_status: int = 403,
    invalid_status: int = 401,
    positive: bool = True,
    failure: str | None = None,
) -> tuple[dict[str, Any], list[httpx.Request], list[str], dict[str, str]]:
    inbound = {
        name: signed(key, claims(incoming=True, user=user))
        for name, user in (("allowed", ALLOWED), ("denied", DENIED))
    }
    downstream = {
        name: signed(
            key,
            {**claims(incoming=False, user=user), **(changed or {})},
        )
        for name, user in (("allowed", ALLOWED), ("denied", DENIED))
    }
    requests: list[httpx.Request] = []
    invocations: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json=keys(key))
        if request.url.path == "/healthz":
            return httpx.Response(200)
        if request.url.path == "/Validate":
            return httpx.Response(200, json={"token": "must-not-appear-in-evidence"})
        assert request.url.path == "/AuthorizationHeader/Foundry"
        assert request.url.params["AgentIdentity"] == AGENT
        assert request.url.params["optionsOverride.RequestAppToken"] == "false"
        assert "AgentUserId" not in request.url.params
        assert "AgentUsername" not in request.url.params
        user = (
            "allowed"
            if request.headers["Authorization"] == f"Bearer {inbound['allowed']}"
            else "denied"
        )
        return httpx.Response(
            sidecar_status,
            json={"authorizationHeader": f"Bearer {downstream[user]}"},
        )

    def invoke(cfg: probe.Config, token: str) -> probe.Invocation:
        assert cfg is config
        invocations.append(token)
        if failure:
            return probe.Invocation(None, failure=failure)
        if token == downstream["allowed"]:
            return probe.Invocation(200, positive, "resp_probe" if positive else None)
        if token == downstream["denied"]:
            return probe.Invocation(denied_status)
        return probe.Invocation(invalid_status)

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        result = probe.run_probe(config, inbound, http, invoke)
    return (
        result,
        requests,
        invocations,
        {**inbound, **{f"out_{k}": v for k, v in downstream.items()}},
    )


def test_four_cases_prove_delegation_without_closing_the_rest_of_i0(
    config: probe.Config, signing_key: rsa.RSAPrivateKey
) -> None:
    result, requests, invocations, tokens = exercise(config, signing_key)
    assert result["foundry_delegation"] == "pass"
    assert result["i0_complete"] is False
    assert result["containment"] == "not_evaluated"
    assert [item["name"] for item in result["cases"]] == [
        "allowed",
        "denied",
        "invalid_token",
        "wrong_audience",
    ]
    assert len(invocations) == 4
    assert invocations[-1] == tokens["allowed"]
    evidence = json.dumps(result)
    for forbidden in (*tokens.values(), ALLOWED, DENIED, "must-not-appear-in-evidence"):
        assert forbidden not in evidence
    for request in requests:
        assert "Unauthenticated" not in request.url.path
        assert "x-ms-user-identity" not in request.headers


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("idtyp", "app"),
        ("scp", ""),
        ("azp", BROWSER),
        ("appid", BROWSER),
        ("oid", "00000000-0000-4000-8000-000000000099"),
        ("tid", BLUEPRINT),
        ("aud", "https://graph.microsoft.com"),
        ("iss", "https://untrusted.example/"),
        ("exp", 1),
        ("nbf", 9999999999),
    ],
)
def test_wrong_or_app_only_claims_never_reach_foundry_as_valid_delegation(
    config: probe.Config, signing_key: rsa.RSAPrivateKey, key: str, value: Any
) -> None:
    result, _, invocations, tokens = exercise(config, signing_key, changed={key: value})
    assert result["foundry_delegation"] == "inconclusive"
    assert tokens["out_allowed"] not in invocations
    assert tokens["out_denied"] not in invocations


def test_forged_signature_is_rejected(config: probe.Config, signing_key: rsa.RSAPrivateKey) -> None:
    forged = signed(
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        claims(incoming=False),
    )
    with pytest.raises(probe.ProbeError, match="signature_or_claims"):
        probe.delegated_claims(
            forged,
            keys(signing_key),
            config,
            audience=config.foundry_audience,
            scope=config.foundry_delegated_scope,
            user_id=ALLOWED,
            client_id=AGENT,
        )


@pytest.mark.parametrize("status", [302, 401, 403, 404, 429, 500])
def test_sidecar_error_is_inconclusive_never_app_only_fallback(
    config: probe.Config, signing_key: rsa.RSAPrivateKey, status: int
) -> None:
    result, _, calls, tokens = exercise(config, signing_key, sidecar_status=status)
    assert result["foundry_delegation"] == "inconclusive"
    assert tokens["out_allowed"] not in calls


@pytest.mark.parametrize("field", ["denied_status", "invalid_status"])
def test_accepting_negative_cases_fails_the_gate(
    config: probe.Config, signing_key: rsa.RSAPrivateKey, field: str
) -> None:
    result, _, _, _ = exercise(config, signing_key, **{field: 200})
    assert result["foundry_delegation"] == "fail"


def test_denials_without_positive_control_do_not_pass(
    config: probe.Config, signing_key: rsa.RSAPrivateKey
) -> None:
    result, _, _, _ = exercise(config, signing_key, positive=False)
    assert result["foundry_delegation"] == "inconclusive"
    assert all(case["verdict"] != "pass" for case in result["cases"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allowed_user_id", DENIED),
        ("sidecar_url", "https://sidecar.example"),
        ("foundry_endpoint", "http://test.services.ai.azure.com/api/projects/test"),
        ("foundry_endpoint", "https://test.services.ai.azure.com.evil.example/api/projects/test"),
        ("probe_name", "agent-harness-config"),
        ("image", "test.azurecr.io/agent:latest"),
        ("foundry_delegated_scope", ""),
    ],
)
def test_configuration_guards(config: probe.Config, field: str, value: str) -> None:
    with pytest.raises(probe.ProbeError):
        replace(config, **{field: value})


def test_token_files_are_private(tmp_path: Path) -> None:
    token = tmp_path / "allowed.jwt"
    token.write_text("synthetic-token")
    token.chmod(0o600)
    assert probe.read_token(token) == "synthetic-token"
    token.chmod(0o644)
    with pytest.raises(probe.ProbeError, match="owner_only"):
        probe.read_token(token)


def test_projected_probe_source_includes_shared_validator(
    config: probe.Config, tmp_path: Path
) -> None:
    rendered = probe.manifest(config, (ROOT / "src/containment_demo/identity_probe.py").read_text())
    data = rendered["items"][1]["data"]
    volumes = rendered["items"][2]["spec"]["template"]["spec"]["volumes"]
    projected = next(volume for volume in volumes if volume["name"] == "source")
    for item in projected["configMap"]["items"]:
        destination = tmp_path / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(data[item["key"]])
    result = subprocess.run(  # noqa: S603 - local copied source and fixed --help only
        [sys.executable, str(tmp_path / "probe.py"), "--help"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "containment_demo/delegated_auth.py").is_file()


def test_manifest_is_private_and_finite(config: probe.Config) -> None:
    rendered = probe.manifest(config, "# synthetic probe source")
    assert {item["kind"] for item in rendered["items"]} == {"Job", "ConfigMap", "ServiceAccount"}
    job = rendered["items"][2]["spec"]
    assert job["backoffLimit"] == 0
    assert job["activeDeadlineSeconds"] == 600
    spec = job["template"]["spec"]
    assert spec["securityContext"]["runAsGroup"] == spec["securityContext"]["fsGroup"] == 10001
    assert spec["serviceAccountName"] == config.probe_name
    assert spec["initContainers"][0]["restartPolicy"] == "Always"
    environment = {item["name"]: item["value"] for item in spec["initContainers"][0]["env"]}
    assert environment["Kestrel__Endpoints__Http__Url"] == "http://127.0.0.1:5000"
    assert environment["DownstreamApis__Foundry__RequestAppToken"] == "false"
    assert environment["AzureAd__ClientCredentials__0__SourceType"] == "SignedAssertionFilePath"
    assert "ClientSecret" not in json.dumps(rendered)
    assert ALLOWED not in json.dumps(rendered)
    assert DENIED not in json.dumps(rendered)


def test_runtime_contains_no_default_credential_or_impersonation_fallback() -> None:
    source = (ROOT / "src/containment_demo/identity_probe.py").read_text()
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.Name) and node.id == "DefaultAzureCredential"
        for node in ast.walk(tree)
    )
    assert "x-ms-user-identity" not in source
    assert "follow_redirects=False" in source
    assert "trust_env=False" in source


def test_setup_has_distinct_identities_and_no_denied_user_role() -> None:
    source = (ROOT / "infra/identity-probe/identities.tf").read_text() + (
        ROOT / "infra/identity-probe/compatibility.tf"
    ).read_text()
    assert "msgraph_resource" not in source
    assert "depends_on           = [terraform_data.setup_target]" in source
    assert "var.allowed_user_id" in source
    assert "principal_id         = var.denied_user_id" not in source
    assert 'role_definition_name = "Foundry Agent Consumer"' in source
    provider = (ROOT / "infra/identity-probe/providers.tf").read_text()
    assert 'provider "msgraph"' not in provider
    assert "tenant_id       = var.tenant_id" in provider


def test_config_file_reports_no_raw_values(config: probe.Config, tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text(json.dumps(asdict(config)))
    assert probe.load_config(target) == config
    target.write_text('{"tenant_id":"do-not-echo"}')
    with pytest.raises(probe.ProbeError, match="invalid_or_missing") as error:
        probe.load_config(target)
    assert "do-not-echo" not in str(error.value)


@pytest.mark.parametrize("status", [200, 302, 401, 403])
def test_real_sdk_constructs_delegated_named_agent_request(
    config: probe.Config, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    pytest.importorskip("azure.ai.projects")
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            json={
                "id": "resp_probe",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "output": [],
                "model": "synthetic",
            },
        )

    def client(timeout: float) -> httpx.Client:
        assert timeout == config.timeout_seconds
        return httpx.Client(
            transport=httpx.MockTransport(handle),
            follow_redirects=False,
            trust_env=False,
            timeout=timeout,
        )

    monkeypatch.setattr(probe, "http_client", client)
    result = probe.invoke_foundry(config, "synthetic-delegated-bearer")
    assert result.http_status == status
    assert result.completed is (status == 200)
    assert len(requests) == 1  # No redirect, retry, or workload-authentication fallback.
    request = requests[0]
    assert request.url.path == (
        f"/api/projects/test-project/agents/{config.agent_name}/endpoint/protocols/openai/responses"
    )
    assert request.url.params["api-version"]
    assert request.headers["Foundry-Features"]
    assert request.headers["Authorization"] == "Bearer synthetic-delegated-bearer"
    body = json.loads(request.content)
    assert body["store"] is False
    assert body["input"] == probe.PROMPT


def cluster_script() -> str:
    source = (ROOT / "tasks/Taskfile.identity.yml").read_text()
    body = source.split("  _cluster:\n", 1)[1].split("      - |\n", 1)[1]
    return textwrap.dedent(body)


@pytest.mark.parametrize("guard", ["context", "namespace", "version", "ownership"])
def test_cluster_guards_block_and_tampering_breaks_each_guard(
    config: probe.Config, tmp_path: Path, guard: str
) -> None:
    if shutil.which("jq") is None:
        pytest.skip("jq is required to exercise Task guards offline")
    directory = tmp_path / ".identity-probe"
    directory.mkdir()
    (directory / "config.json").write_text(
        json.dumps(
            asdict(
                replace(config, namespace="different" if guard == "namespace" else config.namespace)
            )
        )
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    terraform = bin_dir / "terraform"
    terraform.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        " *aks_cluster_name) echo expected-cluster ;;\n"
        " *kubernetes_namespace) echo agent-boundary-lab ;;\n"
        " *) exit 93 ;;\nesac\n"
    )
    terraform.chmod(0o755)
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        ' "config current-context") echo "$CURRENT_CONTEXT" ;;\n'
        ' "version -o json") printf \'{"serverVersion":{"major":"1","minor":"%s"}}\' "$MINOR" ;;\n'
        ' *"get job,secret,configmap,serviceaccount"*) printf "%s" "$OBJECTS" ;;\n'
        ' *) echo "unexpected mutation" >&2; exit 94 ;;\nesac\n'
    )
    kubectl.chmod(0o755)
    objects = {
        "items": [
            {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/part-of": "baseline"
                        if guard == "ownership"
                        else "identity-probe",
                        "identity-probe/name": config.probe_name,
                    }
                }
            }
        ]
    }
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PYTHONPATH": str(ROOT / "src"),
        "CURRENT_CONTEXT": "wrong-cluster" if guard == "context" else "expected-cluster",
        "MINOR": "32" if guard == "version" else "33",
        "OBJECTS": json.dumps(objects),
    }
    source = cluster_script().replace("{{.ROOT_DIR}}", str(tmp_path))
    source = source.replace(f"{tmp_path}/.venv/bin/python", sys.executable)
    if guard == "context":
        broken = source.replace('[ "$(kubectl config current-context)" = "$EXPECTED" ]', "true")
    elif guard == "namespace":
        broken = source.replace('[ "$(jq -er .namespace "$CONFIG")" = "$EXPECTED_NS" ]', "true")
    elif guard == "version":
        broken = source.replace("(.major | tonumber) > 1", "true")
    else:
        broken = re.sub(r"all\(\.items\[\];.*?\$name\)", "true", source, flags=re.S)
    assert source != broken

    def run(script: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            ["bash", "-c", script],  # noqa: S607
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    original = run(source)
    assert original.returncode != 0, original.stdout + original.stderr
    mutated = run(broken)
    assert mutated.returncode == 0, mutated.stdout + mutated.stderr


@pytest.mark.parametrize("name", ["probe", "status", "down"])
def test_cluster_operations_always_run_guards_first(name: str) -> None:
    source = (ROOT / "tasks/Taskfile.identity.yml").read_text()
    match = re.search(rf"(?ms)^  {name}:\n(.*?)(?=^  [\w-]+:|\Z)", source)
    assert match
    assert match[1].split("cmds:", 1)[1].lstrip().startswith("- task: _cluster")


def test_sidecar_startup_is_bounded(config: probe.Config, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)

    def unavailable(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503)

    with (
        httpx.Client(transport=httpx.MockTransport(unavailable)) as client,
        pytest.raises(probe.ProbeError, match="sidecar_did_not_become_ready"),
    ):
        probe.run_probe(config, {}, client)
    assert calls == ["/healthz"] * 15


@pytest.mark.parametrize("failure", ["dns_error", "tls_error", "timeout", "connection_error"])
def test_network_failure_never_proves_authentication_or_denial(
    config: probe.Config, signing_key: rsa.RSAPrivateKey, failure: str
) -> None:
    result, _, _, _ = exercise(config, signing_key, failure=failure)
    assert result["foundry_delegation"] == "inconclusive"
    assert all(case["verdict"] == "inconclusive" for case in result["cases"])


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8",
        "127.0.0.1",
        "169.254.1.1",
        "0.0.0.0",  # noqa: S104 -- DNS rejection fixture, never a listener.
        "224.0.0.1",
    ],
)
def test_nonprivate_or_special_foundry_dns_is_rejected(
    config: probe.Config, monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    monkeypatch.setattr(
        probe.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (probe.socket.AF_INET, probe.socket.SOCK_STREAM, 6, "", (address, 443))
        ],
    )
    with pytest.raises(probe.ProbeError, match="foundry_did_not_resolve_privately"):
        probe.require_private_foundry(config)
