"""Tests for the two business tools.

These are the guard rails for the claims in docs/README.md. Several of them assert the
*absence* of behaviour — no hostname check, no mode branch, no disabled TLS — because
the value of this demo depends entirely on those absences.
"""

from __future__ import annotations

import inspect
import ssl

import httpx
import pytest
import respx

from containment_demo import tools
from containment_demo.settings import ErrorCategory, PolicyMode, Settings

POLICY_URL = "https://policy.example.com/policy"
RECEIVER_URL = "https://receiver.example.net/ingest"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        policy_api_url=POLICY_URL,  # type: ignore[arg-type]
        test_receiver_url=RECEIVER_URL,  # type: ignore[arg-type]
        http_timeout_seconds=5.0,
    )


class TestSuccessPaths:
    @respx.mock
    def test_policy_tool_succeeds_and_sends_run_marker(self, settings: Settings) -> None:
        route = respx.get(POLICY_URL).mock(
            return_value=httpx.Response(200, json={"policy_id": "SP-1", "tier": "standard"})
        )
        result = tools.get_servicing_policy(settings)

        assert result["succeeded"] is True
        assert result["http_status"] == 200
        assert result["error_category"] == ErrorCategory.NONE
        assert result["result"] == {"policy_id": "SP-1", "tier": "standard"}
        assert route.calls.last.request.headers["X-Demo-Run-Id"] == settings.demo_run_id

    @respx.mock
    def test_receiver_tool_posts_synthetic_record_only(self, settings: Settings) -> None:
        route = respx.post(RECEIVER_URL).mock(
            return_value=httpx.Response(202, json={"received": True})
        )
        result = tools.send_to_external_processor(settings)

        assert result["succeeded"] is True
        assert result["http_status"] == 202

        import json

        body = json.loads(route.calls.last.request.content)
        assert body["record_type"] == "synthetic_servicing_case"
        assert body["demo_run_id"] == settings.demo_run_id
        # No field may carry anything resembling customer data.
        assert set(body) == {"demo_run_id", "record_type", "case_reference", "note"}

    @respx.mock
    def test_results_carry_evidence_metadata(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={}))
        result = tools.get_servicing_policy(settings)

        for field in (
            "tool_name",
            "destination_host",
            "demo_run_id",
            "policy_mode",
            "agent_name",
            "agent_version",
            "duration_ms",
            "http_status",
            "error_category",
        ):
            assert field in result, f"evidence field {field!r} missing"
        assert result["destination_host"] == "policy.example.com"


