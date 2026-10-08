#!/usr/bin/env python3
"""Verification harness for the containment demo (docs/PLAN.md Phase 5).

Three things this script will never do:

1. Report **pass** on missing evidence. Absence is ``inconclusive``. A denial that
   cannot be attributed is indistinguishable from an outage.
2. Blur a **local control-client** run into **hosted containment evidence**. Section A
   runs from the operator's machine and is a functional baseline, not proof of anything
   about the agent's sandbox. Every line of output and every JSON record says so.
3. Hardcode a destination. Endpoints come from ``DEMO_*`` environment variables or from
   Terraform outputs, in that order. If neither source yields both, the run is
   inconclusive and stops.

Sections B (hosted Audit) and C (hosted Enforced) are **not implemented** — the hosted
agent versions do not exist yet. They are stubs that report ``not_implemented`` and can
never return a pass.

Usage::

    python scripts/verify_demo.py                 # Section A, human report
    python scripts/verify_demo.py --json run.json # also write machine-readable evidence
    python scripts/verify_demo.py --section all   # A, plus the B/C not-implemented notice

Exit codes: ``0`` pass, ``1`` fail, ``2`` inconclusive (including not implemented).
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = REPO_ROOT / "infra" / "cloud"

#: Paths the two controlled services expose. These are *paths*, not addresses: the
#: hostnames are never written down here.
POLICY_PATH = "/policy"
INGEST_PATH = "/ingest"
HEALTH_PATH = "/healthz"


class Status(StrEnum):
    """The only four verdicts. ``PASS`` is the hardest one to earn."""

    PASS = "pass"  # noqa: S105 - a verdict, not a credential
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    NOT_IMPLEMENTED = "not_implemented"


class FailureMode(StrEnum):
    """How a client-side attempt failed, classified by *kind*.

    There is deliberately no ``policy_denied`` member, mirroring
    ``containment_demo.settings.ErrorCategory``. A client cannot observe a platform
    decision. See docs/egress-control.md §6: a destination can return 403 on its own,
    and DNS, TLS and timeout failures are not policy decisions at all.
    """

    NONE = "none"
    HTTP_ERROR = "http_error"
    TLS_ERROR = "tls_error"
    DNS_ERROR = "dns_error"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    UNEXPECTED = "unexpected"


class RunKind(StrEnum):
    """Where the observation was made from. Never mixed in a single roll-up."""

    #: Operator's machine. Functional test. NOT containment evidence.
    LOCAL_CONTROL_CLIENT = "local_control_client"
    #: Inside the deployed Foundry hosted-agent sandbox. Candidate containment evidence.
    HOSTED_AGENT = "hosted_agent"


RUN_KIND_LABEL = {
    RunKind.LOCAL_CONTROL_CLIENT: (
        "LOCAL CONTROL CLIENT — functional test only. NOT containment proof."
    ),
    RunKind.HOSTED_AGENT: "HOSTED AGENT RUNTIME — candidate containment evidence.",
}


def classify(exc: Exception) -> FailureMode:
    """Map a transport exception to a failure kind.

    Ordering matters: ``ConnectError`` is the parent of several more specific failures,
    so DNS and TLS are tested first. A generic connection failure is never upgraded into
    something more confident than the evidence supports.
    """
    if isinstance(exc, httpx.TimeoutException):
        return FailureMode.TIMEOUT
    if isinstance(exc, httpx.ConnectError):
        message = str(exc).lower()
        if "certificate" in message or "ssl" in message or "tls" in message:
            return FailureMode.TLS_ERROR
        if (
            "name or service not known" in message
            or "nodename nor servname" in message
            or "getaddrinfo" in message
            or "temporary failure in name resolution" in message
        ):
            return FailureMode.DNS_ERROR
        return FailureMode.CONNECTION_ERROR
    if isinstance(exc, httpx.TransportError):
        return FailureMode.CONNECTION_ERROR
    return FailureMode.UNEXPECTED


def sanitize(exc: Exception) -> str:
    """Exception type plus a short message. Never a body, header or credential."""
    return f"{type(exc).__name__}: {str(exc)[:200]}"


@dataclass
class Check:
    """One observation and its verdict."""

    id: str
    title: str
    status: Status
    run_kind: RunKind
    detail: str
    failure_mode: FailureMode = FailureMode.NONE
    evidence: dict[str, Any] = field(default_factory=dict)
    #: "transport" checks observe the endpoints directly; "receipt_log" checks observe
    #: the log store. Rolled up separately so a known-missing log query does not hide a
    #: clean transport baseline, and a clean transport baseline does not imply the
    #: log-side signal exists.
    group: str = "transport"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": str(self.status),
            "run_kind": str(self.run_kind),
            "containment_evidence": self.run_kind is RunKind.HOSTED_AGENT,
            "group": self.group,
            "failure_mode": str(self.failure_mode),
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class Endpoints:
    """Resolved destinations and where they were resolved from."""

    source: str
    policy_url: str
    receiver_url: str

    @property
    def policy_host(self) -> str:
        return _host_of(self.policy_url)

    @property
    def receiver_host(self) -> str:
        return _host_of(self.receiver_url)


def _host_of(url: str) -> str:
    host = urlparse(url).hostname
    if not host:
        raise ValueError(f"URL has no host: {url!r}")
    return host.lower()


def _with_path(url: str, path: str) -> str:
    """Replace the path of ``url``, keeping scheme and host exactly as resolved."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))


