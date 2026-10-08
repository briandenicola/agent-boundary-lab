"""Tests for the hosted-agent invocation primitive.

The primitive's job is to say, separately and honestly, what each of the two tools did.
The cases that matter are the ones that are easy to get wrong in a way that flatters the
result:

* a tool the model never called, read as a denial;
* one tool's failure suppressing the other's result;
* a classified failure read as proof of containment;
* two calls to the same tool disagreeing, and the convenient one being kept.

Every test here is offline: no Azure package, no credential, no network. The live call
takes an injected client, which is the only reason that is possible.
"""

from __future__ import annotations

import json

import pytest

from containment_demo.agent import REQUIRED_TOOL_NAMES
from containment_demo.invoke import (
    DETERMINATION,
    SOURCE_NONE,
    SOURCE_TOOL_RECORD,
    TOOL_NAMES,
    ControlCheck,
    VersionFacts,
    build_outcomes,
    classify_invocation_exception,
    compare_control,
    digest_of,
    extract_json_objects,
    invoke_agent,
    outcome_from_record,
    outcomes_from_response,
    response_texts,
    tool_records,
)
from containment_demo.settings import ErrorCategory

DIGEST = "sha256:94ed4a2142a3e5fbe4888125c9f13a3e629e2dfb65b25c62abed2c655bfa0d45"
IMAGE = f"acr.azurecr.io/containment-demo-agent@{DIGEST}"


def _record(
    tool: str,
    *,
    succeeded: bool = True,
    category: str = "none",
    status: int | None = 200,
    host: str = "example.invalid",
) -> dict[str, object]:
    return {
        "tool_name": tool,
        "destination_host": host,
        "demo_run_id": "run-1",
        "http_status": status,
        "succeeded": succeeded,
        "error_category": category,
        "error_detail": None,
    }


def _response(*texts: str, response_id: str = "resp_1", status: str = "completed") -> object:
    class _Response:
        id = response_id

        def __init__(self) -> None:
            self.status = status

        def model_dump(self) -> dict[str, object]:
            return {
                "id": response_id,
                "status": status,
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": text} for text in texts],
                    }
                ],
            }

    return _Response()


class _FakeResponses:
    def __init__(self, result: object | Exception) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeClient:
    def __init__(self, result: object | Exception) -> None:
        self.responses = _FakeResponses(result)


class TestTheToolListCannotDriftFromTheAgent:
    def test_both_business_tools_are_covered(self) -> None:
        assert set(TOOL_NAMES) == set(REQUIRED_TOOL_NAMES)

    def test_order_is_fixed_so_evidence_records_are_comparable(self) -> None:
        assert TOOL_NAMES == ("get_servicing_policy", "send_to_external_processor")


class TestNoSecondVocabulary:
    def test_classification_reuses_the_tools_error_category(self) -> None:
        # scripts/verify_demo.py's FailureMode already mirrors ErrorCategory. A third
        # list of names would be a third thing to keep in step.
        from scripts.verify_demo import FailureMode

        assert {m.value for m in FailureMode} == {m.value for m in ErrorCategory}

    def test_there_is_no_policy_denied_category(self) -> None:
        assert not any("deni" in m.value or "block" in m.value for m in ErrorCategory)


class TestBothToolsAreAlwaysReported:
    def test_an_empty_response_still_reports_two_tools(self) -> None:
        outcomes = build_outcomes([])
        assert list(outcomes) == list(TOOL_NAMES)
        for outcome in outcomes.values():
            assert outcome.attempted is False
            assert outcome.succeeded is None
            assert outcome.evidence_source == SOURCE_NONE

    def test_one_tool_failing_does_not_suppress_the_other(self) -> None:
        outcomes = build_outcomes(
            [
                _record("get_servicing_policy", succeeded=True, category="none", status=200),
                _record(
                    "send_to_external_processor",
                    succeeded=False,
                    category="http_error",
                    status=403,
                ),
            ]
        )
        assert outcomes["get_servicing_policy"].succeeded is True
        assert outcomes["get_servicing_policy"].http_status == 200
        assert outcomes["send_to_external_processor"].succeeded is False
        assert outcomes["send_to_external_processor"].error_category is ErrorCategory.HTTP_ERROR
        assert outcomes["send_to_external_processor"].http_status == 403

    def test_only_one_tool_reporting_leaves_the_other_not_attempted(self) -> None:
        outcomes = build_outcomes([_record("get_servicing_policy")])
        assert outcomes["get_servicing_policy"].attempted is True
        other = outcomes["send_to_external_processor"]
        assert other.attempted is False
        assert "INCONCLUSIVE" in other.detail


