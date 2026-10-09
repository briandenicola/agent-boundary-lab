# A2A spike (Blocker 5): drafted, not run
- `src/containment_demo/a2a_spike.py` + `tests/unit/test_a2a_spike.py` (20 tests); new `a2a` extra in pyproject (not in any image).
- Read-only by default. `--enable` PATCHes ONE agent (changes Azure; Brian's call). `--send` calls the agent.
- No pass: determination is always `inconclusive-a2a-unverified`. Failures are classified our_call vs platform; only platform 400/404/405/415/501 on enable/card is an `unsupported-signal`.
- Unknown (docs/compatibility.md B5a): hosted-container support, whether protocol_versions must list a2a, whether the container must serve anything, v1.0 JSON-RPC method name, a2a-sdk method names (not installed locally).
- The PATCH targets the agent, not a version, so it does not change the image digest; adding a2a to protocol_versions would, and is deliberately not done.
- Needs: in-VNet execution; PATCH rights for --enable.
