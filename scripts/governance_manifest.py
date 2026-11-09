"""Render a private AKS publishing helper from existing Terraform outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from typing import Any

from pydantic import ValidationError

from containment_demo.governance.hosted import SCENARIOS, HostedSettings
from containment_demo.settings import Settings


def render(cloud: dict[str, Any], policies: dict[str, str], image: str) -> dict[str, Any]:
    env = {
        "DEMO_FOUNDRY_ACCOUNT_NAME": cloud["foundry_account_name"],
        "DEMO_FOUNDRY_PROJECT_NAME": cloud["project_name"],
        "DEMO_AGENT_NAME_AUDIT": cloud["agent_name_audit"],
        "DEMO_AGENT_NAME_ENFORCED": cloud["agent_name_enforced"],
        "DEMO_RAI_POLICY_AUDIT_ID": cloud["rai_policy_audit_id"],
        "DEMO_RAI_POLICY_ENFORCED_ID": cloud["rai_policy_enforced_id"],
        "DEMO_GOVERNANCE_ALL_POLICY_ID": policies["all"],
        "DEMO_GOVERNANCE_NETWORK_POLICY_ID": policies["network"],
        "DEMO_GOVERNANCE_AUDIT_POLICY_ID": policies["audit"],
        "DEMO_AGENT_IMAGE": image,
        "DEMO_DEPLOY_REQUEST_TIMEOUT_SECONDS": "60",
        "DEMO_DEPLOY_RETRY_TOTAL": "0",
        "DEMO_POLICY_API_URL": cloud["policy_api_url"],
        "DEMO_TEST_RECEIVER_URL": cloud["test_receiver_url"],
        "DEMO_MODEL_DEPLOYMENT": cloud["model_deployment_name"],
        "DEMO_AZURE_OPENAI_ENDPOINT": cloud["foundry_endpoint"],
        "DEMO_DIAGNOSTICS_ENABLED": "true",
        "DEMO_DIAGNOSTICS_TOKEN": cloud["diagnostics_token"],
        "DEMO_GOVERNANCE_MODE": "disabled",
        "DEMO_APPLICATION_INSIGHTS_CONNECTION_STRING": cloud[
            "application_insights_connection_string"
        ],
        "DEMO_GOVERNANCE_WORKSPACE_ID": cloud["log_analytics_workspace_id"],
        "DEMO_POLICY_API_APP_NAME": cloud["policy_api_app_name"],
        "DEMO_TEST_RECEIVER_APP_NAME": cloud["test_receiver_app_name"],
    }
    # Validate without using the operator's .env or printing secret values on errors.
    HostedSettings.model_validate(
        {key.removeprefix("DEMO_").lower(): value for key, value in env.items()}
    )
    Settings.model_validate(
        {key.removeprefix("DEMO_").lower(): value for key, value in env.items()}
    )
    namespace = cloud["kubernetes_namespace"]
    service_account = cloud["agent_deployer_service_account"]
    for value in (namespace, service_account):
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", value) is None:
            raise ValueError("invalid Kubernetes name")
    container_env = [
        {"name": name, "value": value}
        for name, value in env.items()
        if name not in {"DEMO_DIAGNOSTICS_TOKEN", "DEMO_APPLICATION_INSIGHTS_CONNECTION_STRING"}
    ]
    for name in ("DEMO_DIAGNOSTICS_TOKEN", "DEMO_APPLICATION_INSIGHTS_CONNECTION_STRING"):
        container_env.append(
            {
                "name": name,
                "valueFrom": {"secretKeyRef": {"name": "agent-governance-config", "key": name}},
            }
        )
    container = {
        "name": "publisher",
        "image": image,
        "command": ["sleep", "infinity"],
        "env": container_env,
        "resources": {"requests": {"cpu": "100m", "memory": "256Mi"}, "limits": {"memory": "1Gi"}},
        "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "agent-governance", "namespace": namespace},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app.kubernetes.io/name": "agent-governance"}},
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "agent-governance",
                        "azure.workload.identity/use": "true",
                    },
                    "annotations": {
                        "agent-boundary-lab/config-hash": hashlib.sha256(
                            (
                                env["DEMO_DIAGNOSTICS_TOKEN"]
                                + env["DEMO_APPLICATION_INSIGHTS_CONNECTION_STRING"]
                            ).encode()
                        ).hexdigest()
                    },
                },
                "spec": {
                    "serviceAccountName": service_account,
                    "securityContext": {"runAsNonRoot": True},
                    "containers": [container],
                },
            },
        },
    }
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "agent-governance-config", "namespace": namespace},
                "type": "Opaque",
                "stringData": {
                    name: env[name]
                    for name in (
                        "DEMO_DIAGNOSTICS_TOKEN",
                        "DEMO_APPLICATION_INSIGHTS_CONNECTION_STRING",
                    )
                },
            },
            deployment,
        ],
    }


def check_policy_ownership(existing: list[str], owned: list[str]) -> None:
    if not isinstance(existing, list) or not isinstance(owned, list):
        raise ValueError("Policy ownership reads must be JSON arrays")
    for name in (
        "containment-demo-governance-all",
        "containment-demo-governance-network",
        "containment-demo-governance-audit",
    ):
        if name in existing and name not in owned:
            raise ValueError(f"{name} already exists outside this track's Terraform state")


def check_plan(plan: dict[str, Any]) -> None:
    allowed = {f'azapi_resource.policy["{key}"]' for key in ("all", "network", "audit")}
    if (
        not plan.get("format_version")
        or not plan.get("planned_values")
        or plan.get("errored")
        or plan.get("deferred_changes")
    ):
        raise ValueError("Incomplete or failed Terraform policy plan")
    for change in plan.get("resource_changes", []):
        if change["mode"] == "data":
            continue
        if change["address"] not in allowed or change["change"]["actions"] not in (
            ["no-op"],
            ["create"],
            ["update"],
        ):
            raise ValueError("Plan changes resources outside the three dedicated RAI policies")


def check_grants(grants: list[dict[str, str]], scope: str, prefix: str) -> None:
    names = {f"{prefix}-gov-{scenario.name}" for scenario in SCENARIOS}
    if not isinstance(grants, list) or len(grants) > 7:
        raise ValueError("Unexpected model grant journal")
    for grant in grants:
        if (
            grant["scope"] != scope
            or grant["agent_name"] not in names
            or grant["role_definition_id"] != "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
            or re.fullmatch(r"[0-9a-fA-F-]{36}", grant["principal_id"]) is None
            or not grant["id"].startswith(
                f"{scope}/providers/Microsoft.Authorization/roleAssignments/"
            )
            or re.fullmatch(r"[0-9a-fA-F-]{36}", grant["id"].rsplit("/", 1)[1]) is None
        ):
            raise ValueError("Model grant is outside this governance track")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--check-ownership", action="store_true")
    parser.add_argument("--check-plan", action="store_true")
    parser.add_argument("--check-grants", action="store_true")
    parser.add_argument("--scope", default="")
    parser.add_argument("--agent-prefix", default="")
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    try:
        if args.check_plan:
            check_plan(payload)
        elif args.check_grants:
            check_grants(payload, args.scope, args.agent_prefix)
        elif args.check_ownership:
            check_policy_ownership(payload["existing"], payload["owned"])
        else:
            if not args.image:
                parser.error("--image is required for rendering")
            cloud = {name: item["value"] for name, item in payload["cloud"].items()}
            print(json.dumps(render(cloud, payload["policies"], args.image)))
    except ValidationError as exc:
        print(
            "Invalid governance config fields: "
            + ", ".join(str(error["loc"]) for error in exc.errors()),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
