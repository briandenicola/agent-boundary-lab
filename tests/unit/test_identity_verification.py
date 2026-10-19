"""Execute the public verification task offline, with synthetic completed setup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import asdict
from pathlib import Path

import pytest

from containment_demo import identity_directory as directory
from containment_demo import identity_setup as setup
from containment_demo.identity_verification import private_json, ready, verdict
from tests.unit.test_identity_setup import Graph
from tests.unit.test_identity_setup import inputs as inputs_fixture
from tests.unit.test_identity_setup import settings as settings_fixture

ROOT = Path(__file__).resolve().parents[2]
inputs = inputs_fixture
settings = settings_fixture


def passed() -> dict:
    return {
        "foundry_delegation": "pass",
        "cases": [
            {
                "name": name,
                "verdict": "pass",
                "stage": "foundry_invocation",
                "http_status": status,
                "response_id": "synthetic-response",
            }
            for name, status in (
                ("allowed", 200),
                ("denied", 403),
                ("invalid_token", 401),
                ("wrong_audience", 401),
            )
        ],
    }


@pytest.mark.parametrize(
    ("mode", "ok", "cleanup_failed"),
    [
        ("pass", True, False),
        ("fail", False, False),
        ("inconclusive", False, False),
        ("job_failed", False, False),
        ("login_failed", False, False),
        ("denied_login_failed", False, False),
        ("logs_missing", False, False),
        ("logs_malformed", False, False),
        ("sidecar_failed", False, False),
        ("incoming_failed", False, False),
        ("timeout", False, False),
        ("status_missing", False, False),
        ("missing_setup", False, False),
        ("missing_config", False, False),
        ("cleanup_context_lost", False, False),
        ("pass", False, True),
    ],
)
def test_public_verify(
    tmp_path: Path, inputs, settings, mode: str, ok: bool, cleanup_failed: bool
) -> None:
    runner = shutil.which("task")
    if runner is None:
        pytest.skip("Task runner unavailable")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    shutil.copy2(ROOT / "tasks/Taskfile.identity.yml", tasks / "Taskfile.identity.yml")
    (tmp_path / "Taskfile.yml").write_text(
        "version: '3'\nsilent: true\nincludes:\n"
        "  identity:\n    taskfile: ./tasks/Taskfile.identity.yml\n"
    )
    (tmp_path / "src").symlink_to(ROOT / "src", target_is_directory=True)
    private = tmp_path / ".identity-probe"
    private.mkdir(mode=0o700)
    state = private / "setup-state.json"
    setup.run(Graph(), state, inputs, settings)
    journal_before = state.read_bytes()
    journal = json.loads(journal_before)
    config = inputs.probe_config(
        setup.client_id(journal, "blueprint"),
        setup.client_id(journal, "browser"),
        journal["resources"]["agent"]["id"],
    )
    directory.save(private / "config.json", asdict(config))
    config_before = (private / "config.json").read_bytes()
    if mode == "missing_setup":
        state.unlink()
    elif mode == "missing_config":
        (private / "config.json").unlink()
    events = tmp_path / "events"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    scripts = {
        python: """
            import json, os, sys
            from pathlib import Path
            args = sys.argv[1:]
            if args[:2] == ["-m", "containment_demo.identity_probe"]:
                action = args[2]
                with Path(os.environ["EVENTS"]).open("a") as log:
                    log.write(action + (" " + args[-1] if action == "login" else "") + "\\n")
                if action == "login":
                    if os.environ["MODE"] == "login_failed": sys.exit(1)
                    if os.environ["MODE"] == "denied_login_failed" and args[-1] == "denied":
                        sys.exit(1)
                    token = Path(".identity-probe") / (args[-1] + ".jwt")
                    token.write_text("SYNTHETIC-NOT-A-TOKEN")
                    token.chmod(0o600)
                elif action == "manifest": print("{}")
                sys.exit(0)
            os.execv(os.environ["REAL_PYTHON"], [os.environ["REAL_PYTHON"], *args])
        """,
        bindir / "terraform": """
            import sys
            assert sys.argv[2:4] == ["output", "-raw"], sys.argv
            print("synthetic-cluster" if sys.argv[-1] == "aks_cluster_name"
                  else "agent-boundary-lab")
        """,
        bindir / "kubectl": """
            import json, os, sys
            from pathlib import Path
            a = sys.argv[1:]
            mode = os.environ["MODE"]
            with Path(os.environ["EVENTS"]).open("a") as log:
                log.write("kubectl " + " ".join(a) + "\\n")
            if a == ["config", "current-context"]:
                calls = Path(os.environ["EVENTS"]).read_text()
                lost = mode == "cleanup_context_lost" and calls.count("config current-context") >= 3
                print("wrong-cluster" if lost else "synthetic-cluster")
            elif "version" in a: print('{"serverVersion":{"major":"1","minor":"33"}}')
            elif "job,secret,configmap,serviceaccount" in a: print('{"items":[]}')
            elif "create" in a: print('{"metadata":{},"data":{}}')
            elif "wait" in a: sys.exit(1 if mode in ("job_failed", "timeout") else 0)
            elif "logs" in a:
                if mode == "logs_missing": sys.exit(1)
                if mode == "logs_malformed":
                    print("NOT-JSON-MUST-NOT-BE-PRINTED")
                    sys.exit(0)
                result = json.loads(os.environ["REPORT"])
                if mode in ("fail", "inconclusive"): result["foundry_delegation"] = mode
                if mode in ("sidecar_failed", "incoming_failed"):
                    result["foundry_delegation"] = "inconclusive"
                    result["cases"][0].update({
                        "verdict": "inconclusive",
                        "stage": (
                            "sidecar_obo" if mode == "sidecar_failed" else "incoming_validation"
                        ),
                        "http_status": 400 if mode == "sidecar_failed" else 401,
                        "detail": "MUST-NOT-BE-PRINTED",
                    })
                result["untrusted_payload"] = "MUST-NOT-BE-PRINTED"
                print(json.dumps(result))
            elif "get" in a:
                if mode == "status_missing": sys.exit(1)
                print(json.dumps({"status": {} if mode == "timeout" else {
                    "failed" if mode == "job_failed" else "succeeded": 1}}))
            elif "delete" in a and "secret" in a:
                sys.exit(1 if os.environ["CLEANUP_FAILED"] == "1" else 0)
        """,
    }
    for path, content in scripts.items():
        path.write_text(f"#!{sys.executable}\n" + textwrap.dedent(content))
        path.chmod(0o755)
    result = subprocess.run(  # noqa: S603 - resolved local Task, fake executables only
        [runner, "identity:verify"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "REAL_PYTHON": sys.executable,
            "EVENTS": str(events),
            "MODE": mode,
            "REPORT": json.dumps(passed()),
            "CLEANUP_FAILED": str(int(cleanup_failed)),
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert (result.returncode == 0) is ok, result.stdout + result.stderr
    if mode in ("missing_setup", "missing_config"):
        assert not events.exists()
        if mode == "missing_setup":
            assert not state.exists()
            assert (private / "config.json").read_bytes() == config_before
        else:
            assert not (private / "config.json").exists()
            assert state.read_bytes() == journal_before
        return
    calls = events.read_text()
    assert "login allowed" in calls
    report = json.loads((private / "verification-result.json").read_text())
    if mode not in ("login_failed", "denied_login_failed"):
        assert calls.index("login allowed") < calls.index("login denied") < calls.index("wait")
        expected = (
            mode
            if mode in ("pass", "fail", "inconclusive")
            else "pass"
            if mode == "cleanup_context_lost"
            else "inconclusive"
        )
        assert report["foundry_delegation"] == expected
        assert report["i0_complete"] is False
        assert report["containment"] == "not_evaluated"
    else:
        expected_reason = "allowed_login_failed" if mode == "login_failed" else mode
        assert report["foundry_delegation"] == "inconclusive"
        assert report["reason"] == expected_reason
    reasons = {
        "logs_missing": "probe_logs_missing",
        "logs_malformed": "probe_report_malformed",
        "job_failed": "probe_job_failed",
        "timeout": "probe_wait_failed_or_timeout",
        "status_missing": "probe_job_status_unavailable",
    }
    if mode in reasons:
        assert report["reason"] == reasons[mode]
    if mode in ("sidecar_failed", "incoming_failed"):
        expected_stage = "sidecar_obo" if mode == "sidecar_failed" else "incoming_validation"
        assert report["cases"][0]["stage"] == expected_stage
        assert report["cases"][0]["http_status"] == (400 if mode == "sidecar_failed" else 401)
        assert "detail" not in report["cases"][0]
    assert ("delete secret" in calls) is (mode != "cleanup_context_lost")
    assert not list(private.glob("*.jwt"))
    assert state.read_bytes() == journal_before
    assert (private / "config.json").read_bytes() == config_before
    assert "SYNTHETIC-NOT-A-TOKEN" not in result.stdout + result.stderr
    assert "MUST-NOT-BE-PRINTED" not in result.stdout + result.stderr
    if cleanup_failed:
        assert "cleanup incomplete" in result.stderr


def test_no_success_without_positive_control() -> None:
    report = passed()
    assert verdict(json.dumps(report), True)["foundry_delegation"] == "pass"
    report["cases"][0]["http_status"] = 403
    assert verdict(json.dumps(report), True)["foundry_delegation"] == "inconclusive"


def test_only_valid_optional_correlation_metadata_is_retained() -> None:
    report = passed()
    report["probe_run_id"] = "00000000-0000-4000-8000-000000000001"
    result = verdict(json.dumps(report), True)
    assert result["probe_run_id"] == report["probe_run_id"]
    assert result["cases"][0]["response_id"] == "synthetic-response"
    report["probe_run_id"] = "NOT-A-UUID-MUST-NOT-BE-PRINTED"
    report["cases"][0]["response_id"] = "untrusted.payload.must.not.be.printed"
    result = verdict(json.dumps(report), True)
    assert "probe_run_id" not in result
    assert "response_id" not in result["cases"][0]


def test_success_guard_mutation_is_detected() -> None:
    source = (ROOT / "src/containment_demo/identity_verification.py").read_text()
    namespace = {"__name__": "isolated_guard_mutant"}
    exec(  # noqa: S102 - isolated, fixed-source safety-guard mutation; no user input
        compile(
            source.replace(
                'elif value == "pass" and succeeded:',
                'elif value == "pass":',
            ),
            "<isolated guard mutation>",
            "exec",
        ),
        namespace,
    )
    assert verdict(json.dumps(passed()), False)["foundry_delegation"] == "inconclusive"
    with pytest.raises(AssertionError):
        assert (
            namespace["verdict"](json.dumps(passed()), False)["foundry_delegation"]
            == "inconclusive"
        )


def test_completed_setup_guard(tmp_path: Path, inputs, settings) -> None:
    state = tmp_path / "setup-state.json"
    setup.run(Graph(), state, inputs, settings)
    journal = json.loads(state.read_text())
    config = tmp_path / "config.json"
    setup.configure(config, journal, inputs)
    ready(state, config)
    journal["pending"] = setup.ORDER[0]
    directory.save(state, journal)
    with pytest.raises(directory.ProbeError):
        ready(state, config)


def test_missing_ready_files_are_not_created(tmp_path: Path, inputs, settings) -> None:
    state, config = tmp_path / "setup-state.json", tmp_path / "config.json"
    with pytest.raises(FileNotFoundError):
        ready(state, config)
    assert not state.exists()
    assert not config.exists()
    # An absent read has not poisoned the existing engine's no-journal creation gate.
    setup.run(Graph(), state, inputs, settings)
    before = state.read_bytes()
    with pytest.raises(FileNotFoundError):
        ready(state, config)
    assert not config.exists()
    assert state.read_bytes() == before
    setup.configure(config, json.loads(before), inputs)
    ready(state, config)


def test_noncreating_read_retains_privacy_guards(tmp_path: Path) -> None:
    path = tmp_path / "private.json"
    directory.save(path, {"synthetic": True})
    assert private_json(path) == {"synthetic": True}
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        private_json(link)
    path.chmod(0o644)
    with pytest.raises(directory.ProbeError):
        private_json(path)
