# a2a_spike: platform HTTP errors were labelled our_call (Brett, 2026-10-09)
httpx.HTTPStatusError carries the status on `exc.response`, not `exc.status_code`, so `http_status_of` returned None and a platform 400 became origin=our_call/unexpected. classify_failure now reads `exc.response`, labels HTTP errors origin=platform (401/403/407 stay our_call), records the status, and captures a redacted body capped at 2048 chars (Bearer/Basic, JWTs, authorization/token/secret/password/api-key values removed).
Tamper: ignoring exc.response, removing the cap, removing redaction each fail named tests.
Lesson: a classifier unit-tested only with fake exceptions that carry the attribute you expect will never meet the real library's shape; test with the real httpx error.