class TestAMissingToolCallIsNotADenial:
    def test_not_attempted_is_never_a_success_and_never_a_failure(self) -> None:
        outcome = build_outcomes([])["send_to_external_processor"]
        assert outcome.succeeded is None
        assert outcome.error_category is None
        assert "not a denial" in outcome.detail

    def test_the_determination_is_always_inconclusive(self) -> None:
        client = _FakeClient(_response(json.dumps(_record("get_servicing_policy"))))
        result = invoke_agent(
            endpoint="https://example.invalid/api/projects/p",
            agent_name="containment-demo-audit",
            demo_run_id="run-1",
            client=client,
        )
        assert result.determination == DETERMINATION
        assert "inconclusive" in result.determination
        assert "pass" not in json.dumps(result.as_dict())


class TestFailureKindsStayApart:
    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (TimeoutError("timed out"), ErrorCategory.TIMEOUT),
            (OSError("[Errno -2] Name or service not known"), ErrorCategory.DNS_ERROR),
            (OSError("certificate verify failed"), ErrorCategory.TLS_ERROR),
            (ValueError("something else entirely"), ErrorCategory.UNEXPECTED),
        ],
    )
    def test_each_kind_is_classified_distinctly(
        self, exc: Exception, expected: ErrorCategory
    ) -> None:
        assert classify_invocation_exception(exc) is expected

    def test_an_openai_style_status_error_is_an_http_error(self) -> None:
        class APIStatusError(Exception):
            status_code = 403

        assert (
            classify_invocation_exception(APIStatusError("Forbidden")) is ErrorCategory.HTTP_ERROR
        )

    def test_an_openai_style_timeout_is_a_timeout_not_a_connection_error(self) -> None:
        class APITimeoutError(Exception):
            pass

        assert classify_invocation_exception(APITimeoutError("")) is ErrorCategory.TIMEOUT

    def test_a_connection_error_is_not_upgraded_into_dns_or_tls(self) -> None:
        class APIConnectionError(Exception):
            pass

        assert (
            classify_invocation_exception(APIConnectionError("Connection error."))
            is ErrorCategory.CONNECTION_ERROR
        )

    def test_a_cause_chain_is_inspected_not_just_the_outer_exception(self) -> None:
        class APIConnectionError(Exception):
            pass

        outer = APIConnectionError("Connection error.")
        outer.__cause__ = OSError("[Errno -2] Name or service not known")
        assert classify_invocation_exception(outer) is ErrorCategory.DNS_ERROR


class TestTransportFailureIsNotAToolResult:
    def test_a_failed_invocation_reports_both_tools_as_not_attempted(self) -> None:
        class APITimeoutError(Exception):
            pass

        client = _FakeClient(APITimeoutError("request timed out"))
        result = invoke_agent(
            endpoint="https://example.invalid/api/projects/p",
            agent_name="containment-demo-enforced",
            demo_run_id="run-2",
            client=client,
        )
        assert result.transport_ok is False
        assert result.transport_error_category is ErrorCategory.TIMEOUT
        assert all(o.attempted is False for o in result.outcomes.values())
        assert "says nothing about egress" in (result.transport_detail or "")

    def test_an_http_403_reaching_the_platform_is_kept_separate_from_tool_results(self) -> None:
        class APIStatusError(Exception):
            status_code = 403

        client = _FakeClient(APIStatusError("Forbidden"))
        result = invoke_agent(
            endpoint="https://example.invalid/api/projects/p",
            agent_name="containment-demo-audit",
            demo_run_id="run-3",
            client=client,
        )
        assert result.transport_error_category is ErrorCategory.HTTP_ERROR
        assert "HTTP 403" in (result.transport_detail or "")
        assert result.outcomes["send_to_external_processor"].error_category is None


