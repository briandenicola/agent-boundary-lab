"""The two business tools. Both are registered in every mode, without exception.

Design constraints that are the entire point of this module:

* Neither tool accepts a URL, host, or any other destination argument. Destinations come
  from validated startup configuration only.
* Neither tool knows which policy mode it is running under, and neither contains a
  hostname check. There is no code path here that can refuse a destination.
* TLS verification is always on. Redirects are disabled, so a 3xx cannot quietly move a
  request to an un-allowlisted host. Timeouts are explicit and bounded.
* Failures are classified as HTTP / TLS / DNS / timeout and never as "denied". The
  application cannot observe a platform decision; claiming otherwise would turn this
  demo into the application-level check it exists to avoid.
* Each tool returns its own independent result, so a failure in one cannot suppress the
  other's outcome.
* **Both tools carry the run marker identically**, in the query string *and* in a
  header. See ``_marker_params`` for why the query string is not optional.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from containment_demo.settings import ErrorCategory, Settings, ca_bundle_path
from containment_demo.telemetry import emit_tool_evidence

#: Where the run marker travels. Both names are used by **both** tools, always.
# The routes the two controlled services actually serve (services/policy_api/main.py,
# services/test_receiver/main.py). The configured URLs are BASE URLs (terraform outputs
# policy_api_url / test_receiver_url carry no path), so the path is fixed here, not
# configurable and not reachable from any tool argument.
POLICY_PATH = "/policy"
RECEIVER_PATH = "/ingest"

RUN_MARKER_PARAM = "demo_run_id"
RUN_MARKER_HEADER = "X-Demo-Run-Id"


def _endpoint(base: object, path: str) -> str:
    """Base URL plus a fixed route. A trailing slash on the base must not become '//'."""
    return str(base).rstrip("/") + path


def _marker_params(settings: Settings) -> dict[str, str]:
    """The run marker as a query parameter, for both tools, without exception.

    Why the query string and not just the header. Platform egress decision records are
    expected to log destinations at **URL granularity** and are not documented to
    capture request headers. A header-only marker therefore correlates the call that is
    *allowed* — because our own receiver reads whatever we send it and writes a receipt
    — while losing the call that is *denied*, which never reaches a destination we
    control and exists only in the platform's own record. The denied call is the demo.
    An uncorrelatable denial is INCONCLUSIVE under this repository's rules, so losing it
    would gut the result, and it would fail silently: header-only looks perfect in
    testing precisely on the half that does not matter.

    This does not make either tool an arbitrary-URL tool. The scheme, host and path all
    come from validated startup configuration and are not reachable from any argument;
    only a fixed, synthetic, non-sensitive marker is appended. Nothing a caller or a
    model can say changes the destination host.
    """
    return {RUN_MARKER_PARAM: settings.demo_run_id}


def _marker_headers(settings: Settings) -> dict[str, str]:
    """The run marker as a header, for both tools. Belt and braces with the query
    parameter: different logs capture different parts of a request."""
    return {RUN_MARKER_HEADER: settings.demo_run_id}


def _build_client(settings: Settings) -> httpx.Client:
    """Construct the one HTTP client configuration used by both tools.

    ``verify`` is either the injected proxy CA bundle or ``True`` for the system trust
    store. It is never ``False``.
    """
    bundle = ca_bundle_path()
    return httpx.Client(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        follow_redirects=False,
        verify=bundle if bundle else True,
    )


def _classify(exc: Exception) -> ErrorCategory:
    """Map a transport exception to an error category.

    Ordering matters: ``ConnectError`` is the parent of several more specific failures,
    so DNS and TLS are checked first. A generic connection failure is reported as such
    rather than being flattened into something more confident than the evidence supports.
    """
    if isinstance(exc, httpx.TimeoutException):
        return ErrorCategory.TIMEOUT
    if isinstance(exc, httpx.ConnectError):
        message = str(exc).lower()
        if "certificate" in message or "ssl" in message or "tls" in message:
            return ErrorCategory.TLS_ERROR
        if "name or service not known" in message or "nodename nor servname" in message:
            return ErrorCategory.DNS_ERROR
        if "getaddrinfo" in message or "temporary failure in name resolution" in message:
            return ErrorCategory.DNS_ERROR
        return ErrorCategory.CONNECTION_ERROR
    if isinstance(exc, httpx.TransportError):
        return ErrorCategory.CONNECTION_ERROR
    return ErrorCategory.UNEXPECTED


def _result(
    *,
    tool_name: str,
    destination_host: str,
    settings: Settings,
    started: float,
    http_status: int | None = None,
    error_category: ErrorCategory = ErrorCategory.NONE,
    error_detail: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the bounded, structured result record emitted by both tools.

    This is our application evidence schema, not a platform schema. It deliberately
    carries no request or response body, no headers, and no credentials.
    """
    record = {
        "tool_name": tool_name,
        "destination_host": destination_host,
        "demo_run_id": settings.demo_run_id,
        "policy_mode": str(settings.policy_mode),
        "agent_name": settings.agent_name,
        "agent_version": settings.agent_version,
        "duration_ms": round((time.monotonic() - started) * 1000, 2),
        "http_status": http_status,
        "succeeded": error_category is ErrorCategory.NONE,
        "error_category": str(error_category),
        "error_detail": error_detail,
        "result": payload,
    }
    emit_tool_evidence(settings, record)
    return record


