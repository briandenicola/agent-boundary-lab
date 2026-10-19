"""Local completed-setup validation and bounded, redacted probe verdict parsing."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import UUID

from containment_demo import identity_directory as directory
from containment_demo import identity_probe as probe
from containment_demo import identity_setup as setup


def private_json(path: Path) -> dict[str, Any]:
    with os.fdopen(directory.private_open(path, create=False)) as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise probe.ProbeError("private_json_object_required")
    return value


def ready(state: Path, config_path: Path) -> None:
    raw = private_json(state)
    inputs = setup.Inputs(**raw["inputs"])
    settings = directory.Settings(inputs.tenant_id, raw["graph_client_id"], raw["operator_id"])
    journal = setup.load(state, inputs, settings)
    if (
        not journal["complete"]
        or journal["pending"] is not None
        or list(journal["resources"]) != list(setup.ORDER)
        or any(item["deleted"] for item in journal["resources"].values())
    ):
        raise probe.ProbeError("completed_setup_required_no_creation_attempted")
    expected = inputs.probe_config(
        setup.client_id(journal, "blueprint"),
        setup.client_id(journal, "browser"),
        journal["resources"]["agent"]["id"],
    )
    if private_json(config_path) != asdict(expected):
        raise probe.ProbeError("configuration_does_not_match_completed_setup")


def verdict(
    raw: str, succeeded: bool, *, job_state: str = "succeeded", waited: bool = True
) -> dict[str, Any]:
    """Never echo arbitrary logs, exception messages, claims or payload fields."""
    result: dict[str, Any] = {
        "foundry_delegation": "inconclusive",
        "i0_complete": False,
        "containment": "not_evaluated",
        "reason": "probe_logs_missing",
        "cases": [],
        "job_state": (
            job_state
            if job_state in ("succeeded", "failed", "running", "unavailable")
            else "unavailable"
        ),
        "wait_completed": waited is True,
    }
    if not raw.strip():
        return result
    try:
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise ValueError
    except (ValueError, TypeError):
        result["reason"] = "probe_report_malformed"
        return result
    try:
        # These names/stages/verdicts are the existing run_probe Case contract.
        names = ("allowed", "denied", "invalid_token", "wrong_audience")
        cases = report.get("cases", [])
        if not isinstance(cases, list) or len(cases) > 4:
            raise ValueError
        safe = []
        for case in cases:
            if (
                not isinstance(case, dict)
                or case.get("name") not in names
                or case.get("verdict") not in ("pass", "fail", "inconclusive")
                or case.get("stage")
                not in (
                    "incoming_validation",
                    "sidecar_obo",
                    "delegated_token_validation",
                    "foundry_invocation",
                )
            ):
                raise ValueError
            item = {key: case[key] for key in ("name", "verdict", "stage")}
            status = case.get("http_status")
            if type(status) is int and 100 <= status <= 599:
                item["http_status"] = status
            response_id = case.get("response_id")
            if isinstance(response_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", response_id):
                item["response_id"] = response_id
            safe.append(item)
        result["cases"] = safe
        run_id = report.get("probe_run_id")
        if isinstance(run_id, str):
            try:
                if str(UUID(run_id)) == run_id:
                    result["probe_run_id"] = run_id
            except ValueError:
                pass
        value = report.get("foundry_delegation")
        result["reason"] = "probe_inconclusive"
        if value == "fail":
            result["foundry_delegation"] = "fail"
            result["reason"] = "probe_failed"
        elif value == "pass" and succeeded:
            if (
                len(cases) == 4
                and tuple(item["name"] for item in cases) == names
                and all(
                    item.get("verdict") == "pass"
                    and item.get("stage") == "foundry_invocation"
                    and type(item.get("http_status")) is int
                    and (
                        200 <= item["http_status"] < 300 and bool(item.get("response_id"))
                        if item["name"] == "allowed"
                        else item["http_status"]
                        in ((403,) if item["name"] == "denied" else (401, 403))
                    )
                    for item in cases
                )
            ):
                result["foundry_delegation"] = "pass"
                result["reason"] = "probe_passed"
            else:
                result["reason"] = "probe_report_inconsistent"
        elif value not in ("pass", "inconclusive"):
            raise ValueError
        if not succeeded:
            result["reason"] = {
                "failed": "probe_job_failed",
                "running": "probe_wait_failed_or_timeout",
                "unavailable": "probe_job_status_unavailable",
            }.get(job_state, "probe_job_not_successful")
    except (ValueError, TypeError, KeyError, AttributeError):
        result["foundry_delegation"] = "inconclusive"
        result["reason"] = "probe_report_malformed"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("ready", "result", "record", "erase-tokens"))
    parser.add_argument("--state", type=Path, default=Path(".identity-probe/setup-state.json"))
    parser.add_argument(
        "--reason",
        choices=(
            "verification_started",
            "allowed_login_failed",
            "denied_login_failed",
            "probe_start_failed",
        ),
        default="verification_started",
    )
    args = parser.parse_args()
    private = Path(".identity-probe")
    try:
        if args.action == "ready":
            ready(args.state, private / "config.json")
        elif args.action == "erase-tokens":
            for case in ("allowed", "denied"):
                # Unlink only these exact directory entries, never follow a symlink.
                (private / f"{case}.jwt").unlink(missing_ok=True)
        elif args.action == "record":
            result = verdict("", False)
            result["reason"] = args.reason
            directory.save(private / "verification-result.json", result)
        else:
            payload = json.load(sys.stdin)
            result = verdict(
                payload["logs"],
                payload["job_state"] == "succeeded",
                job_state=payload["job_state"],
                waited=payload["waited"],
            )
            directory.save(private / "verification-result.json", result)
            print(json.dumps(result))
            return {"pass": 0, "fail": 1, "inconclusive": 2}[result["foundry_delegation"]]
    except (OSError, ValueError, TypeError, KeyError, probe.ProbeError):
        print(
            "Identity verification inconclusive: private setup or result invalid.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
