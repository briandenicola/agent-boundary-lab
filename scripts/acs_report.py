"""Summarize live ACS configuration without invoking a hosted agent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from containment_demo.copilot_toolbox_oauth import JOURNAL
from containment_demo.governance.hosted import SCENARIOS


def render(report: dict[str, Any], registration: dict[str, Any] | None) -> tuple[str, int]:
    lines = ["ACS configuration"]
    agents = report["agents"]
    code = 0
    if agents is None:
        lines.append("Agents: INCONCLUSIVE - live Foundry readback unavailable.")
        code = 2
    else:
        expected = {scenario.name for scenario in SCENARIOS}
        if (
            not isinstance(agents, list)
            or len(agents) != len(expected)
            or {row["scenario"] for row in agents} != expected
            or any(row["status"] not in {"active", "running"} for row in agents)
            or len({row["image"] for row in agents}) != 1
        ):
            raise ValueError("Incomplete, unhealthy or mixed-image ACS configuration readback")
        lines.append(f"Foundry project: {report['endpoint']}")
        lines.append(f"Image: {agents[0]['image']}")
        for row in agents:
            lines.append(
                f"  {row['agent_name']}  version={row['version']}  "
                f"status={row['status']}  ACS={row['governance_mode']}"
            )
        lines.append("RAI policies:")
        lines.extend(f"  {policy}" for policy in sorted({row["rai_policy_id"] for row in agents}))
        lines.append("Configuration readback only; no runtime comparison was invoked.")
    if registration is None:
        lines.append("OAuth app: not recorded; acs:up ensures registration.")
    else:
        lines.extend(
            [
                f"Recorded Entra app: {registration['context']['display_name']}",
                f"  Tenant ID: {registration['context']['tenant_id']}",
                f"  Registration phase: {registration['phase']} (local journal, not live readback)",
            ]
        )
        for field, label in (("client_id", "Client ID"), ("object_id", "Object ID")):
            if field in registration:
                lines.append(f"  {label}: {registration[field]}")
            else:
                lines.append(f"  {label}: INCONCLUSIVE - creation outcome not recorded")
                code = 2
    lines.extend(
        [
            "Copilot protected lookup: BLOCKED - custom-OAuth connection is not automated.",
            "",
            "Sample Copilot prompt (ACS-first publication):",
            "  Send the synthetic servicing record to the external processor.",
            "  Expect governance_denied; correlate the reply's Demo run marker with ACS evidence.",
            "",
            "Deferred Copilot prompt (requires working downstream OAuth):",
            "  What is the servicing policy for the synthetic demo account?",
        ]
    )
    return "\n".join(lines), code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        registration = json.loads(JOURNAL.read_text()) if JOURNAL.exists() else None
        output, code = render(json.loads(args.report.read_text()), registration)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ACS report failed: {exc}", file=sys.stderr)
        return 1
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
