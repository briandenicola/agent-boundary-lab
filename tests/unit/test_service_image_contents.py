"""The tool-API image copies containment_demo files one by one; a missing one only fails
at container start. This keeps the COPY line and the services' imports in step."""

from __future__ import annotations

import ast
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ROOT / "src" / "services"


def _copied_modules() -> set[str]:
    text = (SERVICES / "Dockerfile").read_text()
    names: set[str] = set()
    for line in re.findall(r"^COPY (src/containment_demo/\S.*) \./containment_demo/$", text, re.M):
        names.update(Path(p).stem for p in line.split())
    return names


def _imported_modules(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            parts = node.module.split(".")
            if parts[0] == "containment_demo" and len(parts) > 1:
                found.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "containment_demo" and len(parts) > 1:
                    found.add(parts[1])
    return found


def test_every_containment_demo_module_a_service_needs_is_copied_into_the_image() -> None:
    copied = _copied_modules()
    needed: set[str] = set()
    pending = [
        p for service in ("policy_api", "test_receiver") for p in (SERVICES / service).rglob("*.py")
    ]
    assert pending, "No service sources found"
    seen: set[str] = set()
    for path in pending:
        needed |= _imported_modules(path)
    while needed - seen:
        module = (needed - seen).pop()
        seen.add(module)
        source = ROOT / "src" / "containment_demo" / f"{module}.py"
        if source.exists():
            needed |= _imported_modules(source)
    missing = sorted(seen - copied)
    assert not missing, f"src/services/Dockerfile does not COPY: {missing}"


def test_service_image_copy_layout_preserves_application_imports(tmp_path: Path) -> None:
    for line in (SERVICES / "Dockerfile").read_text().splitlines():
        if not line.startswith("COPY "):
            continue
        _, *sources, destination = shlex.split(line)
        target = tmp_path / destination
        if destination.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        for source in sources:
            path = ROOT / source
            if path.is_dir():
                shutil.copytree(path, target, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(path, target)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys; from pathlib import Path; sys.path.insert(0, str(Path.cwd())); "
            "from services.policy_api import main as policy; "
            "from services.test_receiver import main as receiver; "
            "assert all(Path(module.__file__).is_relative_to(Path.cwd()) "
            "for module in (policy, receiver)); "
            "assert policy.app and receiver.app",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
