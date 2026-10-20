# Issue #4 squad execution plan (allowed vs denied demo)

Date: 2026-10-19  
Owner intent: keep the demo simple and show **allowed user vs denied user** behavior clearly.

## Objective

Demonstrate, through the existing harness → Foundry agent path, that:

1. an **allowed** user can invoke the authorization-protected tool path successfully;
2. a **denied** user is rejected at the authorization boundary for the same path;
3. the two-tool containment story stays intact (allowlisted destination vs non-allowlisted destination);
4. code, runbook, and operator workflow are easy to read, explain, stand up, and repeat.

## Scope and boundaries

- Keep existing UI/harness entrypoints; no second UI.
- Keep both business tools always registered and unchanged in intent.
- Keep receiver unauthenticated; do not treat policy authorization denial as containment proof.
- Never log/display raw tokens, authorization headers, or full claim dumps.
- Missing/ambiguous evidence is inconclusive.

## Squad work packages

| ID | Work package | Primary | Reviewer | Depends on | Deliverables | Done when |
| --- | --- | --- | --- | --- | --- | --- |
| WP-0 | Locking scope and acceptance language | Ripley | Brian | none | Updates to `docs/issue-4-demo-readiness.md` with explicit allowed-vs-denied acceptance and out-of-scope notes | Acceptance criteria match this objective and remove side-quest ambiguity |
| WP-1 | Implementing minimal actor context contract | Brett | Ripley | WP-0 | Small shared runtime contract keyed by run id (actor alias + bounded lifetime + safe statuses) | Harness and policy path can resolve actor context deterministically without exposing secrets |
| WP-2 | Enforcing policy API authorization by actor | Brett | Dallas | WP-1 | `services/policy_api/main.py` integration with shared validator/actor contract, explicit 401/403/503 semantics | Allowed actor authorized; denied actor rejected; `/healthz` only unauthenticated route |
| WP-3 | Surfacing actor-level outcomes in harness/UI | Brett | Ripley | WP-2 | Harness/UI response model and page output updates: actor alias, auth verdict, policy result, containment determination separation | Presenter can explain one run output without reading logs or code |
| WP-4 | Preserving containment signal separation | Lambert | Ripley | WP-2 | Telemetry/evidence mapping updates ensuring identity auth results and containment evidence remain separate | No report path can mislabel policy denial as containment pass |
| WP-5 | Adding focused regression tests | Dallas | Ripley | WP-2, WP-3, WP-4 | Unit tests for allowed/denied behavior, redaction, classification boundaries, and no-fallback guardrails | New tests fail on broken auth separation and pass on intended behavior |
| WP-6 | Simplifying operator workflow | Parker | Ripley | WP-2 | Task targets/wiring for repeatable demo sequence and safe cleanup behavior | Operator has a short command order with explicit failure handling and no destructive ambiguity |
| WP-7 | Updating demo artifacts and presenter handoff | Lambert | Dallas | WP-5, WP-6 | `docs/demo-runbook.md`, `docs/telemetry-map.md`, `docs/evidence-template.md` aligned to shipped behavior | Cold presenter can execute checklist and classify outcomes correctly |
| WP-8 | Running demo rehearsal and signoff | Dallas | Brian | WP-7 | Rehearsal record for allowed/denied plus audit/enforced tool behavior using current command flow | Two consecutive runs are reproducible with same interpretation |

## Execution order

WP-0 → WP-1 → WP-2 → (WP-3 + WP-4 in parallel) → WP-5 → WP-6 → WP-7 → WP-8

## Task handoff rules for squad execution

- Every WP PR/patch includes: goal, files touched, test evidence, and open risks.
- Reviewer gate rules apply: Ripley reviews evidence-shaping changes; Dallas reviews test-result claims.
- If a WP is rejected, reassignment follows squad routing rules before retry.