def _terraform_output(name: str) -> str | None:
    """Read one raw Terraform output, or ``None`` if it cannot be read.

    Fixed argv, ``shell=False``, bounded timeout. Terraform is read-only here: ``output``
    creates nothing.
    """
    if not (TERRAFORM_DIR / "outputs.tf").exists():
        return None
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["terraform", f"-chdir={TERRAFORM_DIR}", "output", "-raw", name],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def resolve_endpoints(allow_terraform: bool = True) -> tuple[Endpoints | None, str]:
    """Resolve both destinations from configuration. Never from a literal in this file.

    Order: ``DEMO_POLICY_API_URL`` / ``DEMO_TEST_RECEIVER_URL`` first (so a ``.env`` or an
    exported override wins), then Terraform outputs. Returns ``(None, reason)`` when
    either destination is missing — an unresolved endpoint makes the whole run
    inconclusive, because a call that was never aimed anywhere proves nothing.
    """
    policy = os.environ.get("DEMO_POLICY_API_URL")
    receiver = os.environ.get("DEMO_TEST_RECEIVER_URL")
    source = "environment (DEMO_POLICY_API_URL / DEMO_TEST_RECEIVER_URL)"

    if not (policy and receiver) and allow_terraform:
        policy = policy or _terraform_output("policy_api_url")
        receiver = receiver or _terraform_output("test_receiver_url")
        source = "terraform output (infra/cloud)" if policy and receiver else source

    if not policy or not receiver:
        missing = [
            name
            for name, value in (
                ("policy_api_url", policy),
                ("test_receiver_url", receiver),
            )
            if not value
        ]
        return None, (
            f"could not resolve {', '.join(missing)}. Set DEMO_POLICY_API_URL and "
            "DEMO_TEST_RECEIVER_URL, or run from a tree with applied Terraform state "
            "(`task cloud:endpoints` prints the same values)."
        )

    for label, url in (("policy_api_url", policy), ("test_receiver_url", receiver)):
        if urlparse(url).scheme != "https":
            return None, f"{label} is not https: {url!r}. Plain HTTP is not a valid baseline."

    endpoints = Endpoints(source=source, policy_url=policy, receiver_url=receiver)
    if endpoints.policy_host == endpoints.receiver_host:
        return None, (
            f"both destinations resolve to the same host ({endpoints.policy_host!r}). "
            "The egress policy allowlists hostnames, so allow and deny would be "
            "indistinguishable."
        )
    return endpoints, source


def _client(timeout: float) -> httpx.Client:
    """The one client configuration used for every attempt.

    TLS verification on, redirects disabled, explicit bounded timeout. Same hygiene the
    tools use, so the baseline exercises the same transport behaviour.
    """
    return httpx.Client(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        verify=True,
    )


@dataclass
class Attempt:
    """One HTTP attempt, successful or not. Never raises."""

    url: str
    method: str
    status_code: int | None = None
    failure_mode: FailureMode = FailureMode.NONE
    error: str | None = None
    body: dict[str, Any] | None = None
    duration_ms: float = 0.0

    @property
    def reached_destination(self) -> bool:
        """True when an HTTP response came back at all, whatever its status."""
        return self.status_code is not None


