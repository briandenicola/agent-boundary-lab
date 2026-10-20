"""Offline checks for the public command interface and application-only deployment."""

from __future__ import annotations

import json
import os
import re
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


def task_body(file: str, name: str) -> str:
    content = (ROOT / "tasks" / file).read_text()
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:|\Z)", content)
    assert match, name
    return match[1]


def shell_body(name: str) -> str:
    body = task_body("Taskfile.deploy.yml", name)
    match = re.search(r"(?ms)^      - \|\n(.*?)(?=^      - task:|\Z)", body)
    assert match, name
    return textwrap.dedent(match[1])


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
    assert "-target=" not in commands
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
    ("file", "name"),
    [
        *(("Taskfile.deploy.yml", name) for name in ("all", *COMPONENTS)),
        ("Taskfile.cloud.yml", "harness-up"),
        ("Taskfile.local-model.yml", "up"),
        ("Taskfile.ui.yml", "up"),
        ("Taskfile.a2a.yml", "up"),
        ("Taskfile.harness.yml", "up"),
    ],
)
def test_deployment_chain_has_no_confirmation_prompts(file: str, name: str) -> None:
    assert "prompt:" not in task_body(file, name)


@pytest.mark.parametrize(
    ("file", "name"),
    [
        ("Taskfile.cloud.yml", "down"),
        ("Taskfile.cloud.yml", "bootstrap"),
        ("Taskfile.cloud.yml", "network-up"),
        ("Taskfile.local-model.yml", "build"),
    ],
)
def test_separate_operations_keep_their_confirmations(file: str, name: str) -> None:
    assert "prompt:" in task_body(file, name)


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
    assert f"${{{prefix}_IMAGE_TAG:-latest}}" in build
    tag = "${" + prefix + "_IMAGE_TAG:-latest}"
    for name in ("digest", "render"):
        body = task_body(file, name)
        assert f"TAG: '{tag}'" in body
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