class TestRepeatedCallsAreNotResolvedConveniently:
    def test_agreeing_records_collapse_and_count(self) -> None:
        outcomes = build_outcomes([_record("get_servicing_policy")] * 2)
        assert outcomes["get_servicing_policy"].occurrences == 2
        assert outcomes["get_servicing_policy"].succeeded is True

    def test_disagreeing_records_go_inconclusive(self) -> None:
        outcomes = build_outcomes(
            [
                _record("send_to_external_processor", succeeded=True, category="none", status=202),
                _record(
                    "send_to_external_processor",
                    succeeded=False,
                    category="http_error",
                    status=403,
                ),
            ]
        )
        outcome = outcomes["send_to_external_processor"]
        assert outcome.succeeded is None
        assert outcome.error_category is None
        assert outcome.occurrences == 2
        assert "disagree" in outcome.detail


class TestExtractionFromRealisticResponses:
    def test_json_is_found_inside_prose_and_markdown_fences(self) -> None:
        text = (
            "Here is what happened:\n```json\n"
            + json.dumps(_record("get_servicing_policy"))
            + "\n```\nand then\n"
            + json.dumps(_record("send_to_external_processor", succeeded=False, category="timeout"))
        )
        records = tool_records(extract_json_objects(text))
        assert {r["tool_name"] for r in records} == set(TOOL_NAMES)

    def test_records_nested_in_a_wrapper_are_found(self) -> None:
        wrapper = {
            "demo_run_id": "run-1",
            "determination": "inconclusive-without-platform-evidence",
            "results": [_record("get_servicing_policy"), _record("send_to_external_processor")],
        }
        records = tool_records(extract_json_objects(json.dumps(wrapper)))
        assert len(records) == 2

    def test_unrelated_json_is_ignored(self) -> None:
        records = tool_records(extract_json_objects('{"tool_name": "some_other_tool"}'))
        assert records == []

    def test_malformed_json_does_not_raise(self) -> None:
        assert extract_json_objects("{not json at all") == []

    def test_text_is_read_from_message_content_parts(self) -> None:
        texts = response_texts(_response("hello", "world"))
        assert texts == ["hello", "world"]

    def test_an_unrecognised_payload_shape_yields_no_text_rather_than_raising(self) -> None:
        assert response_texts(object()) == []

    def test_function_call_output_items_are_read(self) -> None:
        payload = {
            "output": [
                {
                    "type": "function_call_output",
                    "output": json.dumps(_record("get_servicing_policy")),
                }
            ]
        }
        outcomes = outcomes_from_response(payload)
        assert outcomes["get_servicing_policy"].evidence_source == SOURCE_TOOL_RECORD


class TestRecordFieldsAreNotInvented:
    def test_an_unrecognised_error_category_is_not_guessed(self) -> None:
        outcome = outcome_from_record(
            {"tool_name": "get_servicing_policy", "error_category": "policy_denied"}
        )
        assert outcome.error_category is None
        assert "unrecognised error_category" in outcome.detail

    def test_a_missing_http_status_stays_none_not_zero(self) -> None:
        outcome = outcome_from_record({"tool_name": "get_servicing_policy", "succeeded": True})
        assert outcome.http_status is None

    def test_succeeded_is_derived_from_category_when_absent(self) -> None:
        outcome = outcome_from_record(
            {"tool_name": "get_servicing_policy", "error_category": "none"}
        )
        assert outcome.succeeded is True

    def test_succeeded_stays_unknown_when_nothing_says_otherwise(self) -> None:
        outcome = outcome_from_record({"tool_name": "get_servicing_policy"})
        assert outcome.succeeded is None


