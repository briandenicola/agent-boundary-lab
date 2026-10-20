# Issue #4 demo readiness checklist

**Last updated:** 2026-10-20 (Ripley revision)
**Status:** code written and unit-tested with mocks; **nothing run live**. Every box below is unchecked on purpose.
**Goal:** one signed-in user is **allowed** (policy API 200) and one is **denied** (403 `user_not_authorized`) for the
same tool, in Audit and Enforced, using each user's own token. Flow and caveats: [token-flow-documented.md](token-flow-documented.md).

Labels: **VERIFIED** = ran/observed; **SOURCE-VERIFIED** = read in code or primary docs; **UNVERIFIED** = unknown.
The only VERIFIED fact: the unit suite passed (953 passed, 5 skipped, mocks only, run by the coordinator).

## Three outcomes, never merged

1. **Identity result** (policy API verdict on the user's OBO token: 200 with `user_object_id` / 403 / 401). Not a network
   result. The actor alias is a display label, never an input.
2. **Network/containment result** (`send_to_external_processor`): platform egress decision + receipt absence/presence,
   per [demo-runbook.md](demo-runbook.md) sections B/C. Without platform evidence it is **inconclusive**.
3. A denied identity result is not a containment pass or fail, and the reverse.

## Known code defects to fix before the live run (SOURCE-VERIFIED by reading; details in token-flow section 6)

- [x] (code fixed, UNVERIFIED live) `invoke.outcome_from_record` now keeps `user_object_id` on HTTP 200, so the UI `allowed` verdict is reachable.
- [x] (code fixed, UNVERIFIED live) `HARNESS_OBO_*` is written to Secret `harness-oidc-config`; the harness Deployment now
      maps the four keys via `secretKeyRef` (`optional: true`) and `external-app` restarts the harness. Confirm in the pod:
      `HARNESS_OBO_*` present and the harness starts.
- [x] (code fixed, UNVERIFIED live) The UI receipt KQL matches `authorization_decision` or `served` receipts for the run id.

## Pre-run (owner approval for every Azure/Entra/cluster change)

- [ ] `uv lock` (msal added to `pyproject.toml`; `uv.lock` is tracked and not regenerated).
- [ ] Images rebuilt so the new code ships: hosted agent, policy API, facade, harness (`task build:all`).
- [ ] `POLICY_API_AUTHORIZED_USER_IDS=8bbab162-0743-444c-b305-fed34bab43fb` in `.env` (only that user; `10870cbe-74ab-4c46-b5a8-8fcded26e615` absent).
- [ ] `task app:deploy-external HOSTNAME=… LETSENCRYPT_EMAIL=…` (includes `external-app`, which writes `TF_VAR_policy_api_*` into `.env`, and a final `cloud:up` that makes the policy API delegated).
- [ ] New images rolled out (agent versions, policy API, facade, harness).

## Live checks (each UNVERIFIED until run)

- [ ] Allowed user (`8bbab162…`): UI shows `allowed`, `user_token_forwarded=true`, in Audit and Enforced.
- [ ] Denied user (`10870cbe…`): UI shows `denied`, error `user_not_authorized`, the user's object id, in Audit and Enforced.
- [ ] `user_token_forwarded=false` never appears. If it does, Foundry did not deliver the header (or defect 2): the result
      is "no evidence", not a pass.
- [ ] `send_to_external_processor` outcome identical for both users, judged only by platform evidence + receipts.
- [ ] Receipt query (kql-queries.md section 10) returns the denial row for the denied run; served receipt via query 5 for
      the allowed run.
- [ ] Egress panel still reads `inconclusive` unless platform evidence is joined on the same run id.

## Teardown

- [ ] `task chat-agent:external-app-down` (also removes the `TF_VAR_policy_api_*` lines from `.env`), then `task cloud:up`.

## Notes

- `az` CLI is used by these tasks, departing from the squad rule "no az in anything that ships", at the owner's explicit
  request.
- `demo_ui.py` (two-button UI) still shows the old `status_from_http` badge; out of scope.
- Delegated Foundry invocation matrix from I0 (invalid/wrong-audience at the Foundry layer) is not part of this flow and
  remains unproven ([identity-probe.md](identity-probe.md)).
- The earlier WP-1/WP-2 actor-context checklist in this file was superseded: the actor alias is display only now
  (`actor_context.py` docstring).
