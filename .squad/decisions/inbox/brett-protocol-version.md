# Decision: Responses protocol version default 2.0.0 (2026-10-09)

First live invoke: HTTP 400 "Unsupported responses protocol version '' for agent 'containment-demo-audit:3'. Please use version '2.0.0'."
`v1` passed create_version but failed at invoke: create-time acceptance is not evidence of invoke-time validity.

- `DEMO_AGENT_PROTOCOL_VERSION` default `v1` -> `2.0.0` (still a settings field). UNVERIFIED until a live invoke succeeds.
- invoke.py sends no protocol-version header/param (SDK sends only api-version query + Foundry-Features header; azure-ai-projects 2.8.0 _patch.py:55-86), so no change. Its docstring still says "v1"; stale comment only.
- Pinned by test_registered_protocol_version_is_2_0_0_not_v1.
- Digest unaffected by this change, but agent versions must be redeployed (new version) for it to take effect. Brian runs it.
