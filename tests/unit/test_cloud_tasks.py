"""Offline guards for cloud bootstrap, image preflight, and account write ordering."""

from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "tasks"
INFRA = ROOT / "infra/cloud"


def task_body(file: str, name: str) -> str:
    content = (TASKS / file).read_text()
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:|\Z)", content)
    assert match, name
    return match[1]


def shell_body(name: str, file: str = "Taskfile.arm.yml") -> str:
    body = task_body(file, name)
    match = re.search(r"(?m)^      - \|\n((?:        .*\n|[ \t]*\n)*)", body)
    assert match
    return textwrap.dedent(match[1])


def run_guard(
    tmp_path: Path,
    script: str,
    *,
    tag: str = "",
    missing: str = "",
    invalid: bool = False,
    state: str = "azapi_resource.managed_network",
    terraform_failure: bool = False,
    state_json: str = "",
    roles_json: str = "[]",
    principal_id: str = "foundry-identity",
    cli_failure: bool = False,
    import_failure: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    cloud_dir = tmp_path / "project with spaces/infra/cloud"
    cloud_dir.mkdir(parents=True)
    project_dir = cloud_dir.parents[1]
    log = tmp_path / "calls"
    terraform = tmp_path / "terraform"
    terraform.write_text(
        '#!/bin/sh\nprintf "terraform %s\\n" "$*" >> "$CALL_LOG"\n'
        'if [ "$1" != "-chdir=$EXPECTED_CLOUD_DIR" ] || [ ! -d "$EXPECTED_CLOUD_DIR" ]; then\n'
        '  echo "wrong Terraform directory" >&2; exit 1\n'
        "fi\n"
        'if [ "$TERRAFORM_FAILURE" = 1 ]; then echo "state read failed" >&2; exit 1; fi\n'
        'case "$*" in\n'
        '  *"output -raw acr_name") echo testregistry ;;\n'
        '  *"state list") printf "%s\\n" "$TEST_STATE" ;;\n'
        '  *"show -json") printf "%s\\n" "$TEST_STATE_JSON" ;;\n'
        '  *" import "*)\n'
        '    if [ "$IMPORT_FAILURE" = 1 ]; then echo "import failed" >&2; exit 1; fi ;;\n'
        '  *) echo "unexpected Terraform command" >&2; exit 1 ;;\n'
        "esac\n"
    )
    cli = tmp_path / "az"
    cli.write_text(
        '#!/bin/sh\nprintf "registry %s\\n" "$*" >> "$CALL_LOG"\n'
        'if [ "$CLI_FAILURE" = 1 ]; then echo "Azure read failed" >&2; exit 1; fi\n'
        'case "$*" in\n'
        '  "resource show "*) printf "%s\\n" "$TEST_PRINCIPAL"; exit 0 ;;\n'
        '  "role assignment list "*) printf "%s\\n" "$TEST_ROLES_JSON"; exit 0 ;;\n'
        "esac\n"
        'case "$*" in\n'
        '  *"$MISSING_IMAGE"*)\n'
        '    if [ -n "$MISSING_IMAGE" ]; then echo MANIFEST_UNKNOWN >&2; exit 1; fi ;;\n'
        "esac\n"
        'if [ "$INVALID_DIGEST" = 1 ]; then echo chatter; exit 0; fi\n'
        'printf "upgrade chatter\\nsha256:%064d\\n" 0\n'
    )
    terraform.chmod(0o755)
    cli.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CALL_LOG": str(log),
        "CLOUD_DIR": "wrong/inherited/path",
        "EXPECTED_CLOUD_DIR": str(cloud_dir),
        "ENDPOINT_IMAGE_TAG": tag,
        "MISSING_IMAGE": missing,
        "INVALID_DIGEST": str(int(invalid)),
        "TEST_STATE": state,
        "TERRAFORM_FAILURE": str(int(terraform_failure)),
        "TEST_STATE_JSON": state_json,
        "TEST_ROLES_JSON": roles_json,
        "TEST_PRINCIPAL": principal_id,
        "CLI_FAILURE": str(int(cli_failure)),
        "IMPORT_FAILURE": str(int(import_failure)),
    }
    result = subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", script.replace("{{.ROOT_DIR}}", str(project_dir))],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, log.read_text() if log.exists() else ""


