"""Opt-in I0 probe. Tokens stay in memory; output contains verdicts, never claims."""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import re
import socket
import stat
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import jwt

FOUNDRY_SCOPE = "https://ai.azure.com/.default"
INPUT_SCOPE = "access_as_user"
PROMPT = "This is a synthetic authentication probe. Reply OK without calling any tools."


class ProbeError(Exception):
    """A safe, fixed diagnostic code; never wrap an exception containing token data."""


@dataclass(frozen=True)
class Config:
    tenant_id: str
    blueprint_client_id: str
    browser_client_id: str
    agent_client_id: str
    allowed_user_id: str = field(repr=False)
    denied_user_id: str = field(repr=False)
    foundry_endpoint: str
    agent_name: str
    foundry_audience: str
    foundry_delegated_scope: str
    probe_name: str
    namespace: str
    image: str
    sidecar_image: str
    sidecar_url: str = "http://127.0.0.1:5000"
    timeout_seconds: float = 30

    def __post_init__(self) -> None:
        for value in (
            self.tenant_id,
            self.blueprint_client_id,
            self.browser_client_id,
            self.agent_client_id,
            self.allowed_user_id,
            self.denied_user_id,
        ):
            try:
                UUID(value)
            except (ValueError, TypeError, AttributeError):
                raise ProbeError("configuration_requires_real_identity_ids") from None
        if self.allowed_user_id == self.denied_user_id:
            raise ProbeError("test_users_must_differ")
        if len({self.blueprint_client_id, self.browser_client_id, self.agent_client_id}) != 3:
            raise ProbeError("blueprint_browser_and_agent_must_differ")
        endpoint = urlsplit(self.foundry_endpoint)
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or not endpoint.hostname.endswith(".services.ai.azure.com")
            or endpoint.username
            or endpoint.password
            or endpoint.port not in (None, 443)
            or endpoint.query
            or endpoint.fragment
            or not re.fullmatch(r"/api/projects/[A-Za-z0-9-]+", endpoint.path)
        ):
            raise ProbeError("invalid_private_foundry_endpoint")
        if self.sidecar_url != "http://127.0.0.1:5000":
            raise ProbeError("sidecar_must_be_pod_local")
        if not self.foundry_audience or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_.-]*", self.foundry_delegated_scope
        ):
            raise ProbeError("verified_foundry_audience_and_scope_required")
        for value in (self.probe_name, self.namespace, self.agent_name):
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
                raise ProbeError("invalid_probe_resource_name")
        if not re.fullmatch(r"[a-z]+-[a-z]+-[0-9a-f]{4}-identity-probe", self.probe_name):
            raise ProbeError("dedicated_generated_probe_name_required")
        for image in (self.image, self.sidecar_image):
            if not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}", image):
                raise ProbeError("probe_images_must_be_digest_pinned")
        if not 1 <= self.timeout_seconds <= 120:
            raise ProbeError("invalid_bounded_timeout")


def load_config(path: Path) -> Config:
    try:
        return Config(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        raise ProbeError("invalid_or_missing_private_configuration") from None


def read_token(path: Path) -> str:
    try:
        info = path.stat()
        projected_secret = (
            info.st_uid == 0 and info.st_gid == os.getegid() and not info.st_mode & 0o037
        )
        if not stat.S_ISREG(info.st_mode) or (info.st_mode & 0o077 and not projected_secret):
            raise ProbeError("token_file_must_be_owner_only")
        value = path.read_text().strip()
    except OSError:
        raise ProbeError("token_file_missing") from None
    if not value or len(value) > 32768 or any(character.isspace() for character in value):
        raise ProbeError("invalid_token_file")
    return value


def require_private_foundry(config: Config) -> None:
    try:
        addresses = socket.getaddrinfo(
            urlsplit(config.foundry_endpoint).hostname, 443, type=socket.SOCK_STREAM
        )
    except socket.gaierror:
        raise ProbeError("foundry_dns_failure") from None
    if not addresses or any(
        not ipaddress.ip_address(entry[4][0]).is_private
        or ipaddress.ip_address(entry[4][0]).is_loopback
        or ipaddress.ip_address(entry[4][0]).is_link_local
        or ipaddress.ip_address(entry[4][0]).is_unspecified
        or ipaddress.ip_address(entry[4][0]).is_multicast
        or ipaddress.ip_address(entry[4][0]).is_reserved
        for entry in addresses
    ):
        raise ProbeError("foundry_did_not_resolve_privately")


def http_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)