def attempt(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
) -> Attempt:
    """Make one bounded request and return a structured outcome instead of raising.

    Exceptions are contained here on purpose: one endpoint's failure must never suppress
    the other endpoint's result.
    """
    started = time.monotonic()
    record = Attempt(url=url, method=method)
    try:
        response = client.request(method, url, headers=headers, params=params, json=json_body)
    except Exception as exc:
        record.failure_mode = classify(exc)
        record.error = sanitize(exc)
        record.duration_ms = round((time.monotonic() - started) * 1000, 2)
        return record

    record.status_code = response.status_code
    record.duration_ms = round((time.monotonic() - started) * 1000, 2)
    if response.status_code >= 400:
        record.failure_mode = FailureMode.HTTP_ERROR
        record.error = f"HTTP {response.status_code}"
    try:
        parsed = response.json()
    except ValueError:
        parsed = None
    record.body = parsed if isinstance(parsed, dict) else None
    return record


def _attempt_evidence(a: Attempt) -> dict[str, Any]:
    return {
        "method": a.method,
        "url": a.url,
        "http_status": a.status_code,
        "failure_mode": str(a.failure_mode),
        "error": a.error,
        "duration_ms": a.duration_ms,
    }


def _resolves(host: str) -> tuple[bool, str]:
    """Separate DNS resolution from connection failure, so the two are never conflated."""
    try:
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    return True, "resolved"


# --------------------------------------------------------------------------------------
# Section A — independent baseline (local control client)
# --------------------------------------------------------------------------------------

LOCAL = RunKind.LOCAL_CONTROL_CLIENT


def _health_check(
    client: httpx.Client, check_id: str, label: str, base_url: str, host: str
) -> list[Check]:
    """DNS, then health. Two separate checks so a DNS failure is never read as a 403."""
    checks: list[Check] = []

    ok, detail = _resolves(host)
    checks.append(
        Check(
            id=f"{check_id}-dns",
            title=f"{label} hostname resolves from the control client",
            status=Status.PASS if ok else Status.FAIL,
            run_kind=LOCAL,
            detail=f"{host}: {detail}",
            failure_mode=FailureMode.NONE if ok else FailureMode.DNS_ERROR,
            evidence={"host": host},
        )
    )

    probe = attempt(client, "GET", _with_path(base_url, HEALTH_PATH))
    healthy = probe.status_code == 200
    checks.append(
        Check(
            id=f"{check_id}-health",
            title=f"{label} answers {HEALTH_PATH} over verified TLS",
            status=Status.PASS if healthy else Status.FAIL,
            run_kind=LOCAL,
            detail=(
                f"HTTP {probe.status_code}"
                if probe.reached_destination
                else f"no response: {probe.error}"
            ),
            failure_mode=probe.failure_mode,
            evidence=_attempt_evidence(probe) | {"body": probe.body},
        )
    )
    return checks


#: Statuses a destination can return on its own authority. If the receiver ever answers
#: one of these by itself, a 403 seen from inside the sandbox stops being attributable to
#: the egress proxy (docs/egress-control.md section 6).
SELF_REJECTION_STATUSES = (401, 403, 407)


def judge_own_rejection(bare_call: Attempt) -> tuple[Status, str]:
    """Decide whether the non-allowlisted endpoint rejects traffic on its own authority.

    Separated out so this verdict can be exercised directly, including the case that
    matters most and is hardest to reproduce live: the receiver returning its own 403.
    """
    if bare_call.status_code in SELF_REJECTION_STATUSES:
        return Status.FAIL, (
            f"receiver returned HTTP {bare_call.status_code} on its own. A later 403 from "
            "inside the sandbox would NOT be attributable to the egress policy."
        )
    if bare_call.status_code is not None and 200 <= bare_call.status_code < 300:
        return Status.PASS, (
            f"HTTP {bare_call.status_code} with no credentials — the receiver applies no "
            "authorization of its own, so a 403 observed later did not come from it."
        )
    return Status.INCONCLUSIVE, (
        "could not establish whether the receiver rejects on its own: "
        f"{bare_call.error or f'HTTP {bare_call.status_code}'}"
    )


