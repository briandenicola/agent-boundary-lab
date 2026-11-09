# Module 09: Run and verify

Use the [demo runbook](../demo-runbook.md) for the authoritative baseline procedure.
It replaces the earlier issue-specific readiness checklists. Dated live results
are in the [telemetry map](../telemetry-map.md#dated-baseline-results).

## Objectives

- Show allowed/denied user access separately from Audit/Enforced egress.
- Verify platform decisions and receipts using the hosted run marker.
- Report pass, fail or inconclusive without inferring proof from agent prose.

## Expected baseline outcomes

| Outcome | Audit | Enforced |
| --- | --- | --- |
| Authorized user, servicing tool | Policy API 200 and verified identity | Same |
| Unauthorized user, servicing tool | 403 `user_not_authorized` | Same |
| External-processing tool | Receiver receipt, platform AuditWouldDeny | Platform Deny, no receiver receipt |

The first two rows are identity outcomes. Only the last row is the network
experiment. A rejected servicing call is not a valid receipt positive control.

## Walkthrough

1. Complete [runbook preflight](../demo-runbook.md#preflight). Check current versions,
   one immutable digest, policy attachments and a working monitoring connection.
2. Open the configured HTTPS harness as each synthetic user, in separate browser
   sessions. Inspect the policy-access card, not the actor alias.
3. As the authorized user, request both tools on both baseline agents. Record each
   hosted `run-...` marker and the UTC time when its tools execute.
4. Wait at least 180 seconds, then run the read-only verifier:

```bash
.venv/bin/python scripts/verify_demo.py --section b \
  --audit-run-id <audit-run-id> --audit-called-at <tool-execution-UTC>
.venv/bin/python scripts/verify_demo.py --section c \
  --enforced-run-id <enforced-run-id> --enforced-called-at <tool-execution-UTC>
```

Exit 0 = pass, 1 = fail, 2 = inconclusive.
Check the matched markers. A later chat-reply timestamp can exclude the real
decision row; use the actual tool-execution time.

A network pass needs the correlated platform decision, the successful servicing
receipt, receiver presence/absence as expected, a mature window and no unattributed
receiver arrivals. The run marker is embedded in the platform URL path and receipt
JSON; `OperationId` and UI-only IDs are not substitutes.

`app:run-allowed` / `app:run-denied` are offline actor-context tests, not these live
Entra calls. Local runs are functional tests, never containment proof.

## Record

Use the [runbook's evidence record](../demo-runbook.md#evidence-record) for each run.
Keep identity, ACS and network verdicts separate; missing required evidence is
inconclusive. For Microsoft 365 Copilot and ACS, use the
[governance guide](../governance-demo.md), not the baseline harness.

**Next:** [Module 10: Monitoring](10-monitoring.md).