def image_script() -> str:
    return shell_body("_endpoint-images").replace("{{.TAG}}", "${ENDPOINT_IMAGE_TAG:-}")


@pytest.mark.parametrize(
    ("tenant", "subscription", "state", "cli_failure", "passes"),
    [
        ("tenant", "subscription", "Enabled", False, True),
        ("other", "subscription", "Enabled", False, False),
        ("tenant", "other", "Enabled", False, False),
        ("tenant", "subscription", "Disabled", False, False),
        ("tenant", "subscription", "Enabled", True, False),
    ],
)
def test_deployment_target_check_is_read_only_and_fail_closed(
    tmp_path: Path,
    tenant: str,
    subscription: str,
    state: str,
    cli_failure: bool,
    passes: bool,
) -> None:
    cli = tmp_path / "az"
    cli.write_text(
        '#!/bin/sh\n[ "$*" = "account show -o json --only-show-errors" ] || exit 9\n'
        'if [ "$MOCK_FAIL" = true ]; then exit 1; fi\nprintf "%s\\n" "$MOCK_ACCOUNT"\n'
    )
    cli.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "ARM_TENANT_ID": "tenant",
        "ARM_SUBSCRIPTION_ID": "subscription",
        "MOCK_FAIL": str(cli_failure).lower(),
        "MOCK_ACCOUNT": json.dumps({"tenantId": tenant, "id": subscription, "state": state}),
    }
    script = shell_body("target-check", "Taskfile.cloud.yml")
    result = subprocess.run(  # noqa: S603 - fixed shell, repository script and fake CLI
        ["/bin/sh", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is passes, result.stdout + result.stderr
    if passes:
        tampered = script.replace(".tenantId == $tenant and .id == $subscription", "true")
        environment["MOCK_ACCOUNT"] = json.dumps(
            {"tenantId": "other", "id": "other", "state": "Enabled"}
        )
        intact = subprocess.run(  # noqa: S603
            ["/bin/sh", "-c", script], env=environment, capture_output=True, check=False
        )
        broken = subprocess.run(  # noqa: S603
            ["/bin/sh", "-c", tampered], env=environment, capture_output=True, check=False
        )
        assert intact.returncode != 0
        assert broken.returncode == 0


@pytest.mark.parametrize("name", ["plan", "bootstrap", "up"])
def test_target_check_precedes_any_terraform_work(name: str) -> None:
    body = task_body("Taskfile.cloud.yml", name)
    assert body.index("- task: target-check") < body.index("- task: _init-once")


def test_empty_tag_checks_no_registry_and_does_not_apply(tmp_path: Path) -> None:
    result, calls = run_guard(tmp_path, image_script())
    assert result.returncode == 0
    assert "placeholders" in result.stdout
    assert calls == ""


def test_both_images_must_resolve_in_the_state_registry(tmp_path: Path) -> None:
    result, calls = run_guard(tmp_path, image_script(), tag="5f24f8e")
    assert result.returncode == 0, result.stderr
    for repository in ("containment-demo-policy-api", "containment-demo-test-receiver"):
        assert f"--name testregistry --image {repository}:5f24f8e" in calls
    assert "apply" not in calls


@pytest.mark.parametrize("repository", ["policy-api", "test-receiver"])
def test_either_missing_image_stops_the_guard(tmp_path: Path, repository: str) -> None:
    result, calls = run_guard(
        tmp_path, image_script(), tag="5f24f8e", missing=f"containment-demo-{repository}"
    )
    assert result.returncode != 0
    assert "MANIFEST_UNKNOWN" in result.stderr
    assert "IMAGE_TAG=5f24f8e task build:tool-apis" in result.stderr
    assert "apply" not in calls


def test_invalid_digest_is_not_success(tmp_path: Path) -> None:
    result, _ = run_guard(tmp_path, image_script(), tag="5f24f8e", invalid=True)
    assert result.returncode != 0
    assert "Invalid digest" in result.stderr


def test_failed_state_read_is_not_a_bootstrap_fallback(tmp_path: Path) -> None:
    result, calls = run_guard(tmp_path, image_script(), tag="5f24f8e", terraform_failure=True)
    assert result.returncode != 0
    assert "state read failed" in result.stderr
    assert "Cannot read the target ACR" in result.stderr
    assert "registry" not in calls


@pytest.mark.parametrize(
    ("state", "passes"),
    [
        ("azapi_resource.managed_network", True),
        ("azapi_resource.foundry", False),
        ("azapi_resource.managed_network_other", False),
    ],
)
def test_managed_network_requires_exact_state_address(
    tmp_path: Path, state: str, passes: bool
) -> None:
    result, _ = run_guard(tmp_path, shell_body("_managed-network-imported"), state=state)
    assert (result.returncode == 0) is passes
    if not passes:
        assert "task cloud:network-import" in result.stderr


def test_network_state_read_failure_stops_before_apply(tmp_path: Path) -> None:
    result, _ = run_guard(tmp_path, shell_body("_managed-network-imported"), terraform_failure=True)
    assert result.returncode != 0
    assert "Cannot read Terraform state" in result.stderr


@pytest.mark.parametrize("name", ["_endpoint-images", "_managed-network-imported"])
def test_guards_use_root_path_and_detect_relative_path_regression(
    tmp_path: Path, name: str
) -> None:
    script = shell_body(name).replace("{{.TAG}}", "${ENDPOINT_IMAGE_TAG:-}")
    result, calls = run_guard(tmp_path / "intact", script, tag="5f24f8e")
    assert result.returncode == 0, result.stderr
    assert f"-chdir={tmp_path}/intact/project with spaces/infra/cloud" in calls

    broken = script.replace("{{.ROOT_DIR}}/infra/cloud", "./${CLOUD_DIR}")
    result, _ = run_guard(tmp_path / "tampered", broken, tag="5f24f8e")
    assert result.returncode != 0
    assert "wrong Terraform directory" in result.stderr


@pytest.mark.parametrize(
    ("file", "name", "tag"),
    [
        ("Taskfile.cloud.yml", "up", "${ENDPOINT_IMAGE_TAG:-}"),
        ("Taskfile.deploy.yml", "tool-apis", "${IMAGE_TAG:-latest}"),
    ],
)
def test_full_apply_checks_images_and_network_before_applying(
    file: str, name: str, tag: str
) -> None:
    body = task_body(file, name)
    apply_command = re.search(r"(?m)^ *(?:- )?terraform\b[^\n]*\bapply\b", body)
    assert apply_command, body
    assert body.index("arm:_endpoint-images") < apply_command.start()
    assert body.index("arm:_managed-network-imported") < apply_command.start()
    assert f"TAG: '{tag}'" in body


def test_bootstrap_and_import_are_explicit_and_state_scoped() -> None:
    bootstrap = task_body("Taskfile.cloud.yml", "bootstrap")
    assert "prompt:" in bootstrap
    assert "-target=azapi_resource.foundry" in bootstrap
    assert bootstrap.index(" apply ") < bootstrap.index("- task: network-import")
    recovery = task_body("Taskfile.cloud.yml", "network-import")
    assert "prompt:" in recovery
    assert "show -json" in recovery
    assert '.address == "azapi_resource.foundry"' in recovery
    assert "/managednetworks/default?api-version=2025-10-01-preview" in recovery
    assert recovery.index("already in Terraform state") < recovery.index(" import ")
    assert " apply " not in recovery
    assert "arm:_account-id" not in recovery


def test_all_foundry_children_share_account_locks_and_narrow_retries() -> None:
    for file in INFRA.glob("*.tf"):
        for match in re.finditer(
            r'(?ms)^resource "azapi_resource" "(\w+)" \{.*?^\}', file.read_text()
        ):
            name, body = match[1], match[0]
            if name == "foundry":
                continue
            assert "locks" in body and "[azapi_resource.foundry.id]" in body, name
            assert "retry" in body and "local.foundry_operation_retry" in body, name
    foundry = (INFRA / "foundry.tf").read_text()
    patterns = re.findall(r'"(\(\?i\)[^"]+|TransientError)"', foundry)
    for error in (
        "Another operation is in progress on the resource",
        "an ongoing operation",
        "TransientError",
    ):
        assert any(re.search(pattern, error) for pattern in patterns)
    for error in ("AuthorizationFailed", "InvalidResource", "Resource already exists"):
        assert not any(re.search(pattern, error) for pattern in patterns)
    assert "depends_on = [azurerm_cognitive_deployment.chat]" in foundry
    assert "depends_on = [azapi_resource.project]" in (INFRA / "managed-network.tf").read_text()


def assert_managed_acr_path(source: str) -> None:
    blocks = {
        match[1]: match[0]
        for match in re.finditer(r'(?ms)^resource "[^"]+" "(\w+)" \{.*?^\}', source)
    }
    approver = blocks["foundry_acr_network_approver"]
    assert 'role_definition_name = "Azure AI Enterprise Network Connection Approver"' in approver
    assert "scope                = azurerm_container_registry.main.id" in approver
    reader = blocks["foundry_acr_network_reader"]
    assert 'role_definition_name = "Reader"' in reader
    assert "scope                = azurerm_resource_group.this.id" in reader
    for grant in (approver, reader):
        assert "principal_id         = azapi_resource.foundry.output.identity.principalId" in grant
    endpoint = blocks["foundry_acr_pe_rule"]
    assert 'name                      = "acr-pe"' in endpoint
    assert "parent_id                 = azapi_resource.managed_network.id" in endpoint
    assert 'type     = "PrivateEndpoint"' in endpoint
    assert "serviceResourceId = azurerm_container_registry.main.id" in endpoint
    assert 'subresourceTarget = "registry"' in endpoint
    dependencies = re.search(r"depends_on = \[(.*?)\]", endpoint, re.S)
    assert dependencies
    for name in ("foundry_acr_network_approver", "foundry_acr_network_reader"):
        assert f"azurerm_role_assignment.{name}" in dependencies[1]
    assert "local.foundry_operation_retry" in endpoint
    assert (
        "Foundry account managed identity don't have required permissions "
        "to read and approve private endpoint connections"
    ) in endpoint


def test_managed_acr_endpoint_has_both_approval_prerequisites() -> None:
    assert_managed_acr_path((INFRA / "managed-network.tf").read_text())


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ("    azurerm_role_assignment.foundry_acr_network_approver,\n", ""),
        ("    azurerm_role_assignment.foundry_acr_network_reader,\n", ""),
        ("azapi_resource.foundry.output.identity.principalId", "project-identity"),
        ('subresourceTarget = "registry"', 'subresourceTarget = "account"'),
        ("serviceResourceId = azurerm_container_registry.main.id", "serviceResourceId = wrong.id"),
    ],
)
def test_managed_acr_guard_detects_missing_or_wrong_prerequisite(
    original: str, replacement: str
) -> None:
    source = (INFRA / "managed-network.tf").read_text()
    assert original in source
    with pytest.raises(AssertionError):
        assert_managed_acr_path(source.replace(original, replacement))