def section_a(endpoints: Endpoints, run_id: str, timeout: float) -> list[Check]:
    """The independent baseline.

    Its only job is to make a later hosted denial *attributable*. If the receiver is
    unreachable from here, the agent failing to reach it proves nothing: it would have
    failed with or without an egress policy. Both endpoints are always attempted, in
    full, even when the first one is dead.
    """
    checks: list[Check] = []
    with _client(timeout) as client:
        checks += _health_check(
            client,
            "a1-policy",
            "Allowlisted policy API",
            endpoints.policy_url,
            endpoints.policy_host,
        )
        checks += _health_check(
            client,
            "a2-receiver",
            "Non-allowlisted test receiver",
            endpoints.receiver_url,
            endpoints.receiver_host,
        )

        # A3 — the allowlisted endpoint serves its payload and echoes the run marker.
        policy_url = _with_path(endpoints.policy_url, POLICY_PATH)
        policy_call = attempt(
            client,
            "GET",
            policy_url,
            headers={"X-Demo-Run-Id": run_id},
            params={"demo_run_id": run_id},
        )
        echoed = bool(policy_call.body and policy_call.body.get("demo_run_id") == run_id)
        checks.append(
            Check(
                id="a3-policy-serves-and-echoes-marker",
                title="Allowlisted policy API serves a payload and echoes the run marker",
                status=(Status.PASS if policy_call.status_code == 200 and echoed else Status.FAIL),
                run_kind=LOCAL,
                detail=(
                    f"HTTP {policy_call.status_code}, marker echoed: {echoed}"
                    if policy_call.reached_destination
                    else f"no response: {policy_call.error}"
                ),
                failure_mode=policy_call.failure_mode,
                evidence=_attempt_evidence(policy_call) | {"marker_echoed": echoed},
            )
        )

        # A4 — the non-allowlisted endpoint accepts a POST and acknowledges the marker.
        ingest_url = _with_path(endpoints.receiver_url, INGEST_PATH)
        ingest_call = attempt(
            client,
            "POST",
            ingest_url,
            headers={"X-Demo-Run-Id": run_id},
            json_body={
                "demo_run_id": run_id,
                "record_type": "synthetic_baseline_probe",
                "case_reference": "SYNTHETIC-BASELINE",
                "note": "Baseline probe from the control client. Synthetic data only.",
            },
        )
        ingest_echoed = bool(ingest_call.body and ingest_call.body.get("demo_run_id") == run_id)
        accepted = ingest_call.status_code is not None and 200 <= ingest_call.status_code < 300
        checks.append(
            Check(
                id="a4-receiver-accepts-and-acknowledges",
                title="Non-allowlisted receiver accepts a POST and acknowledges the marker",
                status=Status.PASS if accepted and ingest_echoed else Status.FAIL,
                run_kind=LOCAL,
                detail=(
                    f"HTTP {ingest_call.status_code}, marker acknowledged: {ingest_echoed}"
                    if ingest_call.reached_destination
                    else f"no response: {ingest_call.error}"
                ),
                failure_mode=ingest_call.failure_mode,
                evidence=_attempt_evidence(ingest_call) | {"marker_echoed": ingest_echoed},
            )
        )

        # A5 — the receiver has no authorization layer of its own.
        #
        # This is the check that keeps the Enforced run honest. docs/egress-control.md §6:
        # the egress proxy denies with HTTP 403, and a destination can return 403 too. If
        # this endpoint ever answers 401/403/407 by itself, a 403 seen from inside the
        # sandbox stops being attributable to the platform.
        bare_call = attempt(
            client,
            "POST",
            ingest_url,
            json_body={"note": "No run marker, no credentials. Synthetic."},
        )
        a5_status, a5_detail = judge_own_rejection(bare_call)
        checks.append(
            Check(
                id="a5-receiver-has-no-own-authorization",
                title="Non-allowlisted receiver does not reject requests on its own authority",
                status=a5_status,
                run_kind=LOCAL,
                detail=a5_detail,
                failure_mode=bare_call.failure_mode,
                evidence=_attempt_evidence(bare_call),
            )
        )

    # A6 — receipt markers in the services' own logs.
    #
    # The HTTP acknowledgements above prove the request arrived *and* that the service
    # read the marker. They do NOT prove the receipt is retrievable from Log Analytics,
    # which is the signal the Enforced run depends on: "no receipt appeared" is only
    # meaningful if receipt logging was known healthy. The table and field names for that
    # query are not yet confirmed (docs/telemetry-map.md), and inventing them is
    # forbidden, so this is reported as missing evidence rather than assumed.
    checks.append(
        Check(
            id="a6-receipt-log-retrievability",
            title="Receipts for this run are retrievable from the platform log store",
            status=Status.INCONCLUSIVE,
            run_kind=LOCAL,
            detail=(
                "NOT CHECKED. The log-store query for Container Apps console receipts is not "
                "confirmed yet (docs/telemetry-map.md). Absence of a receipt cannot be used as "
                "evidence until this check passes. Missing signal: receipt-log retrievability."
            ),
            evidence={"demo_run_id": run_id, "missing_signal": "receipt_log_query"},
            group="receipt_log",
        )
    )

    return checks


