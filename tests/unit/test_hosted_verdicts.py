"""Verdicts for the hosted Audit (B) and Enforced (C) runs.

Fixtures are the real rows quoted in docs/telemetry-map.md §0.12 (observed 2026-10-09,
audit run-2b95fdf4-…, enforced run-d6161cc4-…), reduced to the fields a verdict reads.

The rule under test: PASS, FAIL and INCONCLUSIVE are three different claims, and missing
or too-fresh evidence is INCONCLUSIVE. A client-side 403, 404, DNS error or timeout is not
an input to any of these functions.

No network, no Azure, no credentials.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from scripts import verify_demo
from scripts.verify_demo import (
    MIN_ABSENCE_WAIT_SECONDS,
    HostedEvidence,
    ReceiptEvidence,
    RunKind,
    Status,
    hosted_evidence_from_json,
    judge_hosted_audit,
    judge_hosted_enforced,
)

AUDIT_ID = "run-2b95fdf4-0570-4719-ab1d-31d5ab110967"
ENFORCED_ID = "run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4"
POLICY_HOST = "humble-phoenix-466-policy-api.kinddune-9fead02b.canadacentral.azurecontainerapps.io"
RECEIVER_HOST = (
    "humble-phoenix-466-test-receiver.kinddune-9fead02b.canadacentral.azurecontainerapps.io"
)


def _t(h: int, m: int, s: float) -> datetime:
    return datetime(2026, 10, 9, h, m, 0, tzinfo=UTC) + timedelta(seconds=s)


def _decision(
    when: datetime,
    method: str,
    host: str,
    base: str,
    run_id: str,
    result: str,
    reason: str,
    enforcement: str,
    rule: str = "",
) -> dict[str, Any]:
    path = f"/{base}/{run_id}"
    return {
        "TimeGenerated": when.isoformat(),
        "DependencyType": "NetworkEgressDecision",
        "Data": f"{method} https://{host}{path}",
        "Properties": json.dumps(
            {
                "decisionResultCode": result,
                "decisionReasonCode": reason,
                "enforcement": enforcement,
                "matchedRule": rule,
                "path": path,
            }
        ),
    }


def _receipt(service: str, run_id: str, path_base: str) -> dict[str, Any]:
    return {
        "service": service,
        "demo_run_id": run_id,
        "path": f"/{path_base}/{run_id}",
        "received_at": "2026-10-09T15:11:06.394Z",
    }


# Rows verbatim from telemetry-map §0.12 (1).
AUDIT_POLICY_ROW = _decision(
    _t(15, 11, 6.384), "GET", POLICY_HOST, "policy", AUDIT_ID,
    "Allow", "MatchedAllowRule", "Audit", "allow-policy-api",
)  # fmt: skip
AUDIT_INGEST_ROW = _decision(
    _t(15, 11, 6.439), "POST", RECEIVER_HOST, "ingest", AUDIT_ID,
    "AuditWouldDeny", "AuditWouldDefaultDeny", "Audit",
)  # fmt: skip
ENF_POLICY_ROW = _decision(
    _t(15, 13, 31.308), "GET", POLICY_HOST, "policy", ENFORCED_ID,
    "Allow", "MatchedAllowRule", "Enforced", "allow-policy-api",
)  # fmt: skip
ENF_INGEST_ROW = _decision(
    _t(15, 13, 32.626), "POST", RECEIVER_HOST, "ingest", ENFORCED_ID,
    "Deny", "DefaultDeny", "Enforced",
)  # fmt: skip


def audit_evidence(**over: Any) -> HostedEvidence:
    base: dict[str, Any] = {
        "run_id": AUDIT_ID,
        "called_at": _t(15, 11, 5).isoformat(),
        "queried_at": _t(15, 16, 6).isoformat(),
        "decisions": [AUDIT_POLICY_ROW, AUDIT_INGEST_ROW],
        "receipts": [
            _receipt("policy-api", AUDIT_ID, "policy"),
            _receipt("test-receiver", AUDIT_ID, "ingest"),
        ],
        "unattributed_receipts": [],
        "receipts_query_ok": True,
    }
    base.update(over)
    return hosted_evidence_from_json(base, "fixture")


def enforced_evidence(**over: Any) -> HostedEvidence:
    base: dict[str, Any] = {
        "run_id": ENFORCED_ID,
        "called_at": _t(15, 13, 30).isoformat(),
        # 15:17:21Z, the re-query in §0.12 (4): 3 min 49 s after the Deny row.
        "queried_at": _t(15, 17, 21).isoformat(),
        "decisions": [ENF_POLICY_ROW, ENF_INGEST_ROW],
        "receipts": [_receipt("policy-api", ENFORCED_ID, "policy")],
        "unattributed_receipts": [],
        "receipts_query_ok": True,
    }
    base.update(over)
    return hosted_evidence_from_json(base, "fixture")


def by_id(checks: list[Any]) -> dict[str, Any]:
    return {c.id: c for c in checks}


class TestTheObservedRunsGiveTheObservedVerdicts:
    def test_audit_control_passes_both_legs(self) -> None:
        checks = by_id(judge_hosted_audit(audit_evidence(), AUDIT_ID))
        assert checks["b1-audit-permitted-allowed"].status is Status.PASS
        assert checks["b2-audit-would-deny-arrived"].status is Status.PASS

    def test_enforced_run_passes_both_legs(self) -> None:
        checks = by_id(judge_hosted_enforced(enforced_evidence(), ENFORCED_ID))
        assert checks["c1-enforced-permitted-succeeded"].status is Status.PASS
        assert checks["c2-enforced-unapproved-denied"].status is Status.PASS

    def test_the_query_time_is_carried_in_the_result(self) -> None:
        c2 = by_id(judge_hosted_enforced(enforced_evidence(), ENFORCED_ID))[
            "c2-enforced-unapproved-denied"
        ]
        assert c2.evidence["queried_at"] == _t(15, 17, 21).isoformat()
        assert c2.evidence["seconds_from_call_to_query"] == pytest.approx(228.4, abs=0.1)

    def test_hosted_runs_are_labelled_hosted(self) -> None:
        for c in judge_hosted_enforced(enforced_evidence(), ENFORCED_ID):
            assert c.run_kind is RunKind.HOSTED_AGENT


class TestNoEvidenceIsInconclusiveNeverAPass:
    def test_no_evidence_at_all(self) -> None:
        for c in judge_hosted_enforced(None, ENFORCED_ID) + judge_hosted_audit(None, AUDIT_ID):
            assert c.status is Status.INCONCLUSIVE

    def test_evidence_for_a_different_run_cannot_answer_this_run(self) -> None:
        for c in judge_hosted_enforced(enforced_evidence(), "run-someone-else"):
            assert c.status is Status.INCONCLUSIVE

    def test_the_uis_own_id_is_refused(self) -> None:
        ev = enforced_evidence(run_id="ui-e73b582c569c")
        for c in judge_hosted_enforced(ev, "ui-e73b582c569c"):
            assert c.status is Status.INCONCLUSIVE
            assert "ui-" in c.detail

    def test_empty_evidence_is_inconclusive(self) -> None:
        ev = enforced_evidence(decisions=[], receipts=[])
        assert all(c.status is Status.INCONCLUSIVE for c in judge_hosted_enforced(ev, ENFORCED_ID))


class TestEnforcedDeniedNeedsBothSignals:
    def test_no_receipt_without_a_deny_row_is_not_containment(self) -> None:
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_a_deny_row_with_a_receipt_is_a_contradiction_not_a_denial(self) -> None:
        ev = enforced_evidence(
            receipts=[
                _receipt("policy-api", ENFORCED_ID, "policy"),
                _receipt("test-receiver", ENFORCED_ID, "ingest"),
            ]
        )
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.FAIL
        assert c2.evidence["receipt_evidence"] == str(ReceiptEvidence.ARRIVED_FOR_THIS_RUN)

    def test_an_allow_row_with_a_receipt_under_enforced_is_a_fail(self) -> None:
        allow = _decision(
            _t(15, 13, 32.6), "POST", RECEIVER_HOST, "ingest", ENFORCED_ID,
            "Allow", "MatchedAllowRule", "Enforced",
        )  # fmt: skip
        ev = enforced_evidence(
            decisions=[ENF_POLICY_ROW, allow],
            receipts=[
                _receipt("policy-api", ENFORCED_ID, "policy"),
                _receipt("test-receiver", ENFORCED_ID, "ingest"),
            ],
        )
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.FAIL

    def test_an_audit_mode_deny_shaped_row_is_not_an_enforced_deny(self) -> None:
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW, AUDIT_INGEST_ROW | _retarget()])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_a_deny_row_with_the_wrong_enforcement_field_is_unattributable(self) -> None:
        wrong = copy.deepcopy(ENF_INGEST_ROW)
        wrong["Properties"] = wrong["Properties"].replace("Enforced", "Audit")
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW, wrong])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_disagreeing_decision_rows_are_not_resolved_in_favour_of_the_deny(self) -> None:
        allow = _decision(
            _t(15, 13, 32.7), "POST", RECEIVER_HOST, "ingest", ENFORCED_ID,
            "Allow", "MatchedAllowRule", "Enforced",
        )  # fmt: skip
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW, ENF_INGEST_ROW, allow])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_an_unrecognised_decision_code_is_not_guessed_at(self) -> None:
        odd = copy.deepcopy(ENF_INGEST_ROW)
        odd["Properties"] = odd["Properties"].replace('"Deny"', '"Blocked"')
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW, odd])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE
        assert "not guessed" in c2.detail


class TestPermittedLegNeedsBothSignals:
    def test_a_receipt_without_a_decision_row_is_one_signal_of_two(self) -> None:
        ev = enforced_evidence(decisions=[ENF_INGEST_ROW])
        c1 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c1-enforced-permitted-succeeded"]
        assert c1.status is Status.INCONCLUSIVE
        assert "no platform decision row" in c1.detail

    def test_a_decision_row_without_a_receipt_is_one_signal_of_two(self) -> None:
        ev = enforced_evidence(receipts=[])
        c1 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c1-enforced-permitted-succeeded"]
        assert c1.status is Status.INCONCLUSIVE
        assert "no receipt" in c1.detail


def _retarget() -> dict[str, Any]:
    """Point the audit ingest row at the enforced run's path."""
    row = copy.deepcopy(AUDIT_INGEST_ROW)
    row["Data"] = row["Data"].replace(AUDIT_ID, ENFORCED_ID)
    row["Properties"] = row["Properties"].replace(AUDIT_ID, ENFORCED_ID)
    return row