@pytest.mark.parametrize("name", ["network-plan", "network-up"])
def test_network_tasks_include_both_managed_private_endpoints(name: str) -> None:
    body = task_body("Taskfile.cloud.yml", name)
    for resource in ("foundry_self_pe_rule", "foundry_acr_pe_rule"):
        assert f"-target=azapi_resource.{resource}" in body


def acr_import_inputs() -> tuple[str, list[dict[str, str]]]:
    group = "/subscriptions/test/resourceGroups/demo"
    account = f"{group}/providers/Microsoft.CognitiveServices/accounts/foundry"
    registry = f"{group}/providers/Microsoft.ContainerRegistry/registries/registry"
    state = {
        "values": {
            "root_module": {
                "resources": [
                    {"address": address, "values": {"id": resource_id}}
                    for address, resource_id in (
                        ("azapi_resource.foundry", account),
                        ("azurerm_container_registry.main", registry),
                        ("azurerm_resource_group.this", group),
                    )
                ]
            }
        }
    }
    roles = [
        {
            "id": f"{scope}/providers/Microsoft.Authorization/roleAssignments/{name}",
            "scope": scope,
            "principalId": "foundry-identity",
            "roleDefinitionName": role,
        }
        for scope, name, role in (
            (registry, "approver", "Azure AI Enterprise Network Connection Approver"),
            (group, "reader", "Reader"),
        )
    ]
    return json.dumps(state), roles