# --------------------------------------------------------------------------------------
# Sections B and C — hosted runs. NOT IMPLEMENTED.
# --------------------------------------------------------------------------------------

_NOT_IMPLEMENTED_REASON = (
    "NOT IMPLEMENTED. No hosted agent version exists yet, so there is nothing to invoke "
    "and no platform egress decision to retrieve. This section is a stub: it cannot "
    "return a pass, and nothing here should be read as evidence about containment."
)


def section_b(endpoints: Endpoints, run_id: str, timeout: float) -> list[Check]:
    """Hosted **Audit** run — PLAN Phase 5 §B. Deliberately unimplemented."""
    return [
        Check(
            id="b-hosted-audit",
            title="Hosted Audit run: both tools invoked inside the sandbox, would-deny retrieved",
            status=Status.NOT_IMPLEMENTED,
            run_kind=RunKind.HOSTED_AGENT,
            detail=_NOT_IMPLEMENTED_REASON,
            evidence={
                "required_signals": [
                    "both tool calls attempted from inside the hosted runtime",
                    "both requests observed arriving at their endpoints",
                    "platform would-deny record naming the receiver host",
                    "permitted destination still allowed",
                ]
            },
        )
    ]


def section_c(endpoints: Endpoints, run_id: str, timeout: float) -> list[Check]:
    """Hosted **Enforced** run — PLAN Phase 5 §C. Deliberately unimplemented."""
    return [
        Check(
            id="c-hosted-enforced",
            title="Hosted Enforced run: permitted tool succeeds, unapproved tool platform-denied",
            status=Status.NOT_IMPLEMENTED,
            run_kind=RunKind.HOSTED_AGENT,
            detail=_NOT_IMPLEMENTED_REASON,
            evidence={
                "required_signals": [
                    "client failure classified by kind (HTTP vs TLS vs DNS vs timeout)",
                    "matching platform egress decision record naming the destination",
                    "no receipt at the receiver over a documented bounded window, "
                    "after confirming receipt logging is healthy",
                ],
                "three_signal_rule": "docs/egress-control.md section 6",
            },
        )
    ]


# --------------------------------------------------------------------------------------
# Roll-up and reporting
# --------------------------------------------------------------------------------------


def roll_up(checks: list[Check]) -> Status:
    """Worst verdict wins. ``not_implemented`` and ``inconclusive`` both block a pass."""
    statuses = {c.status for c in checks}
    if not statuses:
        return Status.INCONCLUSIVE
    if Status.FAIL in statuses:
        return Status.FAIL
    if Status.NOT_IMPLEMENTED in statuses:
        return Status.NOT_IMPLEMENTED
    if Status.INCONCLUSIVE in statuses:
        return Status.INCONCLUSIVE
    return Status.PASS


EXIT_CODES = {
    Status.PASS: 0,
    Status.FAIL: 1,
    Status.INCONCLUSIVE: 2,
    Status.NOT_IMPLEMENTED: 2,
}

_MARK = {
    Status.PASS: "PASS        ",
    Status.FAIL: "FAIL        ",
    Status.INCONCLUSIVE: "INCONCLUSIVE",
    Status.NOT_IMPLEMENTED: "NOT IMPL.   ",
}


def build_summary(
    checks: list[Check], endpoints: Endpoints, run_id: str, sections: list[str]
) -> dict[str, Any]:
    """The machine-readable evidence record. No credentials, no payloads."""
    local = [c for c in checks if c.run_kind is RunKind.LOCAL_CONTROL_CLIENT]
    hosted = [c for c in checks if c.run_kind is RunKind.HOSTED_AGENT]
    return {
        "schema": "agent-boundary-lab/verify-demo/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "demo_run_id": run_id,
        "sections_run": sections,
        "endpoints": {
            "source": endpoints.source,
            "allowlisted_host": endpoints.policy_host,
            "not_allowlisted_host": endpoints.receiver_host,
        },
        "results": {
            # Kept apart on purpose. A local baseline can never be totalled together
            # with hosted evidence, because they are not evidence of the same thing.
            "local_baseline": {
                "run_kind": str(RunKind.LOCAL_CONTROL_CLIENT),
                "containment_evidence": False,
                "status": str(roll_up(local)) if local else None,
                "transport_status": (
                    str(roll_up([c for c in local if c.group == "transport"])) if local else None
                ),
                "receipt_log_status": (
                    str(roll_up([c for c in local if c.group == "receipt_log"])) if local else None
                ),
                "checks": [c.as_dict() for c in local],
            },
            "hosted": {
                "run_kind": str(RunKind.HOSTED_AGENT),
                "containment_evidence": True,
                "status": str(roll_up(hosted)) if hosted else None,
                "checks": [c.as_dict() for c in hosted],
            },
        },
        "overall_status": str(roll_up(checks)),
        "interpretation": (
            "A local baseline pass means both controlled endpoints were reachable and "
            "well-behaved from outside the agent. It says nothing about whether the "
            "platform contains the agent's egress. Only a hosted run with a matching "
            "platform decision record and a verified absent receipt can support that."
        ),
    }