class TestTheThreeMinuteRule:
    def test_reading_the_log_too_soon_is_inconclusive(self) -> None:
        ev = enforced_evidence(queried_at=_t(15, 13, 32.626 + 60).isoformat())
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE
        assert "180" in c2.detail

    def test_the_boundary_is_inclusive_of_exactly_the_minimum(self) -> None:
        ev = enforced_evidence(
            queried_at=(
                _t(15, 13, 32.626) + timedelta(seconds=MIN_ABSENCE_WAIT_SECONDS)
            ).isoformat()
        )
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.PASS

    def test_the_wait_is_measured_from_the_later_of_call_and_decision_row(self) -> None:
        # Call logged early, decision row late: counting from the call would pass this.
        ev = enforced_evidence(
            called_at=_t(15, 10, 0).isoformat(),
            queried_at=_t(15, 13, 32.626 + 100).isoformat(),
        )
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_unknown_query_time_is_inconclusive(self) -> None:
        ev = enforced_evidence(queried_at=None)
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_a_naive_timestamp_is_refused_not_assumed_utc(self) -> None:
        ev = enforced_evidence(queried_at="2026-10-09T15:17:21")
        assert ev.queried_at is None
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE


class TestAbsenceNeedsAProvenReceiptLog:
    def test_unreadable_receipt_log_is_inconclusive(self) -> None:
        ev = enforced_evidence(receipts_query_ok=False)
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_without_the_permitted_calls_receipt_there_is_no_positive_control(self) -> None:
        ev = enforced_evidence(receipts=[])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_an_unattributed_receipt_in_the_window_blocks_the_pass(self) -> None:
        ev = enforced_evidence(
            unattributed_receipts=[{"service": "test-receiver", "demo_run_id": ""}]
        )
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_never_having_asked_for_unattributed_receipts_is_inconclusive(self) -> None:
        ev = enforced_evidence(unattributed_receipts=None)
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE


class TestRunIdMatchingIsExact:
    def test_another_runs_receipt_does_not_count_as_ours(self) -> None:
        # A different run's receipt at the receiver must not turn this denial into a FAIL.
        ev = enforced_evidence(
            receipts=[
                _receipt("policy-api", ENFORCED_ID, "policy"),
                _receipt("test-receiver", AUDIT_ID, "ingest"),
            ]
        )
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.PASS

    def test_a_longer_run_id_with_our_id_as_prefix_is_not_our_decision(self) -> None:
        longer = ENFORCED_ID + "9"
        row = _decision(
            _t(15, 13, 32.626), "POST", RECEIVER_HOST, "ingest", longer,
            "Deny", "DefaultDeny", "Enforced",
        )  # fmt: skip
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW, row])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_a_row_whose_path_and_data_disagree_is_not_used(self) -> None:
        bad = copy.deepcopy(ENF_INGEST_ROW)
        bad["Data"] = bad["Data"].replace(ENFORCED_ID, AUDIT_ID)
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW, bad])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE

    def test_rows_that_are_not_egress_decisions_are_ignored(self) -> None:
        other = copy.deepcopy(ENF_INGEST_ROW)
        other["DependencyType"] = "HTTP"
        ev = enforced_evidence(decisions=[ENF_POLICY_ROW, other])
        c2 = by_id(judge_hosted_enforced(ev, ENFORCED_ID))["c2-enforced-unapproved-denied"]
        assert c2.status is Status.INCONCLUSIVE


