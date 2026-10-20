# Issue #4 demo readiness checklist

Date: 2026-10-19
Scope: what must be complete before demonstrating the **narrowed** issue #4 execution
track locked in [`issue-4-squad-plan.md`](issue-4-squad-plan.md) (WP-0): a simple
**allowed user vs denied user** demo through harness -> Foundry -> the
authorization-protected policy tool path, with the two-tool containment story kept
intact and reported separately.

## Primary acceptance (this execution track)

- [ ] An **allowed** actor can drive the existing harness/UI path, reach the hosted
      Foundry agent, and have the authorization-protected policy tool path succeed
      (`get_servicing_policy` / policy API route authorized).
- [ ] A **denied** actor drives the same path and is rejected at the policy
      authorization boundary, for the **same protected tool path** — not a different
      route, not a different tool.
- [ ] Three outcome categories are reported **separately** and never merged into one
      verdict:
  - [ ] **Identity authorization outcome** — whether the actor context (WP-1) resolved
        the caller as the allowed actor or the denied actor. This is a statement about
        who the request claims to be, not about what happened next.
  - [ ] **Policy API authorization outcome** — the protected route's own 200/401/403/503
        decision for that actor (WP-2). A denied policy call is evidence about the
        policy API's authorization boundary, not about egress containment.
  - [ ] **Containment evidence outcome** — platform egress decision plus receiver
        receipt/absence for `send_to_external_processor`, collected exactly as in
        `demo-runbook.md` Sections B/C. A denied identity or policy outcome does not
        stand in for a containment pass or fail, and a containment pass/fail does not
        stand in for either authorization outcome.
- [ ] If the three outcomes above cannot be joined on the same `demo_run_id` (for
      example the containment egress/receipt rows are missing, delayed, or do not carry
      the run id), the containment evidence outcome is **inconclusive** — never
      reported as a pass and never inferred from the identity or policy outcomes.
- [ ] Presenter runbook and evidence docs match exactly what is deployed and describe
      all three outcome categories (identity authorization, policy API authorization,
      containment evidence) without conflating any pair of them.

## Out of scope for this execution track

The following items from the full issue #4 design (`docs/PLAN.md`, I0) are **not**
required to close this narrowed track. They stay documented as open/blocked and are
only pulled back in scope if they turn out to be a hard dependency of running the
allowed/denied demo path itself:

- Delegated Foundry invocation contract and its full I0 matrix (allowed / denied /
  invalid token / wrong-audience token proven **at the Foundry invocation layer**).
- Proving sidecar OBO or a user-delegated bearer accepted by the hosted agent's own
  Responses endpoint.
- Delegated harness-to-Foundry token exchange (I2), beyond the actor-context and policy
  authorization behavior required for this issue #4 execution track.

If, while implementing WP-1/WP-2, the team finds the demo path cannot run at all
without one of these items, escalate to Brian before expanding scope; do not silently
re-absorb the full I0 matrix into this track.

## Current status snapshot

- ✅ Probe sidecar image pull blocker fixed by pinning:
  `mcr.microsoft.com/entra-sdk/auth-sidecar:1.1.2-azurelinux3.0-distroless@sha256:73a8763100c93c3da1a3ed1ba3af2c6122c0517687354dceded30537a1aee97f`
- ✅ Existing UI already exists; no new UI is needed.
- ✅ `identity:up` is rerunnable default path; strict checks moved to `identity:validate`.
- ⚠️ Full I0 delegated Foundry invocation matrix remains unverified/inconclusive — tracked
  as out-of-scope above unless it blocks the narrowed demo path.
- ❌ Allowed-vs-denied demo path (this track) is not yet closed.

## Remaining work (must complete, this track)

## 1) Deliver actor context and policy authorization (WP-1, WP-2)

- [ ] Implement the minimal shared actor context contract (WP-1): actor alias, bounded
      lifetime, safe status only — no raw tokens, no claim dumps.
- [ ] Wire policy API authorization by actor (WP-2): allowed actor authorized; denied
      actor rejected; explicit 401/403/503 semantics; `/healthz` stays the only
      unauthenticated route.
- [ ] Persist a redacted evidence artifact for the allowed/denied pass/fail pair on the
      policy tool path.

## 2) Use existing UI/harness for the allowed/denied demo path (no new UI)

- [ ] Keep current UI as the entrypoint.
- [ ] Ensure UI → harness → A2A facade → Foundry path is the one used in the demo.
- [ ] Add redacted claim summary visibility only (no raw token strings, no auth headers).
- [ ] Show actor-level outcomes in UI/reporting as three distinct fields, never merged:
  - [ ] actor alias and **identity authorization outcome** (which actor was resolved)
  - [ ] **policy API authorization outcome** (the route's own allowed/denied result)
  - [ ] **containment evidence outcome** — pass / fail / **inconclusive** when the
        platform egress/receipt join is missing, never inferred from the two outcomes
        above

## 3) Policy API authorization proof (separate from identity and containment)

- [ ] Demonstrate allowed actor can access the protected policy route.
- [ ] Demonstrate denied actor is rejected at the policy auth boundary for the same route.
- [ ] Ensure denied policy authorization is never reported as containment pass, and is
      labelled as a policy API authorization outcome, not an identity authorization
      outcome or a containment result.
- [ ] Keep receiver route unauthenticated and behaviorally unchanged for containment signal.

## 4) Harden operator workflow for demo day (WP-6)

- [ ] `task app:deploy-external HOSTNAME=... LETSENCRYPT_EMAIL=...` verified live as the from-scratch, no-manual deploy path.
- [ ] OIDC app registration creation is automated by task flow (no portal/manual step required).
- [ ] `task app:deploy` + `task identity:up` sequence verified live in the current environment.
- [ ] `task identity:validate` verified as strict preflight/reconciliation without sign-ins.
- [ ] `task identity:destroy` + teardown sequence verified and repeatable.
- [ ] Failure handling validated:
  - [ ] partial/unknown journal state stops safely
  - [ ] no destructive cleanup on unresolved state
  - [ ] retry path documented

## 5) Demo artifacts and handoff (WP-7)

- [ ] Update `docs/demo-runbook.md` with the allowed/denied demo steps and expected
      outcome categories (identity authorization, policy API authorization, and
      containment evidence — kept explicitly separate).
- [ ] Update `docs/telemetry-map.md` with the actor-context field names used in the
      allowed/denied join.
- [ ] Update `docs/evidence-template.md` for allowed/denied + identity/policy auth
      split (drop the invalid-token/wrong-audience rows unless they are reintroduced
      in scope).
- [ ] Keep one "demo-day checklist" section with operator command order and pass/fail
      criteria for allowed/denied plus audit/enforced tool behavior.

## Operator command sequence for this track

```bash
# strict consistency/reconciliation, no sign-ins
task identity:validate

# rerunnable identity flow + probe
task identity:up

# inspect latest redacted result
task identity:status

# then run the existing UI/harness demo flow with an allowed actor, then a denied actor
```

## Explicit non-goals (to avoid side quests)

- Do not create a second UI.
- Do not log or display raw tokens/auth headers.
- Do not replace delegated Foundry invocation requirement with app-only fallback for
  any item kept in scope.
- Do not conflate identity authorization, policy API authorization, or containment
  enforcement with one another — each is reported as its own outcome.
- Do not expand scope back to the full I0 delegated Foundry invocation matrix without
  Brian's explicit sign-off.