def test_acr_recovery_imports_all_three_resources_from_state(tmp_path: Path) -> None:
    state, roles = acr_import_inputs()
    script = shell_body("acr-network-import", "Taskfile.cloud.yml")
    result, calls = run_guard(tmp_path, script, state_json=state, roles_json=json.dumps(roles))
    assert result.returncode == 0, result.stderr
    assert calls.count(" import ") == 3
    for name in ("approver", "reader"):
        assert f"azurerm_role_assignment.foundry_acr_network_{name}" in calls
        assert roles[0 if name == "approver" else 1]["id"] in calls
    assert "azapi_resource.foundry_acr_pe_rule" in calls
    assert "/foundry/managednetworks/default/outboundrules/acr-pe?api-version=" in calls
    assert " apply " not in calls
    assert " create " not in calls
    assert " put " not in calls


def test_acr_recovery_skips_resources_already_in_state(tmp_path: Path) -> None:
    script = shell_body("acr-network-import", "Taskfile.cloud.yml")
    resources = "\n".join(
        (
            "azapi_resource.foundry_acr_pe_rule",
            "azurerm_role_assignment.foundry_acr_network_approver",
            "azurerm_role_assignment.foundry_acr_network_reader",
        )
    )
    result, calls = run_guard(tmp_path, script, state=resources)
    assert result.returncode == 0, result.stderr
    assert "already in state" in result.stdout
    assert " import " not in calls
    assert "registry " not in calls


