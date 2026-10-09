# Decision: the agent's entry point gets tests, and lazy SDK imports are a hazard class

**Author:** Brett (Agent Developer)
**Date:** 2026-10-08
**Scope:** `src/containment_demo/protocol_adapter.py`, `tests/unit/test_protocol_adapter.py`
**Status:** Proposed

## What shipped

`protocol_adapter.py:70` called `context.get_input_text()` without `await`.
`get_input_text` is a coroutine function on **all four** `ResponseContext` variants in
`azure-ai-agentserver-responses` 2.2.0 — `_response_context`, `hosting._endpoint_handler`,
`hosting._execution_context`, `hosting._routing` — signature
`(self, *, resolve_references: bool = True) -> str`.

So `user_text` was a coroutine object, passed into `_run_agent_turn` as the user's
message. The agent never received the prompt, never decided to call a tool, and **no
invocation on the deployed digest could reach either business tool.** For a repository
whose entire claim rests on two tool calls producing two different platform outcomes, that
is total: the experiment could not run at all.

## Why it shipped: the entry point had zero tests

`tests/unit/` had test_agent, test_dependency_overrides, test_deploy, test_diagnostics,
test_invocation_primitive, test_services, test_settings, test_telemetry, test_tools and
test_verify_harness. It had **nothing for the protocol adapter** — the single function
every hosted invocation passes through. Nothing in the repo referenced `get_input_text`
except the broken line itself.

The tools were well tested. The thing that calls the tools was not. Coverage was
distributed by what was easy to test offline rather than by what would be fatal if wrong.

## Decisions

1. **`tests/unit/test_protocol_adapter.py` exists and is mandatory.** The handler, the
   turn loop, the cancellation contract and the diagnostics wiring are all covered. No
   future change to the entry point lands without a test.

2. **A lazily imported SDK boundary is where async/sync mistakes hide, and must be tested
   at that boundary.** `build_host` imports `azure.ai.agentserver.responses`,
   `google.adk.runners` and `google.genai` *inside* the function — deliberately, for the
   OpenTelemetry ordering reason in the module docstring. The cost is that there is no
   import-time signature for a reader, a linter or a type checker to check the call
   against. mypy sees `context: Any`. Ruff sees nothing. The only thing that can catch a
   missing `await` there is a test that drives the handler with a stand-in whose method is
   `async def` **because the real one is**.

   Corollary: a stand-in for an SDK object must match the real object's *async-ness*, and
   that match must itself be asserted. `test_the_fake_context_matches_the_real_sdk_shape`
   does this — if the fake were sync, the regression test would prove nothing.

3. **The lazy import is also what makes this testable offline.** `sys.modules` is consulted
   for the full dotted name before any parent package is loaded, so
   `monkeypatch.setitem(sys.modules, "azure.ai.agentserver.responses", fake)` means the
   real package is never imported. The tests need no Azure package, no credentials and no
   network, like the rest of `tests/unit`. Nothing was skipped; everything asked for is
   covered.

4. **Related to the deploy-poller lesson, and the same root cause.** That one trusted an
   SDK *enum* over a running service. This one trusted an SDK *signature* that was never
   actually read. Both are "we asserted something about the SDK without checking it".
   The general rule now stands twice over: **where SDK behaviour drives correctness,
   verify it against the installed package or a running service, and pin the verification
   in a test.**

## Consequences

- **The image digest changes, so both agent versions must be rebuilt and redeployed.**
  Dallas's invocation work also touched `tools.py`, so a rebuild was already required.
  Brian runs those commands.
- No prior invocation result on the current digest means anything about containment. Any
  evidence collected from it is **inconclusive** — the tools were never reached, so no
  egress was ever attempted.
- Unchanged, as required: the two business tools, RAI handling, digest pinning, the deploy
  poller.

## Tamper tests

Each guard was broken deliberately and the failing test recorded.

| Tamper | Test that caught it |
| --- | --- |
| Remove the `await` (the shipped defect) | `TestInputTextIsAwaited::test_handler_passes_a_real_str_to_the_agent_turn` and `::test_get_input_text_is_actually_called` |
| Cancellation raises instead of returning | `TestCancellation::test_cancelled_turn_returns_rather_than_raising`, `::test_cancellation_stops_consuming_events`, `::test_a_turn_cancelled_before_any_output_still_returns` |
| Register diagnostics unconditionally | `TestDiagnosticsRoute::test_route_is_not_registered_when_disabled` |
| Diagnostics re-implements a tool instead of reusing it | `TestDiagnosticsRoute::test_diagnostics_reuses_the_two_tool_implementations` |
| No-op control | nothing failed, as intended |