def signing_keys(http: httpx.Client, config: Config) -> dict[str, Any]:
    response = http.get(f"https://login.microsoftonline.com/{config.tenant_id}/discovery/v2.0/keys")
    if response.status_code != 200:
        raise ProbeError("tenant_signing_keys_unavailable")
    try:
        keys = response.json()
    except ValueError:
        raise ProbeError("invalid_tenant_signing_keys") from None
    if (
        not isinstance(keys, dict)
        or not isinstance(keys.get("keys"), list)
        or not all(isinstance(key, dict) for key in keys["keys"])
    ):
        raise ProbeError("invalid_tenant_signing_keys")
    return keys


def delegated_claims(
    token: str,
    keys: dict[str, Any],
    config: Config,
    *,
    audience: str,
    scope: str,
    user_id: str,
    client_id: str,
) -> None:
    try:
        header = jwt.get_unverified_header(token)
        matches = [
            key
            for key in keys["keys"]
            if key.get("kid") == header.get("kid")
            and key.get("kty") == "RSA"
            and key.get("use", "sig") == "sig"
        ]
        if not header.get("kid") or len(matches) != 1 or header.get("alg") != "RS256":
            raise ProbeError("token_signing_key_or_algorithm_rejected")
        key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256")
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=[
                f"https://login.microsoftonline.com/{config.tenant_id}/v2.0",
                f"https://sts.windows.net/{config.tenant_id}/",
            ],
            options={"require": ["exp", "nbf", "aud", "iss", "tid", "oid", "scp"]},
        )
        if (
            claims["tid"] != config.tenant_id
            or claims["oid"] != user_id
            or claims.get("idtyp") == "app"
            or not isinstance(claims["scp"], str)
            or scope not in claims["scp"].split()
            or claims.get("azp", claims.get("appid")) != client_id
            or ("appid" in claims and claims["appid"] != client_id)
            or not isinstance(claims["exp"], (float, int))
            or not isinstance(claims["nbf"], (float, int))
        ):
            raise ProbeError("delegated_user_scope_or_client_mismatch")
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise ProbeError("token_signature_or_claims_rejected") from None


@dataclass(frozen=True)
class Invocation:
    http_status: int | None
    completed: bool = False
    response_id: str | None = None
    failure: str | None = None


def invoke_foundry(config: Config, token: str) -> Invocation:
    from azure.ai.projects import AIProjectClient
    from azure.core.credentials import AccessToken
    from openai import APIConnectionError, APIStatusError

    class DelegatedCredential:
        def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
            if scopes != (FOUNDRY_SCOPE,):
                raise ProbeError("sdk_requested_an_unexpected_resource")
            return AccessToken(token, int(time.time()) + 300)

    # No DefaultAzureCredential, user-identity header, body logging, or app-only retry.
    with (
        AIProjectClient(
            endpoint=config.foundry_endpoint,
            credential=DelegatedCredential(),
            allow_preview=True,
            connection_timeout=config.timeout_seconds,
            read_timeout=config.timeout_seconds,
            retry_total=0,
        ) as project,
        http_client(config.timeout_seconds) as transport,
        project.get_openai_client(
            agent_name=config.agent_name,
            http_client=transport,
            max_retries=0,
        ) as client,
    ):
        try:
            raw = client.responses.with_raw_response.create(
                model="",
                input=PROMPT,
                store=False,
                timeout=config.timeout_seconds,
            )
            response = raw.parse()
        except APIStatusError as exc:
            return Invocation(http_status=exc.status_code)
        except APIConnectionError as exc:
            from containment_demo.invoke import classify_invocation_exception

            return Invocation(None, failure=str(classify_invocation_exception(exc)))
        response_id = response.id
        if not isinstance(response_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", response_id
        ):
            response_id = None
        return Invocation(raw.status_code, response.status == "completed", response_id)


