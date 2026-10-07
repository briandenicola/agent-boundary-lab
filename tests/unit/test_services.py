"""Guards on the two controlled endpoints.

The receiver is the witness for the negative half of the demo: a denial is attributable
because no receipt exists for a run the agent's traces show it attempted. That only
holds if the receiver accepts everything it is given and never logs anything it was not
given, so both properties are tested here rather than assumed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from services.policy_api import main as policy_api
from services.test_receiver import main as test_receiver

RUN_ID = "run-00000000-0000-0000-0000-000000000001"


class LogCapture(logging.Handler):
    """Collects the JSON receipt lines a service emits."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[dict[str, Any]] = []
        self.raw: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        self.raw.append(message)
        try:
            self.records.append(json.loads(message))
        except json.JSONDecodeError:
            pass


@pytest.fixture
def receiver_logs() -> Any:
    capture = LogCapture()
    test_receiver.logger.addHandler(capture)
    yield capture
    test_receiver.logger.removeHandler(capture)


@pytest.fixture
def policy_logs() -> Any:
    capture = LogCapture()
    policy_api.logger.addHandler(capture)
    yield capture
    policy_api.logger.removeHandler(capture)


@pytest.fixture
def receiver() -> TestClient:
    return TestClient(test_receiver.app)


@pytest.fixture
def policy() -> TestClient:
    return TestClient(policy_api.app)


class TestReceiverNeverRejects:
    """A rejection here would be indistinguishable from a platform denial."""

    @pytest.mark.parametrize(
        "payload",
        [
            b"",
            b"not json at all",
            json.dumps({"demo": "record"}).encode(),
            b"x" * 100_000,
        ],
        ids=["empty", "malformed", "json", "large"],
    )
    def test_everything_is_accepted(self, receiver: TestClient, payload: bytes) -> None:
        response = receiver.post("/ingest", content=payload, headers={"X-Demo-Run-Id": RUN_ID})
        assert response.status_code == 202, (
            "the receiver rejected a request on its own judgement; that is "
            "indistinguishable from a platform denial and invalidates the evidence"
        )

    def test_a_missing_run_marker_is_still_accepted(self, receiver: TestClient) -> None:
        assert receiver.post("/ingest", content=b"{}").status_code == 202


class TestReceiverStoresNoContent:
    def test_receipt_contains_only_metadata(
        self, receiver: TestClient, receiver_logs: LogCapture
    ) -> None:
        secret = "synthetic-marker-that-must-not-be-logged"
        receiver.post(
            "/ingest",
            json={"account": secret, "amount": 42},
            headers={"X-Demo-Run-Id": RUN_ID, "Authorization": "Bearer must-not-be-logged"},
        )

        assert len(receiver_logs.records) == 1
        receipt = receiver_logs.records[0]
        assert set(receipt) == {
            "service",
            "event",
            "received_at",
            "demo_run_id",
            "content_length_bytes",
        }
        rendered = " ".join(receiver_logs.raw)
        for leak in (secret, "Bearer", "must-not-be-logged", "account"):
            assert leak not in rendered, f"{leak!r} was retained by the receiver"

    def test_response_body_does_not_echo_the_payload(self, receiver: TestClient) -> None:
        secret = "synthetic-marker-that-must-not-be-echoed"
        response = receiver.post(
            "/ingest", json={"account": secret}, headers={"X-Demo-Run-Id": RUN_ID}
        )
        assert secret not in response.text


class TestReceiptsAreAttributable:
    def test_run_marker_from_header_is_recorded(
        self, receiver: TestClient, receiver_logs: LogCapture
    ) -> None:
        receiver.post("/ingest", content=b"{}", headers={"X-Demo-Run-Id": RUN_ID})
        assert receiver_logs.records[0]["demo_run_id"] == RUN_ID

    def test_run_marker_from_query_string_is_recorded(
        self, receiver: TestClient, receiver_logs: LogCapture
    ) -> None:
        receiver.post(f"/ingest?demo_run_id={RUN_ID}", content=b"{}")
        assert receiver_logs.records[0]["demo_run_id"] == RUN_ID

    def test_health_probes_are_not_receipts(
        self, receiver: TestClient, receiver_logs: LogCapture
    ) -> None:
        """If probes logged receipts, 'no receipt' would stop meaning 'nothing arrived'."""
        for _ in range(3):
            assert receiver.get("/healthz").status_code == 200
        assert receiver_logs.records == []

    def test_policy_health_probes_are_not_receipts(
        self, policy: TestClient, policy_logs: LogCapture
    ) -> None:
        policy.get("/healthz")
        assert policy_logs.records == []


class TestPolicyApi:
    def test_policy_is_served_with_the_run_marker(
        self, policy: TestClient, policy_logs: LogCapture
    ) -> None:
        response = policy.get("/policy", headers={"X-Demo-Run-Id": RUN_ID})
        assert response.status_code == 200
        body = response.json()
        assert body["demo_run_id"] == RUN_ID
        assert body["policy"]["policy_id"] == "SVC-DEMO-0001"
        assert policy_logs.records[0]["demo_run_id"] == RUN_ID

    def test_policy_payload_is_synthetic(self, policy: TestClient) -> None:
        rendered = json.dumps(policy_api.SERVICING_POLICY).lower()
        assert "synthetic" in rendered
        for forbidden in ("ssn", "customer", "password", "secret", "token"):
            assert forbidden not in rendered


class TestDistinctHosts:
    def test_the_two_services_expose_different_paths(self) -> None:
        """A shared path would make the two destinations easy to confuse in evidence."""
        policy_paths = {r.path for r in policy_api.app.routes if hasattr(r, "path")}
        receiver_paths = {r.path for r in test_receiver.app.routes if hasattr(r, "path")}
        assert "/policy" in policy_paths
        assert "/ingest" in receiver_paths
        assert policy_paths & receiver_paths == {"/healthz"}
