# Decision: confirm reuse with a direct get_version read (2026-10-09)

Evidence: containment-demo-audit:4 was `failed` (ImageError, ACR auth / AcrPull) per get_version but ACTIVE per list_versions; find_matching_version reused it and the init container crash-looped.

1. List status is a hint, never a verdict. `_confirmed_reusable` does a direct get_version; only ready/pending is reused, otherwise the next candidate or a NEW version. A failed version is never healed by a permission fix: after the ACR role is applied, a new version is created automatically.
2. "Service error: None" root cause: `AgentVersionDetails` (azure-ai-projects 2.8.0) declares no `error` field; getattr returns None, the undeclared wire field is only reachable by key (`version["error"]`). Verified by deserialising a failed body 2026-10-09. `_service_error_of` now falls back to mapping access.
3. Tamper: skipping the direct read failed test_list_active_but_direct_failed_is_not_reused + test_direct_read_failure_is_logged_with_the_service_error; dropping the mapping fallback failed test_service_error_is_read_from_a_mapping_when_there_is_no_attribute.

## Proposal (not implemented): DEMO_DIAGNOSTICS_TOKEN in environment_variables
environment_variables are readable by anyone who can read the version, so the token leaks to every reader.
Safest: do not ship a secret in the version at all; have the agent fetch the token at startup from Key Vault via its managed identity (Key Vault reference in settings, no value in the definition), or drop the route in hosted mode and trigger diagnostics from the AKS harness only.
Either keeps both versions identical in definition apart from the policy, and keeps the token out of get_version output.
