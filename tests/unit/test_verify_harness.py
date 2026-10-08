"""Tests for the verification harness's own judgement calls.

The harness decides what counts as evidence. Those decisions are pure functions on
purpose, because the cases that matter most are the ones that are hardest to produce on
demand against live infrastructure: a destination returning its own 403, and a receipt
landing with no usable marker.

The case this module exists for: **an empty result set is not "nothing arrived."** A
receipt with `demo_run_id == ""` was observed in `ContainerAppConsoleLogs_CL` on
2026-10-08 (docs/telemetry-map.md §3.2). If the harness ever reads "no rows for our run
id" as a platform block, it has committed exactly the error this repository exists to
prevent.

No network, no Azure, no credentials: every function here is pure.
"""

from __future__ import annotations

import httpx
import pytest
from scripts.verify_demo import (
    Attempt,
    FailureMode,
    ReceiptEvidence,
    Status,
    classify,
    classify_receipt_absence,
    judge_own_rejection,
    roll_up,
)


def _row(service: str = "test-receiver", run_id: str = "") -> dict[str, str]:
    return {"service": service, "demo_run_id": run_id, "received_at": "2026-10-08T17:00:00Z"}


class TestReceiptAbsenceIsNotAutomaticallyAProof:
    def test_rows_carrying_our_marker_mean_the_call_was_not_blocked(self) -> None:
        status, evidence, _ = classify_receipt_absence(
            query_available=True,
            rows_for_run=[_row(run_id="run-1")],
            unattributed_rows=[],
            any_rows_in_window=True,
            retrievability_proven_in_window=True,
        )
        assert status is Status.FAIL
        assert evidence is ReceiptEvidence.ARRIVED_FOR_THIS_RUN

    def test_an_unattributed_arrival_is_inconclusive_not_a_block(self) -> None:
        # The whole point. Rows exist, none carry our marker. That is not "nothing
        # arrived" — it may be our own request with the marker stripped in transit.
        status, evidence, detail = classify_receipt_absence(
            query_available=True,
            rows_for_run=[],
            unattributed_rows=[_row()],
            any_rows_in_window=True,
            retrievability_proven_in_window=True,
        )
        assert status is Status.INCONCLUSIVE
        assert evidence is ReceiptEvidence.ARRIVED_UNATTRIBUTED
        assert "empty demo_run_id" in detail

    def test_an_unattributed_arrival_outranks_proven_retrievability(self) -> None:
        # A healthy pipeline does not make an unattributable arrival attributable.
        status, _, _ = classify_receipt_absence(
            query_available=True,
            rows_for_run=[],
            unattributed_rows=[_row(), _row()],
            any_rows_in_window=True,
            retrievability_proven_in_window=True,
        )
        assert status is not Status.PASS

    def test_no_rows_without_proven_retrievability_is_inconclusive(self) -> None:
        status, evidence, detail = classify_receipt_absence(
            query_available=True,
            rows_for_run=[],
            unattributed_rows=[],
            any_rows_in_window=False,
            retrievability_proven_in_window=False,
        )
        assert status is Status.INCONCLUSIVE
        assert evidence is ReceiptEvidence.NO_ROWS_IN_WINDOW
        assert "absent pipeline" in detail

    def test_no_rows_with_proven_retrievability_is_the_only_passing_case(self) -> None:
        status, evidence, _ = classify_receipt_absence(
            query_available=True,
            rows_for_run=[],
            unattributed_rows=[],
            any_rows_in_window=False,
            retrievability_proven_in_window=True,
        )
        assert status is Status.PASS
        assert evidence is ReceiptEvidence.NO_ROWS_IN_WINDOW

    def test_an_unavailable_query_is_inconclusive_never_a_pass(self) -> None:
        status, evidence, _ = classify_receipt_absence(
            query_available=False,
            rows_for_run=[],
            unattributed_rows=[],
            any_rows_in_window=False,
            retrievability_proven_in_window=True,
        )
        assert status is Status.INCONCLUSIVE
        assert evidence is ReceiptEvidence.QUERY_UNAVAILABLE

    def test_every_non_passing_case_is_distinguishable(self) -> None:
        # Four causes, four labels. Collapsing any two of them loses the distinction the
        # Enforced run depends on.
        seen = {
            classify_receipt_absence(
                query_available=available,
                rows_for_run=for_run,
                unattributed_rows=unattributed,
                any_rows_in_window=bool(for_run or unattributed),
                retrievability_proven_in_window=True,
            )[1]
            for available, for_run, unattributed in (
                (False, [], []),
                (True, [_row(run_id="run-1")], []),
                (True, [], [_row()]),
                (True, [], []),
            )
        }
        assert seen == set(ReceiptEvidence)


