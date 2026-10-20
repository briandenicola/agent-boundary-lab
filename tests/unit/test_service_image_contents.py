"""The tool-API image copies containment_demo files one by one; a missing one only fails
at container start. This keeps the COPY line and the services' imports in step."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _copied_modules() -> set[str]:
    text = (ROOT / "services" / "Dockerfile").read_text()
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
        p for service in ("policy_api", "test_receiver")
        for p in (ROOT / "services" / service).rglob("*.py")
    ]
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
    assert not missing, f"services/Dockerfile does not COPY: {missing}"
