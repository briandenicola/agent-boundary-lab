# Decision: DEMO_AZURE_OPENAI_API_VERSION default 2024-10-21 -> v1 (2026-10-09) — UNVERIFIED

Evidence/sources: docs/compatibility.md E2a (litellm 1.104.0 main.py:1060 bridge, common_utils.py:781-862; MS Learn api-version-lifecycle + responses, accessed 2026-10-09).
Cause (hypothesis fitting reproduced URL): gpt-5.4+ with function tools is routed by litellm to /openai/responses; dated 2024-10-21 predates the Responses API (introduced 2025-03-01-preview) and is used verbatim.

Rollout, important: the deployer copies this value into the hosted agent's environment_variables (deploy.py:331), and reuse matching is image digest + policy only, NOT env. So the env change reaches the agent only via a NEW version. Rebuilding changes the digest, which forces one for both agents; supplying DEMO_AZURE_OPENAI_API_VERSION=v1 on the harness without a rebuild would NOT create a new version (existing one is reused). Recommend rebuild + redeploy. Fallback if 404 persists: `preview`.
Pinned by test_azure_openai_api_version_default_is_v1_not_a_dated_version (tamper-tested).