class TestFailureClassification:
    """A failure must never be reported with more confidence than the evidence allows."""

    @respx.mock
    def test_http_403_is_an_http_error_not_a_denial(self, settings: Settings) -> None:
        """The egress proxy returns 403 — but so can the destination itself.

        The application cannot tell them apart, so it must not try. Attribution needs
        corroborating platform evidence and is the verifier's job.
        """
        respx.post(RECEIVER_URL).mock(return_value=httpx.Response(403))
        result = tools.send_to_external_processor(settings)

        assert result["succeeded"] is False
        assert result["http_status"] == 403
        assert result["error_category"] == ErrorCategory.HTTP_ERROR

    def test_no_error_category_claims_a_policy_decision(self) -> None:
        """There must be no way to express 'the platform denied this' from here."""
        values = {str(c) for c in ErrorCategory}
        for forbidden in ("denied", "blocked", "policy", "egress", "containment"):
            assert not any(forbidden in v for v in values), (
                f"ErrorCategory contains a value implying {forbidden!r}; the application "
                "cannot observe a platform decision."
            )

    @respx.mock
    def test_timeout_is_classified_as_timeout(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
        result = tools.get_servicing_policy(settings)
        assert result["error_category"] == ErrorCategory.TIMEOUT
        assert result["http_status"] is None

    @respx.mock
    def test_dns_failure_is_classified_as_dns(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(
            side_effect=httpx.ConnectError("[Errno -2] Name or service not known")
        )
        result = tools.get_servicing_policy(settings)
        assert result["error_category"] == ErrorCategory.DNS_ERROR

    @respx.mock
    def test_tls_failure_is_classified_as_tls(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(
            side_effect=httpx.ConnectError("certificate verify failed: unable to get issuer")
        )
        result = tools.get_servicing_policy(settings)
        assert result["error_category"] == ErrorCategory.TLS_ERROR

    @respx.mock
    def test_generic_connection_failure_is_not_upgraded(self, settings: Settings) -> None:
        """An unclassifiable connection error stays generic rather than guessing."""
        respx.get(POLICY_URL).mock(side_effect=httpx.ConnectError("connection refused"))
        result = tools.get_servicing_policy(settings)
        assert result["error_category"] == ErrorCategory.CONNECTION_ERROR

    @respx.mock
    def test_error_detail_is_truncated(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(side_effect=httpx.ConnectError("x" * 5000))
        result = tools.get_servicing_policy(settings)
        assert len(result["error_detail"]) < 300


class TestIndependence:
    @respx.mock
    def test_one_tool_failing_does_not_suppress_the_other(self, settings: Settings) -> None:
        """The blocked call must never swallow the permitted call's result."""
        respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={"policy_id": "SP-1"}))
        respx.post(RECEIVER_URL).mock(return_value=httpx.Response(403))

        policy_result = tools.get_servicing_policy(settings)
        receiver_result = tools.send_to_external_processor(settings)

        assert policy_result["succeeded"] is True
        assert receiver_result["succeeded"] is False

    @respx.mock
    def test_order_does_not_matter(self, settings: Settings) -> None:
        respx.post(RECEIVER_URL).mock(side_effect=httpx.ConnectError("boom"))
        respx.get(POLICY_URL).mock(return_value=httpx.Response(200, json={"policy_id": "SP-1"}))

        receiver_result = tools.send_to_external_processor(settings)
        policy_result = tools.get_servicing_policy(settings)

        assert receiver_result["succeeded"] is False
        assert policy_result["succeeded"] is True


class TestHttpHygiene:
    def test_tls_verification_is_never_disabled(self, settings: Settings) -> None:
        client = tools._build_client(settings)
        try:
            context = client._transport._pool._ssl_context  # type: ignore[attr-defined]
            assert context.verify_mode is ssl.CERT_REQUIRED
            assert context.check_hostname is True
        finally:
            client.close()

    def test_redirects_are_disabled(self, settings: Settings) -> None:
        """A 3xx must not be able to move a request to an un-allowlisted host."""
        client = tools._build_client(settings)
        try:
            assert client.follow_redirects is False
        finally:
            client.close()

    def test_timeout_is_applied_from_settings(self, settings: Settings) -> None:
        client = tools._build_client(settings)
        try:
            assert client.timeout.connect == settings.http_timeout_seconds
            assert client.timeout.read == settings.http_timeout_seconds
        finally:
            client.close()

    def test_client_source_never_disables_verification(self) -> None:
        source = inspect.getsource(tools._build_client)
        assert "verify=False" not in source.replace(" ", "")


class TestNoEmbeddedPolicy:
    """The absence tests. These are the point of the repository."""

    def test_tools_take_no_destination_argument(self) -> None:
        for fn in (tools.get_servicing_policy, tools.send_to_external_processor):
            params = list(inspect.signature(fn).parameters)
            assert params == ["settings"], (
                f"{fn.__name__} must take only validated settings; an arbitrary "
                f"destination argument would defeat the experiment. Got {params}."
            )

    def test_no_hostname_appears_literally_in_tool_source(self) -> None:
        """No code-level allowlist or blocklist of hosts."""
        source = inspect.getsource(tools)
        body = source[source.index("def _build_client") :]
        for literal in (".com", ".net", "localhost", "127.0.0.1"):
            assert literal not in body, (
                f"found hostname literal {literal!r} in tool implementation; destinations "
                "must come only from validated configuration"
            )

    def test_no_mode_branch_in_tool_implementations(self) -> None:
        """Tools must behave identically under local, Audit and Enforced."""
        body = inspect.getsource(tools)
        body = body[body.index("def _build_client") :]
        for marker in ("PolicyMode", "policy_mode ==", "policy_mode is", "ENFORCED", "AUDIT"):
            assert marker not in body, (
                f"found {marker!r} in tool implementation; tools must not know or act on "
                "which policy mode they are running under"
            )

    @respx.mock
    def test_behaviour_is_identical_across_modes(self) -> None:
        """Same stub, same inputs, same outcome in every mode.

        The stub returns success deliberately. An earlier version of this test stubbed a
        403, which meant an injected mode-based denial returning 403 looked identical to
        the real outcome and the test passed. Stubbing success means any application-level
        refusal diverges from the other modes and is caught.
        """
        respx.post(RECEIVER_URL).mock(return_value=httpx.Response(202, json={"received": True}))

        outcomes = []
        for mode in (PolicyMode.LOCAL, PolicyMode.AUDIT, PolicyMode.ENFORCED):
            s = Settings(
                policy_api_url=POLICY_URL,  # type: ignore[arg-type]
                test_receiver_url=RECEIVER_URL,  # type: ignore[arg-type]
                policy_mode=mode,
            )
            result = tools.send_to_external_processor(s)
            outcomes.append((result["succeeded"], result["http_status"], result["error_category"]))

        assert len(set(outcomes)) == 1, (
            f"tool behaviour differed across policy modes: {outcomes}. The application must "
            "behave identically; only the platform may differ."
        )
        assert outcomes[0][0] is True, (
            "the un-allowlisted tool must still attempt its call in Enforced mode. "
            "Refusing to attempt it is an application-level block."
        )

    @respx.mock
    def test_request_is_actually_attempted_in_enforced_mode(self) -> None:
        """Enforced must not short-circuit before the network call.

        If the application never makes the request, the platform never gets to deny it,
        and the demo would be proving an application check instead.
        """
        route = respx.post(RECEIVER_URL).mock(return_value=httpx.Response(403))
        s = Settings(
            policy_api_url=POLICY_URL,  # type: ignore[arg-type]
            test_receiver_url=RECEIVER_URL,  # type: ignore[arg-type]
            policy_mode=PolicyMode.ENFORCED,
        )
        tools.send_to_external_processor(s)
        assert route.called, "no outbound request was attempted under Enforced"


class TestNoSensitiveCapture:
    @respx.mock
    def test_result_contains_no_headers_or_raw_body(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(
            return_value=httpx.Response(
                200,
                json={"policy_id": "SP-1"},
                headers={"Authorization": "Bearer super-secret", "Set-Cookie": "sid=abc"},
            )
        )
        result = tools.get_servicing_policy(settings)
        flattened = repr(result)
        assert "super-secret" not in flattened
        assert "Authorization" not in flattened
        assert "sid=abc" not in flattened

    @respx.mock
    def test_response_payload_is_bounded(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(
            return_value=httpx.Response(200, json={f"k{i}": i for i in range(500)})
        )
        result = tools.get_servicing_policy(settings)
        assert len(result["result"]) <= 20

    @respx.mock
    def test_non_object_response_is_not_echoed(self, settings: Settings) -> None:
        respx.get(POLICY_URL).mock(return_value=httpx.Response(200, text="not json"))
        result = tools.get_servicing_policy(settings)
        assert result["result"] == {"parsed": False}
