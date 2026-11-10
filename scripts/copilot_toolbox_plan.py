"""Offline guard for the separate Copilot project's Terraform plan."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def check_plan(plan: dict[str, Any], *, deleting: bool = False) -> None:
    if (
        not plan.get("format_version")
        or "planned_values" not in plan
        or plan.get("errored")
        or plan.get("deferred_changes")
    ):
        raise ValueError("Incomplete Copilot infrastructure plan")
    root = plan["planned_values"].get("root_module", {})
    states = [
        row["values"]["outputs"]
        for row in root.get("resources", [])
        if row["address"] == "data.terraform_remote_state.cloud"
    ]
    if not states:
        states = [
            row["values"]["outputs"]
            for row in plan.get("prior_state", {})
            .get("values", {})
            .get("root_module", {})
            .get("resources", [])
            if row["address"] == "data.terraform_remote_state.cloud"
        ]
    if len(states) != 1:
        raise ValueError("Missing or ambiguous baseline state in the isolated plan")
    cloud = states[0]
    account = cloud["foundry_account_id"]
    group = account.split("/providers/")[0]
    project = f"{account}/projects/{cloud['resource_name']}-copilot"
    resources = {
        "azapi_resource.project": (
            "Microsoft.CognitiveServices/accounts/projects",
            account,
            cloud["resource_name"] + "-copilot",
        ),
        "azapi_resource.project_host": (
            "Microsoft.CognitiveServices/accounts/projects/capabilityHosts",
            project,
            "agents",
        ),
        "azapi_resource.project_insights": (
            "Microsoft.CognitiveServices/accounts/projects/connections",
            project,
            "copilot-appinsights-connection",
        ),
        "azapi_resource.project_pull": (
            "Microsoft.Authorization/roleAssignments",
            f"{group}/providers/Microsoft.ContainerRegistry/registries/{cloud['acr_name']}",
            None,
        ),
        "azapi_resource.project_deployer": (
            "Microsoft.Authorization/roleAssignments",
            project,
            None,
        ),
        "azapi_resource.mcp": (
            "Microsoft.App/containerApps",
            group,
            cloud["resource_name"][:20] + "-copilot-mcp",
        ),
        "azapi_resource.policy": (
            "Microsoft.CognitiveServices/accounts/raiPolicies",
            account,
            cloud["resource_name"] + "-copilot-toolbox",
        ),
    }
    for change in plan.get("resource_changes", []):
        if change["mode"] == "data":
            continue
        allowed = (["no-op"], ["delete"]) if deleting else (["no-op"], ["create"], ["update"])
        if (
            change["address"] not in resources
            or change["change"]["actions"] not in allowed
            or (
                not deleting
                and change["address"] == "azapi_resource.project_host"
                and change["change"]["actions"] == ["update"]
            )
        ):
            raise ValueError("Plan changes resources outside the dedicated Copilot track")
        for value in (change["change"].get("before"), change["change"].get("after")):
            if value is None:
                continue
            kind, parent, name = resources[change["address"]]
            actual_name = value.get("name")
            if (
                value.get("type", "").split("@")[0] != kind
                or value.get("parent_id") not in (parent, None)
                or (name is not None and actual_name != name)
                or (
                    name is None
                    and actual_name is not None
                    and re.fullmatch(r"[0-9a-f-]{36}", actual_name) is None
                )
            ):
                raise ValueError("Dedicated resource address points outside the isolated scope")
            if value.get("id") is not None:
                suffix = (
                    "/providers/" + kind + "/"
                    if kind
                    in {"Microsoft.Authorization/roleAssignments", "Microsoft.App/containerApps"}
                    else "/" + kind.split("/")[-1] + "/"
                )
                if value["id"] != parent + suffix + str(actual_name):
                    raise ValueError("Dedicated resource ID points outside the isolated scope")


def check_grants(grants: list[dict[str, str]], config: dict[str, Any]) -> None:
    account = config["rai_policy_id"].rsplit("/raiPolicies/", 1)[0]
    project = f"{account}/projects/{config['project_name']}"
    if config["project_id"] != project or len(grants) > 2:
        raise ValueError("Unexpected isolated grant journal")
    targets = {
        "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd": account,
        "eed3b665-ab3a-47b6-8f48-c9382fb1dad6": project,
    }
    for grant in grants:
        scope = targets.get(grant["role"])
        if (
            scope is None
            or grant["scope"] != scope
            or grant["agent"] != config["agent_name"]
            or re.fullmatch(r"[0-9a-fA-F-]{36}", grant["principal"]) is None
            or not grant["id"].startswith(
                scope + "/providers/Microsoft.Authorization/roleAssignments/"
            )
            or re.fullmatch(r"[0-9a-fA-F-]{36}", grant["id"].rsplit("/", 1)[1]) is None
        ):
            raise ValueError("Grant is outside the isolated agent/project")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destroy", action="store_true")
    parser.add_argument("--grants", action="store_true")
    parser.add_argument("--config", type=Path)
    arguments = parser.parse_args()
    if arguments.grants:
        if arguments.config is None:
            parser.error("--grants requires --config")
        check_grants(json.load(sys.stdin), json.loads(arguments.config.read_text()))
    else:
        check_plan(json.load(sys.stdin), deleting=arguments.destroy)