@dataclass(frozen=True)
class Case:
    name: str
    verdict: str
    stage: str
    http_status: int | None = None
    detail: str | None = None
    response_id: str | None = None


def run_probe(
    config: Config,
    tokens: dict[str, str],
    http: httpx.Client,
    invoke: Callable[[Config, str], Invocation] = invoke_foundry,
) -> dict[str, Any]:
    results: list[Case] = []
    for attempt in range(15):
        try:
            health = http.get(f"{config.sidecar_url}/healthz", timeout=2)
            if health.status_code == 200:
                break
        except httpx.HTTPError:
            pass  # Bounded startup observation; exhaustion is explicit, never success.
        if attempt == 14:
            raise ProbeError("sidecar_did_not_become_ready")
        time.sleep(1)
    keys = signing_keys(http, config)
    for name, user in (("allowed", config.allowed_user_id), ("denied", config.denied_user_id)):
        stage = "incoming_validation"
        try:
            token = tokens[name]
            delegated_claims(
                token,
                keys,
                config,
                audience=config.blueprint_client_id,
                scope=INPUT_SCOPE,
                user_id=user,
                client_id=config.browser_client_id,
            )
            validation = http.get(
                f"{config.sidecar_url}/Validate", headers={"Authorization": f"Bearer {token}"}
            )
            if validation.status_code != 200:
                results.append(Case(name, "inconclusive", stage, validation.status_code))
                continue
            stage = "sidecar_obo"
            reply = http.get(
                f"{config.sidecar_url}/AuthorizationHeader/Foundry",
                params={
                    "AgentIdentity": config.agent_client_id,
                    "optionsOverride.RequestAppToken": "false",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if reply.status_code != 200:
                results.append(Case(name, "inconclusive", stage, reply.status_code))
                continue
            payload = reply.json()
            if not isinstance(payload, dict):
                raise ProbeError("invalid_sidecar_response")
            authorization = payload.get("authorizationHeader")
            if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
                raise ProbeError("sidecar_did_not_return_a_bearer")
            downstream = authorization.removeprefix("Bearer ")
            stage = "delegated_token_validation"
            delegated_claims(
                downstream,
                keys,
                config,
                audience=config.foundry_audience,
                scope=config.foundry_delegated_scope,
                user_id=user,
                client_id=config.agent_client_id,
            )
            stage = "foundry_invocation"
            outcome = invoke(config, downstream)
            if name == "allowed":
                verdict = (
                    "pass"
                    if outcome.http_status is not None
                    and 200 <= outcome.http_status < 300
                    and outcome.completed
                    and outcome.response_id
                    else "inconclusive"
                )
            elif outcome.http_status == 403:
                verdict = "pass"
            elif outcome.http_status is not None and 200 <= outcome.http_status < 300:
                verdict = "fail"
            else:
                verdict = "inconclusive"
            results.append(
                Case(
                    name, verdict, stage, outcome.http_status, outcome.failure, outcome.response_id
                )
            )
        except ProbeError as exc:
            results.append(Case(name, "inconclusive", stage, detail=str(exc)))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            results.append(Case(name, "inconclusive", stage, detail="request_or_response_invalid"))
    # The blueprint-audience token is a genuine signed token for the WRONG resource.
    for name, value in (
        ("invalid_token", "invalid-identity-probe-token"),
        ("wrong_audience", tokens["allowed"]),
    ):
        try:
            outcome = invoke(config, value)
        except ProbeError as exc:
            results.append(Case(name, "inconclusive", "foundry_invocation", detail=str(exc)))
            continue
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            results.append(
                Case(
                    name, "inconclusive", "foundry_invocation", detail="request_or_response_invalid"
                )
            )
            continue
        verdict = (
            "pass"
            if outcome.http_status in (401, 403)
            else "fail"
            if outcome.http_status is not None and 200 <= outcome.http_status < 300
            else "inconclusive"
        )
        results.append(
            Case(name, verdict, "foundry_invocation", outcome.http_status, outcome.failure)
        )
    positive = results[0].verdict == "pass"
    if not positive:
        results = [
            Case(
                item.name, "inconclusive", item.stage, item.http_status, "positive_control_missing"
            )
            if item.verdict == "pass"
            else item
            for item in results
        ]
    verdict = (
        "fail"
        if any(item.verdict == "fail" for item in results)
        else "pass"
        if positive and all(item.verdict == "pass" for item in results)
        else "inconclusive"
    )
    packages = {}
    for package in ("azure-ai-projects", "openai", "PyJWT", "azure-ai-agentserver-responses"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = "not_installed"
    return {
        "probe_run_id": str(uuid4()),
        "observed_at": datetime.now(UTC).isoformat(),
        "execution": "hosted",
        "foundry_delegation": verdict,
        "i0_complete": False,
        "containment": "not_evaluated",
        "runtime_packages": packages,
        "protocol": {"name": "responses", "version": "not_verified_by_probe"},
        "images": {
            "probe": config.image,
            "sidecar": config.sidecar_image,
            "hosted_agent": "not_verified_by_probe",
        },
        "cases": [asdict(item) for item in results],
    }


def manifest(config: Config, source: str) -> dict[str, Any]:
    name = config.probe_name
    labels = {"app.kubernetes.io/part-of": "identity-probe", "identity-probe/name": name}
    environment = {
        "AzureAd__Instance": "https://login.microsoftonline.com/",
        "AzureAd__TenantId": config.tenant_id,
        "AzureAd__ClientId": config.blueprint_client_id,
        "AzureAd__Audience": config.blueprint_client_id,
        "AzureAd__Scopes": INPUT_SCOPE,
        "AzureAd__ClientCredentials__0__SourceType": "SignedAssertionFilePath",
        "DownstreamApis__Foundry__BaseUrl": config.foundry_endpoint + "/",
        "DownstreamApis__Foundry__Scopes__0": FOUNDRY_SCOPE,
        "DownstreamApis__Foundry__RequestAppToken": "false",
        "Kestrel__Endpoints__Http__Url": config.sidecar_url,
        "Logging__LogLevel__Default": "Warning",
    }
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "ServiceAccount",
                "metadata": {
                    "name": name,
                    "namespace": config.namespace,
                    "labels": labels,
                    "annotations": {
                        "azure.workload.identity/client-id": config.blueprint_client_id
                    },
                },
            },
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": name, "namespace": config.namespace, "labels": labels},
                "data": {"probe.py": source},
            },
            {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {"name": name, "namespace": config.namespace, "labels": labels},
                "spec": {
                    "backoffLimit": 0,
                    "activeDeadlineSeconds": 600,
                    "ttlSecondsAfterFinished": 3600,
                    "template": {
                        "metadata": {"labels": {"azure.workload.identity/use": "true"}},
                        "spec": {
                            "serviceAccountName": name,
                            "restartPolicy": "Never",
                            "securityContext": {
                                "runAsNonRoot": True,
                                "runAsUser": 10001,
                                "runAsGroup": 10001,
                                "fsGroup": 10001,
                            },
                            # Native sidecar exits when the finite probe exits (Kubernetes >=1.33).
                            "initContainers": [
                                {
                                    "name": "auth-sidecar",
                                    "restartPolicy": "Always",
                                    "image": config.sidecar_image,
                                    "env": [
                                        {"name": key, "value": value}
                                        for key, value in environment.items()
                                    ],
                                    "resources": {
                                        "requests": {"cpu": "100m", "memory": "128Mi"},
                                        "limits": {"cpu": "500m", "memory": "512Mi"},
                                    },
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                }
                            ],
                            "containers": [
                                {
                                    "name": "probe",
                                    "image": config.image,
                                    "command": [
                                        "/opt/deploy-venv/bin/python",
                                        "/opt/identity-probe/probe.py",
                                        "run",
                                        "--config",
                                        "/run/identity/config.json",
                                        "--tokens-dir",
                                        "/run/identity",
                                    ],
                                    "volumeMounts": [
                                        {
                                            "name": "source",
                                            "mountPath": "/opt/identity-probe",
                                            "readOnly": True,
                                        },
                                        {
                                            "name": "identity",
                                            "mountPath": "/run/identity",
                                            "readOnly": True,
                                        },
                                    ],
                                    "resources": {
                                        "requests": {"cpu": "100m", "memory": "256Mi"},
                                        "limits": {"cpu": "500m", "memory": "512Mi"},
                                    },
                                    "securityContext": {
                                        "allowPrivilegeEscalation": False,
                                        "capabilities": {"drop": ["ALL"]},
                                    },
                                }
                            ],
                            "volumes": [
                                {"name": "source", "configMap": {"name": name}},
                                {
                                    "name": "identity",
                                    "secret": {"secretName": name, "defaultMode": 0o440},
                                },
                            ],
                        },
                    },
                },
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run", "login", "manifest"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tokens-dir", type=Path)
    parser.add_argument("--case", choices=("allowed", "denied"), default="allowed")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    for name in ("azure", "httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        config = load_config(args.config)
        if args.command == "manifest":
            print(json.dumps(manifest(config, Path(__file__).read_text())))
            return 0
        if args.command == "check":
            if args.tokens_dir is not None:
                for name in ("allowed", "denied"):
                    read_token(args.tokens_dir / f"{name}.jwt")
            print("Configuration valid. Delegated grants and hosted compatibility remain untested.")
            return 0
        token_dir = args.tokens_dir or args.config.parent
        if args.command == "login":
            from azure.core.exceptions import ClientAuthenticationError
            from azure.identity import InteractiveBrowserCredential

            credential = InteractiveBrowserCredential(
                tenant_id=config.tenant_id,
                client_id=config.browser_client_id,
                redirect_uri="http://localhost:8400",
            )
            try:
                token = credential.get_token(
                    f"api://{config.blueprint_client_id}/{INPUT_SCOPE}"
                ).token
            except ClientAuthenticationError:
                raise ProbeError("interactive_login_failed_no_token_written") from None
            finally:
                credential.close()
            with http_client(config.timeout_seconds) as http:
                delegated_claims(
                    token,
                    signing_keys(http, config),
                    config,
                    audience=config.blueprint_client_id,
                    scope=INPUT_SCOPE,
                    user_id=config.allowed_user_id
                    if args.case == "allowed"
                    else config.denied_user_id,
                    client_id=config.browser_client_id,
                )
            token_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = token_dir / f"{args.case}.jwt"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(token)
            print(f"{args.case} token written to an owner-only file; token contents suppressed.")
            return 0
        require_private_foundry(config)
        tokens = {name: read_token(token_dir / f"{name}.jwt") for name in ("allowed", "denied")}
        with http_client(config.timeout_seconds) as http:
            result = run_probe(config, tokens, http)
        print(json.dumps(result, indent=2))
        return {"pass": 0, "fail": 1, "inconclusive": 2}[result["foundry_delegation"]]
    except ProbeError as exc:
        print(json.dumps({"foundry_delegation": "inconclusive", "detail": str(exc)}))
        return 2
    except ImportError:
        print(
            json.dumps(
                {"foundry_delegation": "inconclusive", "detail": "probe_dependencies_missing"}
            )
        )
        return 2
    except (httpx.HTTPError, OSError):
        print(
            json.dumps({"foundry_delegation": "inconclusive", "detail": "network_or_file_failure"})
        )
        return 2
    except (TypeError, ValueError):
        print(json.dumps({"foundry_delegation": "inconclusive", "detail": "sdk_contract_mismatch"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