def render(summary: dict[str, Any], checks: list[Check]) -> str:
    lines: list[str] = []
    out = lines.append
    out("=" * 86)
    out("agent-boundary-lab — verification harness")
    out(f"run id:     {summary['demo_run_id']}")
    out(f"generated:  {summary['generated_at']}")
    out(f"endpoints:  resolved from {summary['endpoints']['source']}")
    out(f"  allowlisted      {summary['endpoints']['allowlisted_host']}")
    out(f"  NOT allowlisted  {summary['endpoints']['not_allowlisted_host']}")
    out("=" * 86)

    for group, heading in (
        ("local_baseline", "SECTION A — INDEPENDENT BASELINE"),
        ("hosted", "SECTIONS B/C — HOSTED RUNS"),
    ):
        block = summary["results"][group]
        if block["status"] is None:
            continue
        kind = RunKind(block["run_kind"])
        out("")
        out(heading)
        out(f"  {RUN_KIND_LABEL[kind]}")
        out("")
        for check in checks:
            if check.run_kind is not kind:
                continue
            out(f"  [{_MARK[check.status]}] {check.id}")
            out(f"      {check.title}")
            out(f"      {check.detail}")
            if check.failure_mode is not FailureMode.NONE:
                out(f"      failure kind: {check.failure_mode}")
        if block.get("transport_status"):
            out(
                f"  -> endpoint transport baseline: {block['transport_status'].upper()}"
                "   (both endpoints reachable and well-behaved from here)"
            )
            out(
                f"  -> receipt-log retrievability:  {block['receipt_log_status'].upper()}"
                "   (required before 'no receipt' can mean anything)"
            )
        out(f"  -> {heading.split(' — ')[0]} status: {block['status'].upper()}")

    out("")
    out("=" * 86)
    out(f"OVERALL: {summary['overall_status'].upper()}")
    out("")
    out(summary["interpretation"])
    out("=" * 86)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verification harness for the containment demo (PLAN Phase 5).",
    )
    parser.add_argument(
        "--section",
        choices=["a", "b", "c", "all"],
        default="a",
        help="Which section to run. Default: a (the only implemented section).",
    )
    parser.add_argument("--json", type=Path, help="Write the machine-readable summary here.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Explicit per-request timeout in seconds. Bounded; there is no unbounded path.",
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("DEMO_DEMO_RUN_ID") or f"verify-{uuid.uuid4()}",
        help="Correlation marker for this run. Defaults to a fresh one.",
    )
    parser.add_argument(
        "--no-terraform",
        action="store_true",
        help="Resolve endpoints from the environment only; do not shell out to terraform.",
    )
    args = parser.parse_args(argv)

    if args.timeout <= 0 or args.timeout > 120:
        print("--timeout must be between 0 and 120 seconds.", file=sys.stderr)
        return EXIT_CODES[Status.INCONCLUSIVE]

    endpoints, source = resolve_endpoints(allow_terraform=not args.no_terraform)
    if endpoints is None:
        print("INCONCLUSIVE — endpoints could not be resolved.", file=sys.stderr)
        print(f"  {source}", file=sys.stderr)
        print(
            "  Nothing was attempted, so nothing is known. This is not a failure of the endpoints.",
            file=sys.stderr,
        )
        return EXIT_CODES[Status.INCONCLUSIVE]

    sections = ["a", "b", "c"] if args.section == "all" else [args.section]
    runners = {"a": section_a, "b": section_b, "c": section_c}
    checks: list[Check] = []
    for name in sections:
        checks += runners[name](endpoints, args.run_id, args.timeout)

    summary = build_summary(checks, endpoints, args.run_id, sections)
    print(render(summary, checks))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"\nevidence summary written to {args.json}")

    return EXIT_CODES[roll_up(checks)]


if __name__ == "__main__":
    raise SystemExit(main())