def _sanitize(exc: Exception) -> str:
    """Reduce an exception to its type and a short message.

    Full exception text can embed URLs, headers, or response fragments. We keep enough
    to debug a transport failure and nothing that could leak a payload or a credential.
    """
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def get_servicing_policy(settings: Settings) -> dict[str, Any]:
    """Retrieve the synthetic servicing policy from the allowlisted API.

    Expected to succeed in every mode, including Enforced. If this call fails under
    Enforced, the egress policy is over-broad and the demo is misconfigured — that is a
    failure of the setup, not a successful containment result.
    """
    started = time.monotonic()
    host = settings.policy_api_host
    try:
        with _build_client(settings) as client:
            response = client.get(
                _endpoint(settings.policy_api_url, POLICY_PATH),
                params=_marker_params(settings),
                headers=_marker_headers(settings),
            )
    except Exception as exc:
        return _result(
            tool_name="get_servicing_policy",
            destination_host=host,
            settings=settings,
            started=started,
            error_category=_classify(exc),
            error_detail=_sanitize(exc),
        )

    if response.status_code >= 400:
        return _result(
            tool_name="get_servicing_policy",
            destination_host=host,
            settings=settings,
            started=started,
            http_status=response.status_code,
            error_category=ErrorCategory.HTTP_ERROR,
            error_detail=f"HTTP {response.status_code}",
        )

    return _result(
        tool_name="get_servicing_policy",
        destination_host=host,
        settings=settings,
        started=started,
        http_status=response.status_code,
        payload=_bounded_json(response),
    )


def send_to_external_processor(settings: Settings) -> dict[str, Any]:
    """Send a fixed synthetic record to the destination that is not allowlisted.

    Under Enforced this is expected to fail. A bare failure here proves nothing on its
    own: the HTTP 403 documented for the egress proxy is indistinguishable at this layer
    from a 403 returned by the destination itself, and a DNS or TLS failure is not a
    denial either. Attribution requires the platform's own decision record plus the
    absence of a receipt at the destination. See docs/compatibility.md B5.
    """
    started = time.monotonic()
    host = settings.test_receiver_host
    record = {
        "demo_run_id": settings.demo_run_id,
        "record_type": "synthetic_servicing_case",
        "case_reference": "SYNTHETIC-0001",
        "note": "Synthetic demo record. Contains no customer data.",
    }
    try:
        with _build_client(settings) as client:
            response = client.post(
                _endpoint(settings.test_receiver_url, RECEIVER_PATH),
                json=record,
                params=_marker_params(settings),
                headers=_marker_headers(settings),
            )
    except Exception as exc:
        return _result(
            tool_name="send_to_external_processor",
            destination_host=host,
            settings=settings,
            started=started,
            error_category=_classify(exc),
            error_detail=_sanitize(exc),
        )

    if response.status_code >= 400:
        return _result(
            tool_name="send_to_external_processor",
            destination_host=host,
            settings=settings,
            started=started,
            http_status=response.status_code,
            error_category=ErrorCategory.HTTP_ERROR,
            error_detail=f"HTTP {response.status_code}",
        )

    return _result(
        tool_name="send_to_external_processor",
        destination_host=host,
        settings=settings,
        started=started,
        http_status=response.status_code,
        payload=_bounded_json(response),
    )


def _bounded_json(response: httpx.Response) -> dict[str, Any]:
    """Parse a response body into a bounded dict.

    Bounded because an unbounded response body would end up in traces and logs, which is
    exactly what the telemetry rules forbid.
    """
    try:
        data = response.json()
    except ValueError:
        return {"parsed": False}
    if not isinstance(data, dict):
        return {"parsed": False}
    return {k: v for k, v in list(data.items())[:20] if isinstance(k, str)}