class TestAuditControl:
    def test_would_deny_without_a_receipt_is_inconclusive(self) -> None:
        ev = audit_evidence(receipts=[_receipt("policy-api", AUDIT_ID, "policy")])
        b2 = by_id(judge_hosted_audit(ev, AUDIT_ID))["b2-audit-would-deny-arrived"]
        assert b2.status is Status.INCONCLUSIVE

    def test_a_receipt_without_a_would_deny_row_is_inconclusive(self) -> None:
        ev = audit_evidence(decisions=[AUDIT_POLICY_ROW])
        b2 = by_id(judge_hosted_audit(ev, AUDIT_ID))["b2-audit-would-deny-arrived"]
        assert b2.status is Status.INCONCLUSIVE

    def test_a_hard_deny_in_audit_mode_invalidates_the_control(self) -> None:
        deny = _decision(
            _t(15, 11, 6.4), "POST", RECEIVER_HOST, "ingest", AUDIT_ID,
            "Deny", "DefaultDeny", "Enforced",
        )  # fmt: skip
        ev = audit_evidence(decisions=[AUDIT_POLICY_ROW, deny])
        b2 = by_id(judge_hosted_audit(ev, AUDIT_ID))["b2-audit-would-deny-arrived"]
        assert b2.status is Status.FAIL

    def test_an_allow_on_the_unapproved_host_invalidates_the_control(self) -> None:
        allow = _decision(
            _t(15, 11, 6.4), "POST", RECEIVER_HOST, "ingest", AUDIT_ID,
            "Allow", "MatchedAllowRule", "Audit",
        )  # fmt: skip
        ev = audit_evidence(decisions=[AUDIT_POLICY_ROW, allow])
        b2 = by_id(judge_hosted_audit(ev, AUDIT_ID))["b2-audit-would-deny-arrived"]
        assert b2.status is Status.FAIL

    def test_a_denied_permitted_destination_is_a_fail(self) -> None:
        deny = _decision(
            _t(15, 11, 6.4), "GET", POLICY_HOST, "policy", AUDIT_ID,
            "AuditWouldDeny", "AuditWouldDefaultDeny", "Audit",
        )  # fmt: skip
        ev = audit_evidence(decisions=[deny, AUDIT_INGEST_ROW])
        b1 = by_id(judge_hosted_audit(ev, AUDIT_ID))["b1-audit-permitted-allowed"]
        assert b1.status is Status.FAIL

    def test_an_audit_row_cannot_stand_in_for_an_enforced_run(self) -> None:
        ev = audit_evidence(decisions=[ENF_POLICY_ROW | _retarget_policy(), AUDIT_INGEST_ROW])
        b1 = by_id(judge_hosted_audit(ev, AUDIT_ID))["b1-audit-permitted-allowed"]
        assert b1.status is Status.INCONCLUSIVE


def _retarget_policy() -> dict[str, Any]:
    row = copy.deepcopy(ENF_POLICY_ROW)
    row["Data"] = row["Data"].replace(ENFORCED_ID, AUDIT_ID)
    row["Properties"] = row["Properties"].replace(ENFORCED_ID, AUDIT_ID)
    return row


class TestLocalRunsAreLabelledAndCannotPass:
    def test_a_local_run_is_labelled_local_and_never_passes(self) -> None:
        ev = enforced_evidence(invoked_from="local_control_client")
        checks = judge_hosted_enforced(ev, ENFORCED_ID)
        for c in checks:
            assert c.run_kind is RunKind.LOCAL_CONTROL_CLIENT
            assert c.status is not Status.PASS
            assert not c.as_dict()["containment_evidence"]

    def test_unknown_provenance_is_not_treated_as_hosted(self) -> None:
        ev = enforced_evidence(invoked_from="somewhere-else")
        assert ev.invoked_from is RunKind.LOCAL_CONTROL_CLIENT


class TestSectionsAreNoLongerStubs:
    def test_sections_without_evidence_report_inconclusive_not_not_implemented(self) -> None:
        for fn in (verify_demo.section_b, verify_demo.section_c):
            checks = fn(None, ENFORCED_ID, 5.0, 0.0)  # type: ignore[arg-type]
            assert checks
            assert all(c.status is Status.INCONCLUSIVE for c in checks)

    def test_no_code_path_passes_on_absence_of_input(self) -> None:
        ev = enforced_evidence(decisions=[], receipts=[], receipts_query_ok=False)
        assert all(c.status is not Status.PASS for c in judge_hosted_enforced(ev, ENFORCED_ID))