def test_acr_recovery_can_resume_after_a_partial_import(tmp_path: Path) -> None:
    state, roles = acr_import_inputs()
    result, calls = run_guard(
        tmp_path,
        shell_body("acr-network-import", "Taskfile.cloud.yml"),
        state="azurerm_role_assignment.foundry_acr_network_approver",
        state_json=state,
        roles_json=json.dumps(roles),
    )
    assert result.returncode == 0, result.stderr
    assert calls.count(" import ") == 2
    assert roles[0]["id"] not in calls
    assert roles[1]["id"] in calls


def test_acr_recovery_rejects_missing_state_resources(tmp_path: Path) -> None:
    state, roles = acr_import_inputs()
    broken = json.loads(state)
    broken["values"]["root_module"]["resources"].pop()
    result, calls = run_guard(
        tmp_path,
        shell_body("acr-network-import", "Taskfile.cloud.yml"),
        state_json=json.dumps(broken),
        roles_json=json.dumps(roles),
    )
    assert result.returncode != 0
    assert "Missing azurerm_resource_group.this resource ID" in result.stderr
    assert " import " not in calls
    assert "registry " not in calls


@pytest.mark.parametrize("problem", ["missing", "wrong_scope", "wrong_principal", "duplicate"])
def test_acr_recovery_rejects_nonunique_or_unrelated_grants(tmp_path: Path, problem: str) -> None:
    state, roles = acr_import_inputs()
    if problem == "missing":
        roles.pop(0)
    elif problem == "wrong_scope":
        roles[0]["scope"] += "-other"
    elif problem == "wrong_principal":
        roles[0]["principalId"] = "project-identity"
    else:
        roles.append({**roles[0], "id": roles[0]["id"] + "-duplicate"})
    result, calls = run_guard(
        tmp_path,
        shell_body("acr-network-import", "Taskfile.cloud.yml"),
        state_json=state,
        roles_json=json.dumps(roles),
    )
    assert result.returncode != 0
    assert "Expected exactly one" in result.stderr
    assert " import " not in calls


@pytest.mark.parametrize("problem", ["state", "identity", "azure", "import"])
def test_acr_recovery_read_and_import_errors_stop_the_task(tmp_path: Path, problem: str) -> None:
    state, roles = acr_import_inputs()
    result, calls = run_guard(
        tmp_path,
        shell_body("acr-network-import", "Taskfile.cloud.yml"),
        state_json=state,
        roles_json=json.dumps(roles),
        principal_id="" if problem == "identity" else "foundry-identity",
        terraform_failure=problem == "state",
        cli_failure=problem == "azure",
        import_failure=problem == "import",
    )
    assert result.returncode != 0
    if problem == "import":
        assert calls.count(" import ") == 1
    else:
        assert " import " not in calls
