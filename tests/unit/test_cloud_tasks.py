"""Offline guards for cloud bootstrap, image preflight, and account write ordering."""

from __future__ import annotations

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


def shell_body(name: str) -> str:
    body = task_body("Taskfile.arm.yml", name)
    match = re.search(r"(?ms)^      - \|\n(.*)", body)
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
        '  *) echo "unexpected Terraform command" >&2; exit 1 ;;\n'
        "esac\n"
    )
    cli = tmp_path / "az"
    cli.write_text(
        '#!/bin/sh\nprintf "registry %s\\n" "$*" >> "$CALL_LOG"\n'
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
    result, _ = run_guard(
        tmp_path, shell_body("_managed-network-imported"), terraform_failure=True
    )
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
    assert body.index("arm:_endpoint-images") < body.index(" apply ")
    assert body.index("arm:_managed-network-imported") < body.index(" apply ")
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
