"""Offline checks for the public command interface and application-only deployment."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = (
    "foundry-agent",
    "tool-apis",
    "agent-bridge",
    "chat-agent",
    "model-server",
    "test-ui",
)


@pytest.mark.parametrize("action", ["plan", "publish", "status", "disable"])
def test_copilot_runs_through_the_private_helper_without_deploying_or_invoking(
    dry_task, action: str
) -> None:
    command = dry_task(f"copilot:{action}")
    assert "cloud:target-check" in command
    assert "/opt/deploy-venv/bin/python /home/agent/.copilot/publisher.py" in command
    assert f"{action} --metadata" in command
    assert "src/containment_demo/copilot.py" in command
    assert "terraform apply" not in command
    assert "governance.hosted up" not in command
    assert "verify_governance run" not in command
    assert "${COPILOT_METADATA_FILE:-" in command
    assert "/.task/copilot/publish-request.json}" in command
    assert "${COPILOT_METADATA_FILE:?" not in command


def task_body(file: str, name: str) -> str:
    content = (ROOT / "tasks" / file).read_text()
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:|\Z)", content)
    assert match, name
    return match[1]


@pytest.mark.parametrize("action", ["up", "status", "publish-plan", "publish", "disable"])
def test_toolbox_commands_use_isolated_helper_files_and_never_roll_out_baseline(
    dry_task,
    action: str,
) -> None:
    command = dry_task(f"copilot-toolbox:{action}")
    assert "cloud:target-check" in command
    assert "/home/agent/.copilot-toolbox/source" in command
    assert "-m containment_demo.copilot_toolbox" in command
    assert ".task/copilot-toolbox/" in command
    assert "kubectl apply" not in command
    assert "rollout" not in command
    assert "governance.hosted up" not in command
    assert "/home/agent/.copilot/publication.json" not in command
    assert "terraform apply" not in command
    if action in {"publish-plan", "publish"}:
        assert "${COPILOT_TOOLBOX_METADATA_FILE:-" in command
        assert "/.task/copilot-toolbox/publish-request.json}" in command
        assert "${COPILOT_TOOLBOX_METADATA_FILE:?" not in command


def test_acs_lifecycle_separates_infrastructure_build_and_agent_deployment(dry_task) -> None:
    up = dry_task("acs:up")
    assert "cloud:target-check" in up
    assert "-m containment_demo.copilot_toolbox_oauth up" in up
    assert "terraform -chdir=infra/governance apply" in up
    assert "Foundry User is already assigned" in up
    assert "governance.hosted up" not in up
    assert "az acr build" not in up
    assert "terraform -chdir=infra/cloud apply" not in up
    build = dry_task("acs:build")
    assert "containment-demo-governed-agent" in build
    assert "az acr build" in build
    assert "copilot_toolbox_oauth up" not in build
    assert " apply " not in build
    deploy = dry_task("acs:deploy")
    assert "governance.hosted up" in deploy
    assert "az role assignment create" in deploy
    assert "terraform -chdir=infra/governance apply" not in deploy
    assert "az acr build" not in deploy
    assert "microsoft365/publish" not in deploy
    integration = dry_task("acs:copilot")
    assert "ensure --metadata" in integration
    assert ".task/copilot/publish-request.json" in integration
    status = dry_task("acs:report")
    assert "/opt/deploy-venv/bin/python - status" in status
    assert "< src/containment_demo/governance/hosted.py" in status
    assert "-m scripts.acs_report" in status
    assert "governance.hosted up" not in status


def test_toolbox_plan_only_reads_its_recorded_client(dry_task) -> None:
    plan = dry_task("copilot-toolbox:plan")
    assert "-m containment_demo.copilot_toolbox_oauth client-id" in plan
    assert "copilot_toolbox_oauth up" not in plan
    assert "${COPILOT_TOOLBOX_OAUTH_CLIENT_ID:?" not in plan
    down = dry_task("copilot-toolbox:down")
    assert down.index("down.tfplan") < down.index("copilot_toolbox_oauth down")


def test_toolbox_configuration_is_consolidated_and_deployment_reads_verified_outputs(dry_task):
    configure = dry_task("copilot-toolbox:infra-up")
    assert configure.index("copilot_toolbox_oauth up") < configure.index("infra.tfplan")
    assert configure.index("apply -input=false") < configure.index("copilot_toolbox_setup up")
    assert configure.index("apply -input=false") < configure.index("az role assignment create")
    assert configure.index("az role assignment create") < configure.index(
        "copilot_toolbox_setup up"
    )
    assert "/home/agent/.copilot-toolbox/source" in configure
    assert "terraform -chdir=infra/cloud apply" not in configure
    deploy = dry_task("copilot-toolbox:up")
    assert "configuration.json" in deploy
    assert "Set the versioned endpoint" not in deploy
    assert 'select(.phase == "ready")' in deploy
    down = dry_task("copilot-toolbox:down")
    assert down.index("copilot_toolbox_setup down") < down.index("down.tfplan")
    assert down.index("copilot_toolbox_oauth down") < down.index(
        "copilot_toolbox_setup finish-down"
    )


@pytest.mark.parametrize(
    "phase,conflict",
    [
        ("ready", False),
        ("consent_required", False),
        ("ready", True),
    ],
)
def test_toolbox_config_uses_ready_journal_and_rejects_conflicting_exports(
    tmp_path: Path,
    phase: str,
    conflict: bool,
) -> None:
    runner = shutil.which("sh")
    if runner is None or shutil.which("jq") is None:
        pytest.skip("sh and jq are required to exercise configuration")
    directory = tmp_path / ".task/copilot-toolbox"
    directory.mkdir(parents=True)
    endpoint = "https://foundry.example.test/api/projects/isolated/toolboxes/policy/versions/2/mcp"
    (directory / "configuration.json").write_text(
        json.dumps(
            {
                "phase": phase,
                "toolbox_endpoint": endpoint,
                "toolbox_policy_tool": "policy___get_servicing_policy",
            }
        )
    )
    (directory / "agent-digest").write_text("sha256:" + "a" * 64)
    destination = directory / "config.json"
    original = {"preserved": "previous-configuration"}
    destination.write_text(json.dumps(original))
    deployment = {"project_id": "/owned/project", "agent_name": "isolated-agent"}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    terraform = bin_dir / "terraform"
    outputs = {"acr_login_server": "registry.example.test", "deployment": json.dumps(deployment)}
    terraform.write_text(f"#!{sys.executable}\nimport sys\nprint({outputs!r}[sys.argv[-1]])\n")
    terraform.chmod(0o755)
    environment = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    environment.pop("COPILOT_TOOLBOX_ENDPOINT", None)
    environment.pop("COPILOT_TOOLBOX_POLICY_TOOL", None)
    if conflict:
        environment["COPILOT_TOOLBOX_ENDPOINT"] = "https://foreign.example.test/mcp"
    body = task_body("Taskfile.copilot-toolbox.yml", "_config")
    script = body.split("/bin/sh -eu <<'SH'\n", 1)[1].split("\n        SH", 1)[0]
    result = subprocess.run(  # noqa: S603 - execute the repository-owned configuration script
        [runner, "-eu"],
        input=textwrap.dedent(script),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if phase != "ready" or conflict:
        assert result.returncode != 0
        assert json.loads(destination.read_text()) == original
        assert "complete any requested consent" in result.stderr or "conflict" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(destination.read_text()) == {
            **deployment,
            "toolbox_endpoint": endpoint,
            "toolbox_policy_tool": "policy___get_servicing_policy",
            "agent_image": "registry.example.test/containment-demo-copilot-toolbox-agent@sha256:"
            + "a" * 64,
        }
        assert destination.stat().st_mode & 0o777 == 0o600


def test_toolbox_registration_task_runs_idempotently_and_resolves_the_recorded_id(
    tmp_path: Path,
) -> None:
    runner = shutil.which("task")
    if runner is None:
        pytest.skip("Go Task is required to exercise registration")
    shutil.copytree(ROOT / "tasks", tmp_path / "tasks")
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\nsilent: true\nincludes:\n"
        "  copilot-toolbox:\n    taskfile: ./tasks/Taskfile.copilot-toolbox.yml\n"
        "  cloud:\n    taskfile: ./tasks/Taskfile.cloud.yml\n"
        "tasks:\n  up:\n    cmds:\n"
        "      - task: copilot-toolbox:oauth-setup\n"
        "  resolve:\n    cmds:\n"
        "      - .venv/bin/python -m containment_demo.copilot_toolbox_oauth client-id\n"
    )
    (tmp_path / ".venv/bin").mkdir(parents=True)
    python = tmp_path / ".venv/bin/python"
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    prefix = "00000000-0000-4000-8000-"
    tenant, subscription, api, scope, client, object_id = (
        prefix + f"{index:012d}" for index in range(1, 7)
    )
    account = (
        f"/subscriptions/{subscription}/resourceGroups/lab"
        "/providers/Microsoft.CognitiveServices/accounts/foundry"
    )
    scripts = {
        "terraform": f"""
            import sys
            print({{
                "foundry_account_id": {account!r},
                "resource_name": "lab",
                "policy_api_app_name": "baseline-policy",
            }}[sys.argv[-1]])
        """,
        "az": f"""
            import json, sys
            from pathlib import Path
            args = sys.argv[1:]
            store = Path("application.json")
            def emit(value):
                print(json.dumps(value))
            if args[:2] == ["account", "show"]:
                emit({{"tenantId": {tenant!r}, "id": {subscription!r}, "state": "Enabled"}})
            elif args[:2] == ["containerapp", "show"]:
                emit([{{"name": key, "value": value}} for key, value in {{
                    "POLICY_API_AUTH_MODE": "delegated",
                    "POLICY_API_TENANT_ID": {tenant!r},
                    "POLICY_API_AUDIENCE": "api://" + {api!r},
                    "POLICY_API_SCOPE": "Policy.Read",
                    "POLICY_API_CLIENT_IDS": "baseline-client",
                }}.items()])
            elif args[:3] == ["ad", "app", "list"]:
                emit([json.loads(store.read_text())] if store.exists() else [])
            elif args[:3] == ["ad", "app", "show"]:
                target = args[args.index("--id") + 1]
                if target == "api://" + {api!r}:
                    emit({{
                        "appId": {api!r}, "identifierUris": ["api://" + {api!r}],
                        "api": {{"oauth2PermissionScopes": [
                            {{"id": {scope!r}, "value": "Policy.Read", "isEnabled": True}}
                        ]}},
                    }})
                else:
                    assert target == {object_id!r}
                    emit(json.loads(store.read_text()))
            elif args[0] == "rest":
                method = args[args.index("--method") + 1].lower()
                if method == "get":
                    emit({{"value": [{{"properties": {{
                        "provisioningState": "Succeeded", "capabilityHostKind": "Agents"
                    }}}}]}})
                else:
                    assert method == "post"
                    assert not store.exists(), "Duplicate app creation"
                    journal = Path(".task/copilot-toolbox/oauth-application.json")
                    assert journal.stat().st_mode & 0o777 == 0o600
                    assert json.loads(journal.read_text())["phase"] == "create_requested"
                    request = Path(args[args.index("--body") + 1][1:])
                    body = json.loads(request.read_text())
                    assert body["requiredResourceAccess"] == [{{
                        "resourceAppId": {api!r},
                        "resourceAccess": [{{"id": {scope!r}, "type": "Scope"}}],
                    }}]
                    app = {{**body, "id": {object_id!r}, "appId": {client!r}}}
                    store.write_text(json.dumps(app))
                    emit(app)
            else:
                raise AssertionError(args)
        """,
    }
    for name, source in scripts.items():
        path = bin_dir / name
        path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(source))
        path.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "PYTHONPATH": str(ROOT / "src"),
        "ARM_TENANT_ID": tenant,
        "ARM_SUBSCRIPTION_ID": subscription,
    }
    environment.pop("COPILOT_TOOLBOX_OAUTH_CLIENT_ID", None)
    for action in ("up", "up", "resolve"):
        result = subprocess.run(  # noqa: S603
            [runner, action],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        if action == "resolve":
            assert result.stdout.strip() == client
    assert (
        json.loads((tmp_path / ".task/copilot-toolbox/oauth-application.json").read_text())[
            "client_id"
        ]
        == client
    )


@pytest.mark.parametrize(
    ("readback", "create_exit", "principal_count", "success", "writes"),
    [
        ("0", 0, 1, True, 2),
        ("1", 0, 1, True, 0),
        ("", 0, 1, False, 0),
        ("invalid", 0, 1, False, 0),
        ("0", 23, 1, False, 1),
        ("0", 0, 2, False, 0),
    ],
)
def test_toolbox_grants_are_scoped_journaled_before_writes_and_fail_closed(
    tmp_path: Path,
    readback: str,
    create_exit: int,
    principal_count: int,
    success: bool,
    writes: int,
) -> None:
    runner = shutil.which("task")
    if runner is None:
        pytest.skip("Go Task is required to exercise isolated grants")
    shutil.copytree(ROOT / "tasks", tmp_path / "tasks")
    (tmp_path / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/copilot_toolbox_plan.py", tmp_path / "scripts")
    (tmp_path / ".venv/bin").mkdir(parents=True)
    (tmp_path / ".venv/bin/python").symlink_to(sys.executable)
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\nsilent: true\nincludes:\n"
        "  toolbox:\n    taskfile: ./tasks/Taskfile.copilot-toolbox.yml\n"
        "tasks:\n  grant:\n    cmds:\n      - task: toolbox:_grants\n"
    )
    account = (
        "/subscriptions/synthetic/resourceGroups/lab"
        "/providers/Microsoft.CognitiveServices/accounts/foundry"
    )
    directory = tmp_path / ".task/copilot-toolbox"
    directory.mkdir(parents=True)
    (directory / "config.json").write_text(
        json.dumps(
            {
                "project_name": "isolated-copilot",
                "project_id": account + "/projects/isolated-copilot",
                "agent_name": "isolated-agent",
                "rai_policy_id": account + "/raiPolicies/isolated",
            }
        )
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "terraform": f"""
            import sys
            print({{
                "foundry_account_id": {account!r},
                "foundry_account_name": "foundry",
                "project_name": "baseline",
            }}[sys.argv[-1]])
        """,
        "az": """
            import json, os, sys
            from pathlib import Path
            args = sys.argv[1:]
            principal = "00000000-0000-4000-8000-000000000001"
            if args[:3] == ["ad", "sp", "list"]:
                print("\\n".join([principal] * int(os.environ["FAKE_PRINCIPALS"])))
            elif args[:3] == ["role", "assignment", "list"]:
                print(os.environ["FAKE_READBACK"])
            elif args[:3] == ["role", "assignment", "create"]:
                journal = Path(".task/copilot-toolbox/grants.json")
                assert journal.stat().st_mode & 0o777 == 0o600
                scope = args[args.index("--scope") + 1]
                role = args[args.index("--role") + 1]
                name = args[args.index("--name") + 1]
                assignment = scope + "/providers/Microsoft.Authorization/roleAssignments/" + name
                records = json.loads(journal.read_text())
                assert any(row["id"] == assignment and row["principal"] == principal
                           and row["role"] == role and row["agent"] == "isolated-agent"
                           for row in records)
                config = json.loads(Path(".task/copilot-toolbox/config.json").read_text())
                expected = (config["project_id"] if role.startswith("eed3")
                            else config["rai_policy_id"].rsplit("/raiPolicies/", 1)[0])
                assert scope == expected
                with Path("writes").open("a") as log:
                    log.write(assignment + "\\n")
                sys.exit(int(os.environ["FAKE_CREATE_EXIT"]))
            else:
                raise AssertionError(args)
        """,
    }
    for name, source in scripts.items():
        path = bin_dir / name
        path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(source))
        path.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [runner, "grant"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_READBACK": readback,
            "FAKE_CREATE_EXIT": str(create_exit),
            "FAKE_PRINCIPALS": str(principal_count),
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    actual = (tmp_path / "writes").read_text().splitlines() if writes else []
    assert len(actual) == writes
    if not writes:
        assert not (tmp_path / "writes").exists()
    else:
        journal = directory / "grants.json"
        assert len(json.loads(journal.read_text())) == writes
        assert journal.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("login", "have", "list_exit", "state_subscription", "success", "created"),
    [
        ("user", "0", "0", "approved", True, True),
        ("user", "1", "0", "approved", True, False),
        ("servicePrincipal", "0", "0", "approved", False, False),
        ("user", "0", "1", "approved", False, False),
        ("user", "", "0", "approved", False, False),
        ("user", "0", "0", "foreign", False, False),
    ],
)
def test_copilot_access_is_user_only_project_scoped_and_idempotent(
    tmp_path: Path,
    login: str,
    have: str,
    list_exit: str,
    state_subscription: str,
    success: bool,
    created: bool,
) -> None:
    runner = shutil.which("task")
    if runner is None:
        pytest.skip("Go Task is required to exercise the access command")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    shutil.copyfile(ROOT / "tasks/Taskfile.copilot.yml", tasks / "Taskfile.copilot.yml")
    (tasks / "cloud.yml").write_text("version: '3'\ntasks:\n  target-check:\n    cmds: ['true']\n")
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\nsilent: true\nincludes:\n"
        "  copilot:\n    taskfile: ./tasks/Taskfile.copilot.yml\n"
        "  cloud:\n    taskfile: ./tasks/cloud.yml\n"
    )
    account = (
        f"/subscriptions/{state_subscription}/resourceGroups/lab"
        "/providers/Microsoft.CognitiveServices/accounts/foundry"
    )
    scope = f"{account}/projects/project"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "terraform": (
            '#!/bin/sh\ncase "$*" in\n'
            f' *foundry_account_id) echo "{account}" ;;\n'
            " *project_name) echo project ;;\n"
            " *) exit 1 ;;\nesac\n"
        ),
        "az": (
            '#!/bin/sh\ncase "$*" in\n'
            ' "account show "*) printf "%s" "$FAKE_LOGIN" ;;\n'
            ' "ad signed-in-user show "*) echo 00000000-0000-4000-8000-000000000001 ;;\n'
            f' "resource show "*) echo "{scope}" ;;\n'
            ' "role assignment list "*) printf "%s" "$FAKE_HAVE"; exit "$FAKE_LIST_EXIT" ;;\n'
            ' "role assignment create "*) printf "%s\\n" "$@" > "$FAKE_CREATED" ;;\n'
            " *) exit 1 ;;\nesac\n"
        ),
    }
    for name, script in scripts.items():
        path = bin_dir / name
        path.write_text(script)
        path.chmod(0o755)
    grant = tmp_path / "created.txt"
    result = subprocess.run(  # noqa: S603
        [runner, "copilot:access"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "ARM_SUBSCRIPTION_ID": "approved",
            "FAKE_LOGIN": login,
            "FAKE_HAVE": have,
            "FAKE_LIST_EXIT": list_exit,
            "FAKE_CREATED": str(grant),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is success, result.stdout + result.stderr
    assert grant.exists() is created
    if created:
        args = grant.read_text().splitlines()
        assert args[args.index("--scope") + 1] == scope
        assert args[args.index("--assignee-principal-type") + 1] == "User"
        assert args[args.index("--role") + 1] == "53ca6127-db72-4b80-b1b0-d745d6d5456d"


def shell_body(name: str) -> str:
    body = task_body("Taskfile.deploy.yml", name)
    match = re.search(r"(?ms)^      - \|\n(.*?)(?=^      - task:|\Z)", body)
    assert match, name
    return textwrap.dedent(match[1])


@pytest.mark.parametrize(
    ("existing", "get_exit", "success", "applied"),
    [
        ("", 0, True, True),
        (
            json.dumps(
                {"metadata": {"annotations": {"azure.workload.identity/client-id": "lab-client"}}}
            ),
            0,
            True,
            False,
        ),
        (
            json.dumps(
                {"metadata": {"annotations": {"azure.workload.identity/client-id": "foreign"}}}
            ),
            0,
            False,
            False,
        ),
        ("", 1, False, False),
    ],
)
def test_governance_prerequisites_preserve_shared_identity(
    tmp_path: Path, existing: str, get_exit: int, success: bool, applied: bool
) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to execute the prerequisite guard")
    body = task_body("Taskfile.governance.yml", "_prerequisites")
    script = textwrap.dedent(body.split("      - |\n", 1)[1])
    assert ":deploy:_namespace" in body
    assert "_infrastructure" in task_body("Taskfile.governance.yml", "up")
    up = task_body("Taskfile.governance.yml", "_infrastructure")
    assert up.index("_prerequisites") < up.index("terraform")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    terraform = bin_dir / "terraform"
    terraform.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        " *kubernetes_namespace) echo lab-namespace ;;\n"
        " *agent_deployer_service_account) echo agent-deployer ;;\n"
        " *agent_deployer_client_id) echo lab-client ;;\n"
        " *) exit 1 ;;\nesac\n"
    )
    terraform.chmod(0o755)
    kubectl = bin_dir / "kubectl"
    kubectl.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        ' *"get serviceaccount"*) printf "%s" "$FAKE_EXISTING"; exit "$FAKE_GET_EXIT" ;;\n'
        ' "apply --server-side -f -") cat > "$FAKE_APPLIED" ;;\n'
        " *) exit 1 ;;\nesac\n"
    )
    kubectl.chmod(0o755)
    manifest = tmp_path / "deploy/kustomize/base/serviceaccount.yaml"
    manifest.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "deploy/kustomize/base/serviceaccount.yaml", manifest)
    applied_file = tmp_path / "applied.yaml"
    result = subprocess.run(  # noqa: S603
        [bash, "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_EXISTING": existing,
            "FAKE_GET_EXIT": str(get_exit),
            "FAKE_APPLIED": str(applied_file),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode == 0) is success, result.stderr
    assert applied_file.exists() is applied
    if applied:
        assert "REPLACE_WITH_" not in applied_file.read_text()
        assert "azure.workload.identity/client-id: lab-client" in applied_file.read_text()


@pytest.mark.parametrize("registry", ["", "invalid-name"])
def test_agent_image_build_stops_before_azure_without_valid_registry(
    tmp_path: Path, registry: str
) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to execute the image build command")
    body = task_body("Taskfile.build.yml", "_foundry-image")
    match = re.search(r"(?ms)^      - \|\n(.*)", body)
    assert match
    script = textwrap.dedent(match[1]).replace("{{.ROOT_DIR}}", str(tmp_path))
    script = script.replace("{{.REPOSITORY}}", "containment-demo-governed-agent")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    terraform = bin_dir / "terraform"
    terraform.write_text('#!/bin/sh\nprintf "%s" "$FAKE_REGISTRY"\n')
    terraform.chmod(0o755)
    az = bin_dir / "az"
    az.write_text('#!/bin/sh\ntouch "$FAKE_AZ_CALLED"\n')
    az.chmod(0o755)
    called = tmp_path / "azure-called"
    result = subprocess.run(  # noqa: S603
        [bash, "-c", script],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_REGISTRY": registry,
            "FAKE_AZ_CALLED": str(called),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "Missing or invalid acr_name" in result.stderr
    assert not called.exists()


@pytest.fixture
def dry_task(tmp_path: Path):
    runner = shutil.which("task")
    if runner is None:
        pytest.skip("Go Task is required to compile command aliases")
    shutil.copy2(ROOT / "Taskfile.yml", tmp_path / "Taskfile.yml")
    shutil.copytree(ROOT / "tasks", tmp_path / "tasks")
    taskfiles = [tmp_path / "Taskfile.yml", *(tmp_path / "tasks").glob("Taskfile.*.yml")]
    for taskfile in taskfiles:
        # Dry runs obey silence too; expose commands only in these isolated copies.
        taskfile.write_text(re.sub(r"(?m)^silent: true$", "silent: false", taskfile.read_text()))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    terraform = bin_dir / "terraform"
    terraform.write_text("#!/bin/sh\nprintf '%s\\n' test-value\n")
    terraform.chmod(0o755)

    def run(name: str) -> str:
        result = subprocess.run(  # noqa: S603
            [runner, "--dry", "--yes", name],
            cwd=tmp_path,
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "TMPDIR": str(tmp_path),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    return run


def test_model_grant_journal_is_private_in_the_real_task_shell(tmp_path: Path) -> None:
    runner = shutil.which("task")
    if runner is None:
        pytest.skip("Go Task is required to execute the model-access command")
    shutil.copytree(ROOT / "tasks", tmp_path / "tasks")
    journal = tmp_path / "private/model-access.json"
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\nsilent: true\nincludes:\n"
        "  cloud:\n    taskfile: ./tasks/Taskfile.cloud.yml\n"
        "tasks:\n  grant:\n    cmds:\n      - task: cloud:_agent-access\n"
        "        vars:\n          APPLY: 'true'\n"
        "          AGENT_NAMES: containment-demo-audit-gov-success\n"
        f"          JOURNAL: '{journal}'\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scope = (
        "/subscriptions/synthetic/resourceGroups/lab"
        "/providers/Microsoft.CognitiveServices/accounts/lab"
    )
    assignment = json.dumps(
        {"id": f"{scope}/providers/Microsoft.Authorization/roleAssignments/synthetic"}
    )
    scripts = {
        "terraform": (
            '#!/bin/sh\ncase "$*" in\n'
            f' *foundry_account_id) echo "{scope}" ;;\n'
            " *agent_name_audit) echo containment-demo-audit ;;\n"
            " *) echo synthetic ;;\nesac\n"
        ),
        "az": (
            '#!/bin/sh\ncase "$*" in\n'
            ' "ad sp list "*) echo 00000000-0000-4000-8000-000000000001 ;;\n'
            ' "role assignment list "*) echo 0 ;;\n'
            f" \"role assignment create \"*) echo '{assignment}' ;;\n"
            " *) exit 1 ;;\nesac\n"
        ),
    }
    for name, script in scripts.items():
        path = bin_dir / name
        path.write_text(script)
        path.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [runner, "grant"],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    grants = json.loads(journal.read_text())
    assert len(grants) == 1
    assert grants[0]["agent_name"] == "containment-demo-audit-gov-success"
    assert grants[0]["scope"] == scope
    assert journal.stat().st_mode & 0o777 == 0o600
    assert not list(journal.parent.glob("model-access.json.*"))


@pytest.mark.parametrize("export_exit", [0, 23])
def test_identity_setup_runs_in_task_shell_with_private_atomic_export(
    tmp_path: Path, export_exit: int
) -> None:
    runner = shutil.which("task")
    if runner is None:
        pytest.skip("Go Task is required to execute the identity setup command")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    shutil.copy2(ROOT / "tasks/Taskfile.identity.yml", tasks / "Taskfile.identity.yml")
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\nsilent: true\nincludes:\n"
        "  identity:\n    taskfile: ./tasks/Taskfile.identity.yml\n"
    )
    private = tmp_path / ".identity-probe"
    private.mkdir()
    config = private / "setup-inputs.json"
    previous = '{"previous":true}\n'
    config.write_text(previous)
    config.chmod(0o600)
    payload = {"tenant_id": "00000000-0000-4000-8000-000000000001", "private": "synthetic"}
    events = tmp_path / "events"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    scripts = {
        "terraform": """
            import os, sys
            from pathlib import Path
            action = sys.argv[2]
            with Path(os.environ["FAKE_EVENTS"]).open("a") as log:
                log.write(action + "\\n")
            if action == "apply":
                assert sys.argv[3:] == ["-input=false", "-auto-approve"]
            elif action == "output":
                assert sys.argv[3:] == ["-json", "setup_config"]
                print(os.environ["FAKE_INPUTS"])
                sys.exit(int(os.environ["FAKE_EXPORT_EXIT"]))
            else:
                raise AssertionError(sys.argv)
        """,
        "pwsh": """
            import json, os, sys
            from pathlib import Path
            args = sys.argv[1:]
            assert args[args.index("-Action") + 1] == "Setup"
            assert "-ApproveRead" in args and "-ApproveMutation" in args
            path = Path(args[args.index("-InputsPath") + 1])
            assert path.stat().st_mode & 0o777 == 0o600
            data = json.loads(path.read_text())
            assert data == json.loads(os.environ["FAKE_INPUTS"])
            assert args[args.index("-TenantId") + 1] == data["tenant_id"]
            with Path(os.environ["FAKE_EVENTS"]).open("a") as log:
                log.write("graph_setup\\n")
        """,
    }
    for name, source in scripts.items():
        script = bin_dir / name
        script.write_text(f"#!{sys.executable}\n" + textwrap.dedent(source))
        script.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [runner, "identity:setup"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_EVENTS": str(events),
            "FAKE_INPUTS": json.dumps(payload),
            "FAKE_EXPORT_EXIT": str(export_exit),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    calls = events.read_text().splitlines()
    if export_exit == 0:
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(config.read_text()) == payload
        assert calls == ["apply", "output", "graph_setup"]
    else:
        assert result.returncode != 0
        assert config.read_text() == previous
        assert calls == ["apply", "output"]
    assert config.stat().st_mode & 0o777 == 0o600
    assert list(private.glob("setup-inputs.*")) == [config]
    assert "synthetic" not in result.stdout + result.stderr


def test_rebuild_defaults_match_task_and_terraform() -> None:
    taskfile = (ROOT / "Taskfile.yml").read_text()
    variables = (ROOT / "infra/cloud/variables.tf").read_text()
    assert re.search(r"(?m)^  DEFAULT_REGION: swedencentral$", taskfile)
    for name, expected in (("region", "swedencentral"), ("aks_node_size", "Standard_D4as_v7")):
        block = re.search(rf'(?ms)^variable "{name}" \{{\n(.*?)^\}}', variables)
        assert block, name
        assert re.search(rf'(?m)^  default\s+= "{expected}"$', block[1]), name


@pytest.mark.parametrize(
    "command", ["cloud:plan", "cloud:bootstrap", "cloud:up", "deploy:tool-apis"]
)
def test_deployment_tasks_resolve_sweden_central(dry_task, command: str) -> None:
    commands = dry_task(command)
    assert "region=swedencentral" in commands
    assert "region=canadacentral" not in commands


def test_build_all_has_all_components_and_no_deployment(dry_task) -> None:
    body = task_body("Taskfile.build.yml", "all")
    assert re.findall(r"- task: ([\w-]+)", body) == list(COMPONENTS)
    commands = dry_task("build:all")
    assert commands.count("acr build") == 6  # tool-apis builds two images in a loop
    assert "for SVC in policy_api test_receiver" in commands
    assert "kubectl" not in commands
    assert " apply " not in commands


def test_deploy_all_is_sequential_and_builds_nothing(dry_task) -> None:
    body = task_body("Taskfile.deploy.yml", "all")
    assert "deps:" not in body
    assert re.findall(r"- task: ([\w-]+)", body) == [
        "tool-apis",
        "foundry-agent",
        "model-server",
        "test-ui",
        "agent-bridge",
        "chat-agent",
    ]
    commands = dry_task("deploy:all")
    assert "acr build" not in commands
    assert re.findall(r"-target=(\S+)", commands) == [
        "azurerm_container_app.policy_api",
        "azurerm_container_app.test_receiver",
    ]
    assert "rollout status deployment/agent-harness" in commands
    assert commands.index("rollout status deployment/agent-harness") < commands.index(
        "role assignment create"
    )
    assert commands.index("rollout status deployment/demo-ui") < commands.index(
        "rollout status deployment/a2a-facade-audit"
    )
    assert commands.index("rollout status deployment/local-model") < commands.index(
        "rollout status deployment/harness"
    )


@pytest.mark.parametrize(
    "taskfile",
    [ROOT / "Taskfile.yml", *sorted((ROOT / "tasks").glob("Taskfile*.yml"))],
    ids=lambda path: path.name,
)
def test_all_tasks_have_no_confirmation_prompts(taskfile: Path) -> None:
    assert not re.search(r"(?m)^\s*prompt:", taskfile.read_text())


@pytest.mark.parametrize("component", COMPONENTS)
def test_every_component_has_matching_build_and_deploy_commands(dry_task, component: str) -> None:
    dry_task(f"build:{component}")
    dry_task(f"deploy:{component}")


@pytest.mark.parametrize(
    "legacy",
    [
        "build:agent",
        "build:services",
        "build:agent-digest",
        "build:deploy-endpoints",
        "a2a:build",
        "harness:build",
        "local-model:build",
        "ui:build",
    ],
)
def test_legacy_commands_still_compile(dry_task, legacy: str) -> None:
    dry_task(legacy)


def test_secret_and_serviceaccount_ordering() -> None:
    ui = task_body("Taskfile.deploy.yml", "test-ui")
    assert ui.index("_namespace") < ui.index(":agent-bridge:secret") < ui.index(":test-ui:up")
    assert ui.index(":test-ui:secret") < ui.index(":test-ui:up")
    bridge = task_body("Taskfile.deploy.yml", "agent-bridge")
    assert bridge.index(":agent-bridge:secret") < bridge.index(":agent-bridge:up")
    chat = task_body("Taskfile.deploy.yml", "chat-agent")
    assert chat.index(":agent-bridge:secret") < chat.index(":chat-agent:up")
    assert chat.index(":chat-agent:secret") < chat.index(":chat-agent:up")


def test_harness_external_ingress_tasks_are_wired() -> None:
    external_prereqs = task_body("Taskfile.harness.yml", "external-prereqs")
    assert "helm upgrade --install ingress-nginx" in external_prereqs
    assert "--set controller.service.externalTrafficPolicy=Local" in external_prereqs
    assert "azure-load-balancer-health-probe-request-path" in external_prereqs
    assert "helm upgrade --install cert-manager" in external_prereqs

    external_app = task_body("Taskfile.harness.yml", "external-app")
    assert "az ad app create" in external_app
    assert "az ad app update" in external_app
    assert "az ad sp show" in external_app
    assert "az ad app credential reset" in external_app

    external_bootstrap = task_body("Taskfile.harness.yml", "external-bootstrap")
    assert "task: external-prereqs" in external_bootstrap
    assert "task: external-app" in external_bootstrap
    assert "task: external-up" in external_bootstrap

    external_secret = task_body("Taskfile.harness.yml", "external-secret")
    assert 'COOKIE_SECRET="${COOKIE_SECRET:-}"' in external_secret

    external_render = task_body("Taskfile.harness.yml", "external-render")
    assert "kustomize build deploy/kustomize/harness-external" in external_render
    assert "REPLACE_WITH_EXTERNAL_HOSTNAME" in external_render
    assert "Refusing: these placeholders were not substituted" in external_render

    external_up = task_body("Taskfile.harness.yml", "external-up")
    assert "chat-agent:external-render" in external_up
    assert "set env deployment/harness HARNESS_AUTH_MODE=ingress_oidc" in external_up
    assert "rollout status deployment/harness-oauth2-proxy" in external_up
    assert "rollout status deployment/harness" in external_up

    external_down = task_body("Taskfile.harness.yml", "external-down")
    assert "set env deployment/harness HARNESS_AUTH_MODE=legacy" in external_down

    verify = task_body("Taskfile.harness.yml", "verify")
    assert 'if [ "$MODE" = "ingress_oidc" ]; then' in verify
    assert "WANT_WITH=401" in verify


def test_chat_agent_secret_updates_optional_diagnostics_links() -> None:
    secret = task_body("Taskfile.harness.yml", "secret")
    assert "--from-literal=HARNESS_WORKBOOK_URL=" in secret
    assert "--from-literal=HARNESS_LOGS_URL=" in secret
    assert "--from-literal=HARNESS_APPINSIGHTS_URL=" in secret
    assert "rollout restart deployment/harness" in secret


def test_app_deploy_external_orchestrates_from_scratch_flow() -> None:
    deploy = task_body("Taskfile.app.yml", "deploy")
    assert "task: :cloud:up" in deploy
    assert "task: :deploy:app-components" in deploy

    deploy_external = task_body("Taskfile.app.yml", "deploy-external")
    assert "task: :cloud:up" in deploy_external
    assert "task: :deploy:app-components" in deploy_external
    assert "task: :chat-agent:external-bootstrap" in deploy_external


def test_deploy_app_components_excludes_tool_apis() -> None:
    app_components = task_body("Taskfile.deploy.yml", "app-components")
    assert "task: foundry-agent" in app_components
    assert "task: model-server" in app_components
    assert "task: test-ui" in app_components
    assert "task: agent-bridge" in app_components
    assert "task: chat-agent" in app_components
    assert "task: tool-apis" not in app_components


@pytest.mark.parametrize(
    ("file", "prefix"),
    [
        ("Taskfile.a2a.yml", "A2A"),
        ("Taskfile.harness.yml", "HARNESS"),
        ("Taskfile.local-model.yml", "LOCAL_MODEL"),
        ("Taskfile.ui.yml", "UI"),
    ],
)
def test_component_build_and_render_preserve_the_same_tag_defaults(file: str, prefix: str) -> None:
    build = task_body(file, "build")
    assert f'"${{{prefix}_IMAGE_TAG:-}}"' in build
    assert "latest" not in build
    assert "image_tag_record" in build
    for name in ("digest", "render"):
        body = task_body(file, name)
        assert f"TAG_OVERRIDE: '${{{prefix}_IMAGE_TAG:-}}'" in body
        assert "latest" not in body
        assert f"EXPLICIT: '${{{prefix}_IMAGE_DIGEST:-}}'" in body


def run_endpoint_plan(tmp_path: Path, plan: str, *, tamper: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    if shutil.which("jq") is None:
        pytest.skip("jq is required to execute the plan guard")
    calls = tmp_path / "calls"
    terraform = tmp_path / "terraform"
    terraform.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
        'case "$*" in\n'
        '  *" plan "*) exit 0 ;;\n'
        '  *" show -json "*) printf "%s\\n" "$TEST_PLAN" ;;\n'
        '  *" apply "*) exit 0 ;;\n'
        '  *) echo "unexpected command" >&2; exit 1 ;;\n'
        "esac\n"
    )
    terraform.chmod(0o755)
    (tmp_path / "scripts").mkdir(exist_ok=True)
    shutil.copy(
        Path(__file__).resolve().parents[2] / "scripts" / "image-tag.sh",
        tmp_path / "scripts" / "image-tag.sh",
    )
    script = shell_body("tool-apis").replace("{{.ROOT_DIR}}", str(tmp_path))
    script = script.replace("{{.REGION}}", "canadacentral")
    if tamper:
        start = script.index("if ! printf")
        end = script.index(f'terraform -chdir="{tmp_path}', start)
        script = script[:start] + script[end:]
    result = subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "TMPDIR": str(tmp_path),
            "CALL_LOG": str(calls),
            "TEST_PLAN": plan,
            "IMAGE_TAG": "existing-build",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text()


def plan_with(address: str, actions: list[str], mode: str = "managed") -> str:
    return json.dumps(
        {
            "format_version": "1.2",
            "planned_values": {"root_module": {}},
            "resource_changes": [
                {"address": address, "mode": mode, "change": {"actions": actions}},
            ],
        }
    )


def test_api_deployment_targets_only_existing_apps_and_applies_the_saved_plan(
    tmp_path: Path,
) -> None:
    result, calls = run_endpoint_plan(
        tmp_path, plan_with("azurerm_container_app.policy_api", ["update"])
    )
    assert result.returncode == 0, result.stderr
    plan_call = next(line for line in calls.splitlines() if " plan " in line)
    assert re.findall(r"-target=(\S+)", plan_call) == [
        "azurerm_container_app.policy_api",
        "azurerm_container_app.test_receiver",
    ]
    apply_call = next(line for line in calls.splitlines() if " apply " in line)
    assert "-target" not in apply_call
    assert "endpoints.tfplan" in apply_call


@pytest.mark.parametrize(
    "dependency",
    [
        "azapi_resource.rai_policy_audit",
        "azapi_resource.rai_policy_enforced",
        "azurerm_log_analytics_workspace.main",
    ],
)
def test_api_deployment_rejects_dependency_changes_even_with_valid_app_updates(
    tmp_path: Path, dependency: str
) -> None:
    plan = json.loads(plan_with("azurerm_container_app.policy_api", ["update"]))
    plan["resource_changes"].extend(
        [
            json.loads(plan_with("azurerm_container_app.test_receiver", ["update"]))[
                "resource_changes"
            ][0],
            json.loads(plan_with(dependency, ["update"]))["resource_changes"][0],
        ]
    )
    result, calls = run_endpoint_plan(tmp_path, json.dumps(plan))
    assert result.returncode != 0
    assert "Refusing" in result.stderr
    assert " apply " not in calls


@pytest.mark.parametrize(
    ("address", "actions", "mode", "allowed"),
    [
        ("azurerm_container_app.policy_api", ["update"], "managed", True),
        ("azurerm_container_app.test_receiver", ["update"], "managed", True),
        ("azapi_resource.rai_enforced", ["no-op"], "managed", True),
        ("data.azurerm_client_config.current", ["read"], "data", True),
        ("azapi_resource.rai_enforced", ["update"], "managed", False),
        ("azurerm_kubernetes_cluster.main", ["create"], "managed", False),
        ("azurerm_container_app.policy_api", ["create"], "managed", False),
        ("azurerm_container_app.policy_api", ["delete", "create"], "managed", False),
        ("azurerm_container_app.test_receiver", ["delete"], "managed", False),
    ],
)
def test_only_existing_app_updates_can_be_applied(
    tmp_path: Path, address: str, actions: list[str], mode: str, allowed: bool
) -> None:
    result, calls = run_endpoint_plan(tmp_path, plan_with(address, actions, mode))
    assert (result.returncode == 0) is allowed, result.stderr
    assert (" apply " in calls) is allowed
    if allowed:
        saved = re.search(r"-out=(.*endpoints\.tfplan)", calls)
        assert saved and f"apply -input=false -compact-warnings {saved[1]}" in calls
    else:
        assert "Refusing" in result.stderr


@pytest.mark.parametrize("plan", ["{}", "not-json", '{"errored": true}'])
def test_missing_or_invalid_plan_is_not_applied(tmp_path: Path, plan: str) -> None:
    result, calls = run_endpoint_plan(tmp_path, plan)
    assert result.returncode != 0
    assert " apply " not in calls


def test_plan_guard_tamper_is_detected(tmp_path: Path) -> None:
    plan = plan_with("azapi_resource.rai_enforced", ["update"])
    intact, intact_calls = run_endpoint_plan(tmp_path / "intact", plan)
    assert intact.returncode != 0 and " apply " not in intact_calls
    broken, broken_calls = run_endpoint_plan(tmp_path / "tampered", plan, tamper=True)
    with pytest.raises(AssertionError):
        assert broken.returncode != 0 and " apply " not in broken_calls


def run_namespace_guard(tmp_path: Path, context: str, *, tamper: bool = False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    calls = tmp_path / "calls"
    scripts = {
        "terraform": (
            '#!/bin/sh\ncase "$*" in\n'
            "  *aks_cluster_name) echo test-aks ;;\n"
            "  *kubernetes_namespace) echo test-namespace ;;\n"
            "  *) exit 1 ;;\nesac\n"
        ),
        "kubectl": (
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
            'case "$*" in\n'
            '  "config current-context") printf "%s\\n" "$TEST_CONTEXT" ;;\n'
            '  "create namespace "*) echo namespace-manifest ;;\n'
            '  "apply --server-side -f -") cat >/dev/null ;;\n'
            "  *) exit 1 ;;\nesac\n"
        ),
        "kustomize": "#!/bin/sh\nexit 1\n",
        "openssl": "#!/bin/sh\nexit 1\n",
    }
    for name, content in scripts.items():
        executable = tmp_path / name
        executable.write_text(content)
        executable.chmod(0o755)
    script = shell_body("_namespace").replace("{{.ROOT_DIR}}", str(tmp_path))
    if tamper:
        start = script.index('[ "$ACTUAL" = "$EXPECTED" ]')
        end = script.index("NS=$(terraform", start)
        script = script[:start] + script[end:]
    result = subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "CALL_LOG": str(calls),
            "TEST_CONTEXT": context,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls.read_text()


@pytest.mark.parametrize("context", ["test-aks", "another-cluster"])
def test_namespace_is_only_written_in_the_state_cluster(tmp_path: Path, context: str) -> None:
    result, calls = run_namespace_guard(tmp_path, context)
    allowed = context == "test-aks"
    assert (result.returncode == 0) is allowed
    assert ("apply --server-side" in calls) is allowed
    if not allowed:
        assert "not the Terraform AKS cluster" in result.stderr
        assert "create namespace" not in calls


def test_namespace_guard_tamper_is_detected(tmp_path: Path) -> None:
    broken, calls = run_namespace_guard(tmp_path, "another-cluster", tamper=True)
    with pytest.raises(AssertionError):
        assert broken.returncode != 0 and "apply --server-side" not in calls
