# Content capture off: ADK legacy span switch (Brett, 2026-10-09)
Finding: google-adk `telemetry/context.py:132-136` reads `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS`, DEFAULT ON; `telemetry/tracing.py:319-358` then sets `gcp.vertex.agent.llm_request/llm_response/tool_response`. Only 'false'/'0' disables it. Our `disable_content_capture()` existed but never listed this var and was never called by the hosted entrypoint.
Fix: var added to `_CONTENT_CAPTURE_OFF`; `protocol_adapter.main()` calls it before Settings/host build, one path for both agents.
Tests: `TestEntrypointPrivacy` (main call removed -> fails), `test_adk_legacy_span_content_switch_is_covered` and `test_capture_is_forced_off` (value flipped -> fail).
Lesson: a safety helper that is defined but not wired into the entrypoint is untested in effect; test at the entrypoint.