class TestQueryErrorsAreNotEmptyResultSets:
    """A failed query and a genuinely empty window must never look the same.

    If they do, every "no receipt" conclusion silently inherits every outage.
    """

    def test_an_exception_is_reported_as_a_failure_not_as_ok(self) -> None:
        from scripts.verify_demo import LogQuery, _run_query

        class Exploding:
            def query_workspace(self, *args: object, **kwargs: object) -> None:
                raise RuntimeError("workspace unreachable")

        rows, reason = _run_query(LogQuery(Exploding(), "workspace-id", "ready"), "X", _window())
        assert rows == []
        assert reason != "ok"
        assert "query failed" in reason

    def test_an_unavailable_client_reports_its_reason(self) -> None:
        from scripts.verify_demo import LogQuery, _run_query

        rows, reason = _run_query(LogQuery(None, None, "no workspace id"), "X", _window())
        assert rows == []
        assert reason == "no workspace id"

    def test_an_unsafe_run_id_is_never_interpolated_into_a_query(self) -> None:
        from scripts.verify_demo import LogQuery, query_receipts_for_run

        class Exploding:
            def query_workspace(self, *args: object, **kwargs: object) -> None:
                raise AssertionError("a malformed run id must not reach the query")

        rows, reason = query_receipts_for_run(
            LogQuery(Exploding(), "workspace-id", "ready"),
            ["app"],
            'x" or true //',
            _window(),
        )
        assert rows == []
        assert "not safe" in reason


def _window() -> tuple:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return (now, now)


class TestDestinationOwnRejection:
    @pytest.mark.parametrize("status_code", [401, 403, 407])
    def test_a_destinations_own_rejection_fails_the_baseline(self, status_code: int) -> None:
        # docs/egress-control.md §6: the egress proxy denies with 403 and so can a
        # destination. If the receiver ever rejects by itself, a later 403 from inside
        # the sandbox is unattributable.
        status, detail = judge_own_rejection(
            Attempt(url="https://r.example.net/ingest", method="POST", status_code=status_code)
        )
        assert status is Status.FAIL
        assert "NOT be attributable" in detail

    def test_an_accepted_request_passes(self) -> None:
        status, _ = judge_own_rejection(
            Attempt(url="https://r.example.net/ingest", method="POST", status_code=202)
        )
        assert status is Status.PASS

    @pytest.mark.parametrize("status_code", [None, 500, 404])
    def test_anything_else_is_inconclusive(self, status_code: int | None) -> None:
        status, _ = judge_own_rejection(
            Attempt(
                url="https://r.example.net/ingest",
                method="POST",
                status_code=status_code,
                error="boom" if status_code is None else None,
            )
        )
        assert status is Status.INCONCLUSIVE


class TestFailureKindsAreNeverCollapsed:
    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (httpx.ConnectTimeout("timed out"), FailureMode.TIMEOUT),
            (httpx.ReadTimeout("timed out"), FailureMode.TIMEOUT),
            (
                httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] bad cert"),
                FailureMode.TLS_ERROR,
            ),
            (
                httpx.ConnectError("[Errno -2] Name or service not known"),
                FailureMode.DNS_ERROR,
            ),
            (httpx.ConnectError("Connection refused"), FailureMode.CONNECTION_ERROR),
            (ValueError("something else"), FailureMode.UNEXPECTED),
        ],
    )
    def test_each_transport_failure_keeps_its_own_kind(
        self, exc: Exception, expected: FailureMode
    ) -> None:
        assert classify(exc) is expected

    def test_no_failure_mode_claims_a_policy_decision(self) -> None:
        # The harness observes; it does not adjudicate. A "denied" category here would
        # let a client-side symptom masquerade as a platform decision.
        assert not any("deny" in m or "denied" in m or "block" in m for m in FailureMode)


class TestRollUp:
    def test_a_single_inconclusive_blocks_a_pass(self) -> None:
        assert roll_up(_checks(Status.PASS, Status.INCONCLUSIVE)) is Status.INCONCLUSIVE

    def test_a_failure_outranks_everything(self) -> None:
        assert roll_up(_checks(Status.PASS, Status.INCONCLUSIVE, Status.FAIL)) is Status.FAIL

    def test_not_implemented_can_never_roll_up_to_a_pass(self) -> None:
        assert roll_up(_checks(Status.PASS, Status.NOT_IMPLEMENTED)) is Status.NOT_IMPLEMENTED

    def test_no_checks_at_all_is_inconclusive(self) -> None:
        assert roll_up([]) is Status.INCONCLUSIVE


def _checks(*statuses: Status) -> list:
    from scripts.verify_demo import Check, RunKind

    return [
        Check(
            id=f"c{i}",
            title="t",
            status=status,
            run_kind=RunKind.LOCAL_CONTROL_CLIENT,
            detail="d",
        )
        for i, status in enumerate(statuses)
    ]
