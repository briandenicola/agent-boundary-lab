"""Owner-run persistent Graph setup for I0; no cluster access or Foundry invocation."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from containment_demo import identity_directory as directory
from containment_demo.identity_probe import Config, ProbeError

ORDER = (
    "browser",
    "browser_principal",
    "blueprint",
    "blueprint_principal",
    "agent",
    "federation",
    "inheritance",
    "incoming_allowed",
    "incoming_denied",
    "foundry_allowed",
    "foundry_denied",
)
GRANTS = ORDER[7:]
READ_FIELDS = {
    "browser": "id,appId,displayName,signInAudience,isFallbackPublicClient,publicClient",
    "browser_principal": "id,appId",
    "blueprint": "id,appId,displayName,signInAudience,api,identifierUris,requiredResourceAccess",
    "blueprint_principal": "id,appId",
    "agent": "id,displayName,agentIdentityBlueprintId",
}


@dataclass(frozen=True, repr=False)
class Inputs:
    tenant_id: str
    allowed_user_id: str
    denied_user_id: str
    foundry_endpoint: str
    agent_name: str
    foundry_audience: str
    foundry_delegated_scope: str
    foundry_api_service_principal_id: str
    aks_oidc_issuer_url: str
    incoming_scope_id: str
    probe_name: str
    namespace: str
    image: str
    sidecar_image: str

    def __post_init__(self) -> None:
        for value in (
            self.tenant_id,
            self.allowed_user_id,
            self.denied_user_id,
            self.foundry_api_service_principal_id,
            self.incoming_scope_id,
        ):
            directory.identity_id(value)
        self.probe_config(
            "00000000-0000-4000-8000-000000000001",
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-4000-8000-000000000003",
        )
        issuer = urlsplit(self.aks_oidc_issuer_url)
        if (
            issuer.scheme != "https"
            or not issuer.hostname
            or not issuer.hostname.endswith(".oic.prod-aks.azure.com")
            or issuer.username
            or issuer.password
            or issuer.port not in (None, 443)
            or issuer.query
            or issuer.fragment
            or not re.fullmatch(r"/[0-9a-f-]{36}/[0-9a-f-]{36}/", issuer.path)
            or issuer.path.split("/")[1] != self.tenant_id
        ):
            raise ProbeError("setup_requires_same_tenant_aks_oidc_issuer")

    def probe_config(self, blueprint: str, browser: str, agent: str) -> Config:
        names = {field.name for field in fields(Config)}
        return Config(
            **{key: value for key, value in asdict(self).items() if key in names},
            blueprint_client_id=blueprint,
            browser_client_id=browser,
            agent_client_id=agent,
        )


def load_inputs(path: Path) -> Inputs:
    if not path.exists():
        raise ProbeError("setup_inputs_missing")
    with os.fdopen(directory.private_open(path)) as source:
        return Inputs(**json.load(source))


def report(verdict: str, detail: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "identity_setup": verdict,
        "foundry_delegation": "not_evaluated",
        "containment": "not_evaluated",
        "i0_complete": False,
    }
    if detail is not None:
        result["detail"] = detail
    return result


def contract(graph: directory.DirectoryAPI) -> dict[str, Any]:
    response = graph.request(
        "GET",
        "servicePrincipals?$filter=servicePrincipalNames/any(n:n eq 'https://ai.azure.com')"
        "&$select=id,appId,servicePrincipalNames,oauth2PermissionScopes",
        200,
    )
    resources = response.get("value")
    if (
        not isinstance(resources, list)
        or len(resources) != 1
        or not isinstance(resources[0], dict)
        or response.get("@odata.nextLink")
    ):
        raise ProbeError("setup_foundry_resource_missing_ambiguous_or_paginated")
    resource = resources[0]
    names = resource.get("servicePrincipalNames")
    scopes = resource.get("oauth2PermissionScopes")
    if (
        not isinstance(names, list)
        or "https://ai.azure.com" not in names
        or not isinstance(scopes, list)
    ):
        raise ProbeError("setup_foundry_contract_response_invalid")
    enabled = [
        {"value": scope["value"], "id": directory.identity_id(scope.get("id"))}
        for scope in scopes
        if isinstance(scope, dict)
        and scope.get("isEnabled") is True
        and isinstance(scope.get("value"), str)
        and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", scope["value"])
    ]
    if not enabled:
        raise ProbeError("setup_foundry_has_no_published_enabled_delegated_scopes")
    return {
        **report("not_evaluated"),
        "foundry_resource_service_principal_id": directory.identity_id(resource.get("id")),
        "foundry_resource_app_id": directory.identity_id(resource.get("appId")),
        "candidate_audiences": names,
        "enabled_delegated_scopes": enabled,
        "note": "Published scopes are not proof of delegated hosted-agent authentication.",
    }


def preflight(graph: directory.DirectoryAPI, inputs: Inputs) -> dict[str, str]:
    resource = graph.request(
        "GET",
        f"servicePrincipals/{inputs.foundry_api_service_principal_id}"
        "?$select=id,appId,servicePrincipalNames,oauth2PermissionScopes",
        200,
    )
    app_id = directory.identity_id(resource.get("appId"))
    names = resource.get("servicePrincipalNames")
    scopes = resource.get("oauth2PermissionScopes")
    if (
        resource.get("id") != inputs.foundry_api_service_principal_id
        or not isinstance(names, list)
        or "https://ai.azure.com" not in names
        or inputs.foundry_audience not in [app_id, *names]
        or not isinstance(scopes, list)
    ):
        raise ProbeError("setup_foundry_resource_or_audience_not_verified")
    matching = [
        scope
        for scope in scopes
        if isinstance(scope, dict)
        and scope.get("value") == inputs.foundry_delegated_scope
        and scope.get("isEnabled") is True
    ]
    if len(matching) != 1:
        raise ProbeError("setup_foundry_delegated_scope_not_published")
    return {"app_id": app_id, "scope_id": directory.identity_id(matching[0].get("id"))}


def client_id(journal: dict[str, Any], key: str) -> str:
    return directory.identity_id(journal["resources"][key].get("app_id"))


def specification(journal: dict[str, Any], inputs: Inputs, key: str) -> tuple[str, dict[str, Any]]:
    resources = journal["resources"]
    name = inputs.probe_name
    if key == "browser":
        return "applications", {
            "displayName": f"{name}-browser",
            "signInAudience": "AzureADMyOrg",
            "isFallbackPublicClient": True,
            "publicClient": {"redirectUris": ["http://localhost:8400"]},
        }
    if key == "browser_principal":
        return "servicePrincipals", {"appId": client_id(journal, "browser")}
    if key == "blueprint":
        return directory.collection("blueprint"), {
            "displayName": f"{name}-blueprint",
            "signInAudience": "AzureADMyOrg",
            "sponsors@odata.bind": [f"{directory.GRAPH}/users/{journal['operator_id']}"],
            "api": {
                "requestedAccessTokenVersion": 2,
                "oauth2PermissionScopes": [
                    {
                        "id": inputs.incoming_scope_id,
                        "value": "access_as_user",
                        "type": "Admin",
                        "isEnabled": True,
                        "adminConsentDisplayName": "Invoke the private identity probe",
                        "adminConsentDescription": "Authorize the two synthetic probe users.",
                    }
                ],
            },
            "requiredResourceAccess": [
                {
                    "resourceAppId": journal["foundry"]["app_id"],
                    "resourceAccess": [{"id": journal["foundry"]["scope_id"], "type": "Scope"}],
                }
            ],
        }
    if key == "blueprint_principal":
        return directory.collection("principal"), {"appId": client_id(journal, "blueprint")}
    if key == "agent":
        return directory.collection("agent"), {
            "displayName": f"{name}-agent",
            "agentIdentityBlueprintId": client_id(journal, "blueprint"),
            "sponsors@odata.bind": [f"{directory.GRAPH}/users/{journal['operator_id']}"],
        }
    blueprint_id = resources["blueprint"]["id"]
    if key == "federation":
        return f"applications/{blueprint_id}/federatedIdentityCredentials", {
            "name": f"{name}-aks",
            "issuer": inputs.aks_oidc_issuer_url,
            "subject": f"system:serviceaccount:{inputs.namespace}:{name}",
            "audiences": ["api://AzureADTokenExchange"],
        }
    if key == "inheritance":
        # This navigation URL is the documented inheritable-permissions contract.
        return (
            f"applications/microsoft.graph.agentIdentityBlueprint/{blueprint_id}/inheritablePermissions",
            {
                "resourceAppId": journal["foundry"]["app_id"],
                "inheritableScopes": {
                    "@odata.type": "#microsoft.graph.allAllowedScopes",
                    "kind": "allAllowed",
                },
                "inheritableRoles": {"@odata.type": "#microsoft.graph.noRoles", "kind": "none"},
            },
        )
    user = inputs.allowed_user_id if key.endswith("_allowed") else inputs.denied_user_id
    incoming = key.startswith("incoming_")
    return "oauth2PermissionGrants", {
        "clientId": resources["browser_principal" if incoming else "blueprint_principal"]["id"],
        "resourceId": resources["blueprint_principal"]["id"]
        if incoming
        else inputs.foundry_api_service_principal_id,
        "consentType": "Principal",
        "principalId": user,
        "scope": "access_as_user" if incoming else inputs.foundry_delegated_scope,
    }


def instance(journal: dict[str, Any], inputs: Inputs, key: str) -> str:
    object_id = journal["resources"][key]["id"]
    if key in ("browser", "browser_principal"):
        return f"{'applications' if key == 'browser' else 'servicePrincipals'}/{object_id}"
    typed = {"blueprint": "blueprint", "blueprint_principal": "principal", "agent": "agent"}
    if key in typed:
        return directory.instance(typed[key], object_id)
    return f"{specification(journal, inputs, key)[0]}/{object_id}"


def contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            contains(actual.get(key), value)
            for key, value in expected.items()
            if key != "@odata.type" and not key.endswith("@odata.bind")
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(contains(item, desired) for item, desired in zip(actual, expected, strict=True))
        )
    return type(actual) is type(expected) and actual == expected


def verify(
    graph: directory.DirectoryAPI,
    journal: dict[str, Any],
    inputs: Inputs,
    key: str,
    *,
    missing_ok: bool = False,
) -> dict[str, Any] | None:
    path = instance(journal, inputs, key)
    if key in READ_FIELDS:
        path += f"?$select={READ_FIELDS[key]}"
    try:
        payload = graph.request("GET", path, 200)
    except directory.GraphError as exc:
        if missing_ok and exc.status == 404:
            return None
        raise
    resource = journal["resources"][key]
    if (
        payload.get("resourceAppId" if key == "inheritance" else "id") != resource["id"]
        or not contains(payload, specification(journal, inputs, key)[1])
        or ("app_id" in resource and payload.get("appId") != resource["app_id"])
    ):
        raise ProbeError("setup_object_ownership_or_configuration_mismatch")
    return payload


def load(path: Path, inputs: Inputs, settings: directory.Settings) -> dict[str, Any]:
    if not path.exists():
        raise ProbeError("setup_journal_missing")
    with os.fdopen(directory.private_open(path)) as source:
        journal = json.load(source)
    if (
        not isinstance(journal, dict)
        or journal.get("version") != 1
        or journal.get("inputs") != asdict(inputs)
        or journal.get("graph_client_id") != settings.client_id
        or journal.get("operator_id") != settings.sponsor_user_id
        or journal.get("pending") not in (None, *ORDER)
        or type(journal.get("complete")) is not bool
        or not isinstance(journal.get("resources"), dict)
        or list(journal["resources"]) != list(ORDER[: len(journal["resources"])])
    ):
        raise ProbeError("setup_journal_context_or_schema_invalid")
    if journal.get("foundry") is None:
        if journal["resources"] or journal["pending"] is not None or journal["complete"]:
            raise ProbeError("setup_journal_resource_without_verified_foundry_contract")
    else:
        directory.identity_id(journal["foundry"]["app_id"])
        directory.identity_id(journal["foundry"]["scope_id"])
    for key, resource in journal["resources"].items():
        if not isinstance(resource, dict) or type(resource.get("deleted")) is not bool:
            raise ProbeError("setup_journal_resource_invalid")
        if key in GRANTS:
            if not isinstance(resource.get("id"), str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,512}", resource["id"]
            ):
                raise ProbeError("setup_grant_id_invalid")
        else:
            directory.identity_id(resource.get("id"))
        if "app_id" in resource:
            directory.identity_id(resource["app_id"])
    return journal


def configure(path: Path, journal: dict[str, Any], inputs: Inputs) -> None:
    if (
        not journal["complete"]
        or journal["pending"] is not None
        or list(journal["resources"]) != list(ORDER)
        or any(resource["deleted"] for resource in journal["resources"].values())
    ):
        raise ProbeError("setup_incomplete_cannot_export_probe_configuration")
    config = inputs.probe_config(
        client_id(journal, "blueprint"),
        client_id(journal, "browser"),
        journal["resources"]["agent"]["id"],
    )
    directory.save(path, asdict(config))


def run(
    graph: directory.DirectoryAPI,
    path: Path,
    inputs: Inputs,
    settings: directory.Settings,
) -> dict[str, Any]:
    if path.exists():
        raise ProbeError("setup_journal_exists_review_or_cleanup_before_new_setup")
    journal: dict[str, Any] = {
        "version": 1,
        "inputs": asdict(inputs),
        "operator_id": settings.sponsor_user_id,
        "graph_client_id": settings.client_id,
        "foundry": None,
        "pending": None,
        "complete": False,
        "resources": {},
    }
    directory.save(path, journal)
    journal["foundry"] = preflight(graph, inputs)
    directory.save(path, journal)
    for key in ORDER:
        collection, body = specification(journal, inputs, key)
        journal["pending"] = key
        directory.save(path, journal)
        try:
            payload = graph.request("POST", collection, (200, 201) if key in GRANTS else 201, body)
        except directory.GraphError as exc:
            if 400 <= exc.status < 500 and exc.status != 408:
                journal["pending"] = None
                directory.save(path, journal)
            raise
        object_id = payload.get("resourceAppId" if key == "inheritance" else "id")
        if key in GRANTS:
            if not isinstance(object_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,512}", object_id
            ):
                raise ProbeError("setup_grant_id_invalid")
        else:
            directory.identity_id(object_id)
        journal["resources"][key] = {"id": object_id, "deleted": False}
        journal["pending"] = None
        directory.save(path, journal)
        observed = verify(graph, journal, inputs, key)
        if key in ("browser", "blueprint") and observed is not None:
            journal["resources"][key]["app_id"] = directory.identity_id(observed.get("appId"))
            directory.save(path, journal)
        if key == "blueprint":
            audience = {"identifierUris": [f"api://{client_id(journal, 'blueprint')}"]}
            graph.request("PATCH", instance(journal, inputs, key), 204, audience)
            observed = verify(graph, journal, inputs, key)
            if not contains(observed, audience):
                raise ProbeError("setup_blueprint_audience_update_not_observed")
    journal["complete"] = True
    directory.save(path, journal)
    return report("configured")


def cleanup(
    graph: directory.DirectoryAPI,
    path: Path,
    journal: dict[str, Any],
    inputs: Inputs,
) -> None:
    if journal["pending"] is not None:
        raise ProbeError("setup_create_outcome_unknown_manual_reconciliation_required")
    for key in reversed(ORDER):
        if key in journal["resources"] and not journal["resources"][key]["deleted"]:
            verify(graph, journal, inputs, key, missing_ok=True)
    for key in reversed(ORDER):
        if key not in journal["resources"] or journal["resources"][key]["deleted"]:
            continue
        try:
            graph.request("DELETE", instance(journal, inputs, key), 204)
        except directory.GraphError as exc:
            if exc.status != 404:
                raise
        if verify(graph, journal, inputs, key, missing_ok=True) is not None:
            raise ProbeError("setup_deletion_not_observed")
        journal["resources"][key]["deleted"] = True
        journal["complete"] = False
        directory.save(path, journal)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "cleanup", "configure", "contract"))
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--state", type=Path, default=Path(".identity-probe/setup-state.json"))
    parser.add_argument("--output", type=Path, default=Path(".identity-probe/config.json"))
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    for logger in ("azure", "msal", "httpx", "httpcore"):
        logging.getLogger(logger).setLevel(logging.ERROR)
    try:
        if not args.approve:
            raise ProbeError("setup_requires_explicit_approval")
        if args.command == "contract":
            print(json.dumps(contract(directory.StdioGraph(sys.stdin, sys.stdout))))
            return 0
        if args.inputs is None:
            raise ProbeError("setup_inputs_required")
        inputs = load_inputs(args.inputs)
        settings = directory.Settings(
            inputs.tenant_id,
            os.environ.get("IDENTITY_GRAPH_CLIENT_ID", ""),
            os.environ.get("IDENTITY_SPONSOR_USER_ID", ""),
        )
        if os.environ.get("IDENTITY_TENANT_ID") != inputs.tenant_id:
            raise ProbeError("setup_selected_tenant_mismatch")
        with directory.journal_lock(args.state):
            graph = directory.StdioGraph(sys.stdin, sys.stdout)
            if args.command == "run":
                result = run(graph, args.state, inputs, settings)
                journal = load(args.state, inputs, settings)
                configure(args.output, journal, inputs)
            else:
                journal = load(args.state, inputs, settings)
                if args.command == "cleanup":
                    cleanup(graph, args.state, journal, inputs)
                    result = report("cleaned_up")
                else:
                    configure(args.output, journal, inputs)
                    result = report("configured")
        print(json.dumps(result))
        return 0
    except ProbeError as exc:
        result = report("inconclusive", str(exc))
    except (OSError, ValueError, TypeError, KeyError):
        result = report("inconclusive", "setup_private_file_or_configuration_invalid")
    print(json.dumps(result))
    return 2


if __name__ == "__main__":
    sys.exit(main())