class TestNoPayloadOrProseIsRetained:
    def test_the_model_text_is_hashed_not_stored(self) -> None:
        secret_ish = "the model said something long and quotable"
        client = _FakeClient(_response(secret_ish))
        result = invoke_agent(
            endpoint="https://example.invalid/api/projects/p",
            agent_name="containment-demo-audit",
            demo_run_id="run-4",
            client=client,
        )
        rendered = json.dumps(result.as_dict())
        assert secret_ish not in rendered
        assert result.response_text_sha256 is not None
        assert result.response_text_chars == len(secret_ish)


class TestTheRunMarkerIsCarried:
    def test_run_id_goes_in_metadata_header_and_prompt(self) -> None:
        client = _FakeClient(_response("{}"))
        invoke_agent(
            endpoint="https://example.invalid/api/projects/p",
            agent_name="containment-demo-audit",
            demo_run_id="run-marker-xyz",
            client=client,
        )
        call = client.responses.calls[0]
        assert call["metadata"] == {"demo_run_id": "run-marker-xyz"}
        assert call["extra_headers"] == {"X-Demo-Run-Id": "run-marker-xyz"}
        # A URL-granularity log cannot see a header. The query parameter is the copy
        # that survives when request headers are not captured.
        assert call["extra_query"] == {"demo_run_id": "run-marker-xyz"}
        assert "run-marker-xyz" in str(call["input"])

    def test_the_agents_own_calls_mark_both_destinations_the_same_way(self) -> None:
        # The invocation primitive and the tools must agree on the marker names, or the
        # join Lambert writes will find one half of the run and not the other.
        from containment_demo.tools import RUN_MARKER_HEADER, RUN_MARKER_PARAM

        assert RUN_MARKER_PARAM == "demo_run_id"
        assert RUN_MARKER_HEADER == "X-Demo-Run-Id"

    def test_the_prompt_asks_for_both_tools_and_does_not_hint_at_an_outcome(self) -> None:
        client = _FakeClient(_response("{}"))
        invoke_agent(
            endpoint="https://example.invalid/api/projects/p",
            agent_name="containment-demo-enforced",
            demo_run_id="run-5",
            client=client,
        )
        prompt = str(client.responses.calls[0]["input"]).lower()
        for name in TOOL_NAMES:
            assert name in prompt
        for forbidden in ("blocked", "denied", "should fail", "allowlist", "policy will"):
            assert forbidden not in prompt


class TestTheControlIsAssertedNotAssumed:
    def _facts(self, image_a: str = IMAGE, image_b: str = IMAGE) -> list[VersionFacts]:
        return [
            VersionFacts("containment-demo-audit", "2", "active", image_a, ".../egress-audit"),
            VersionFacts(
                "containment-demo-enforced", "1", "active", image_b, ".../egress-enforced"
            ),
        ]

    def test_same_digest_and_distinct_policies_holds(self) -> None:
        check = compare_control(self._facts())
        assert check.holds is True
        assert DIGEST in check.detail
        assert "nothing about whether either policy is enforced" in check.detail

    def test_different_digests_fail(self) -> None:
        other = "acr.azurecr.io/containment-demo-agent@sha256:" + "0" * 64
        assert compare_control(self._facts(image_b=other)).holds is False

    def test_a_tag_instead_of_a_digest_fails(self) -> None:
        check = compare_control(self._facts(image_b="acr.azurecr.io/containment-demo-agent:latest"))
        assert check.holds is False
        assert "mutable" in check.detail

    def test_a_shared_policy_fails(self) -> None:
        facts = self._facts()
        facts[1] = VersionFacts(
            "containment-demo-enforced", "1", "active", IMAGE, ".../egress-audit"
        )
        assert compare_control(facts).holds is False

    def test_one_agent_is_not_an_experiment(self) -> None:
        assert compare_control(self._facts()[:1]).holds is False

    def test_digest_of_ignores_tags(self) -> None:
        assert digest_of("repo:latest") is None
        assert digest_of(None) is None
        assert digest_of(IMAGE) == DIGEST

    def test_the_control_check_result_is_a_plain_verdict(self) -> None:
        assert isinstance(compare_control(self._facts()), ControlCheck)
