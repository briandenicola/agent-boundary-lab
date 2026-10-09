# Tools requested "/" on both services (404)
- Root cause: configured DEMO_POLICY_API_URL / DEMO_TEST_RECEIVER_URL are BASE URLs (infra/cloud/outputs.tf:22-30, no path); tools GET/POSTed them verbatim (tools.py client.get/post), but services serve only /policy and /ingest.
- Unit fixtures used full-path URLs, so the mismatch was invisible. Fixtures now use the deployed shape (base with trailing slash).
- Fix: fixed route constants POLICY_PATH/RECEIVER_PATH joined with rstrip("/"). One code path, no mode logic, no allowlist. Test pins paths, no '//', and that the constants match the service decorators.
- Needs agent image rebuild + redeploy of both versions (new digest). Services unchanged.
- 403 at test-receiver: the service never returns 403 (only 404 for unknown route, 405, 422, 202); a 403 is from the platform path or the Container App ingress layer, still only a classified http_error until platform evidence is joined.
