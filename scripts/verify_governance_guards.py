"""Owner-run tamper checks in disposable copies; never mutate the working tree."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("src/containment_demo/governance/runtime.py")
TESTS = "tests/unit/test_governance.py"
MUTATIONS = (
    (
        "execution boundary",
        RUNTIME,
        "if settings.governance_mode is GovernanceMode.DISABLED:",
        "if True:",
        "test_enforced_deny_never_executes",
    ),
    (
        "fail closed",
        RUNTIME,
        'evaluation.verdict == "deny" or evaluation.error',
        'evaluation.verdict == "deny"',
        "test_evaluator_exception_fail_closed",
    ),
    (
        "decision evidence",
        RUNTIME,
        "emit_governance_evidence(settings, evidence)",
        "pass",
        "test_governance_evidence_is_correlated_and_private",
    ),
    (
        "ADK callback wiring",
        Path("src/containment_demo/agent.py"),
        "before_tool_callback=before_tool_callback,",
        "before_tool_callback=None,",
        "test_real_adk_dispatch_preserves_registration_and_delegated_token[enforced]",
    ),
    (
        "bounded evaluation",
        RUNTIME,
        "timeout=settings.governance_timeout_seconds,",
        "timeout=60,",
        "test_timeout_and_malformed_result_fail_closed",
    ),
)


def check(copy: Path, selector: str) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("POLICY_API_")
    }
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", selector, "-q"],
        cwd=copy,
        env={
            **environment,
            "PYTHONPATH": str(copy / "src"),
            "GOVERNANCE_TEST_OPA": str(ROOT / ".task/governance/bin/opa"),
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def run_mutations(
    mutations: tuple[tuple[str, Path, str, str, str], ...],
    test_file: str = TESTS,
) -> int:
    with TemporaryDirectory(prefix="containment-governance-guards-") as directory:
        copy = Path(directory)
        for name in ("src", "tests", "services", "policies", "scripts"):
            shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "pyproject.toml", copy / "pyproject.toml")
        for label, path, original, broken, test in mutations:
            selector = test if "::" in test else f"{test_file}::{test}"
            source_file = copy / path
            source = source_file.read_text()
            baseline = check(copy, selector)
            if baseline.returncode != 0:
                print(f"FAIL: {label} baseline did not pass\n{baseline.stdout}{baseline.stderr}")
                return 1
            if source.count(original) != 1:
                print(f"FAIL: {label} mutation no longer matches exactly once")
                return 1
            source_file.write_text(source.replace(original, broken))
            try:
                result = check(copy, selector)
            finally:
                source_file.write_text(source)
            if result.returncode != 1 or "1 failed" not in result.stdout:
                print(f"FAIL: {label} did not fail its test\n{result.stdout}{result.stderr}")
                return 1
            restored = check(copy, selector)
            if restored.returncode != 0:
                print(f"FAIL: {label} restoration failed\n{restored.stdout}{restored.stderr}")
                return 1
            print(f"PASS: {label} baseline passed, mutation failed, restoration passed")
    return 0


def main() -> int:
    return run_mutations(MUTATIONS)


if __name__ == "__main__":
    raise SystemExit(main())
