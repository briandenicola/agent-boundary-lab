# Module 09: Run and verify

Follow the [demo runbook](../demo-runbook.md) for the full procedure. This module explains what you are proving.

## Expected results

| Outcome | Audit | Enforced |
| --- | --- | --- |
| Authorized user, servicing tool | Policy API 200, verified identity | Same |
| Unauthorized user, servicing tool | 403 `user_not_authorized` | Same |
| External-processing tool | Receiver receipt; platform `AuditWouldDeny` | Platform Deny; no receiver receipt |

The first two rows are identity. Only the last row is the network experiment.

## Steps

1. Complete the runbook [preflight](../demo-runbook.md#preflight).
2. Sign in as each synthetic user in separate browser sessions and read the policy-access card.
3. As the authorized user, run both tools on both agents. Note each `run-...` marker and the UTC time the tools ran.
4. Wait at least 180 seconds, then verify:

```bash
.venv/bin/python scripts/verify_demo.py --section b \
  --audit-run-id <run-id> --audit-called-at <tool-time-UTC>
.venv/bin/python scripts/verify_demo.py --section c \
  --enforced-run-id <run-id> --enforced-called-at <tool-time-UTC>
```

Exit 0 is pass, 1 is fail, 2 is inconclusive. Use the tool execution time, not the chat reply time; a later time can miss the real decision row.

## What counts as a network pass

All of these: the matching platform decision, a successful servicing receipt (the positive control), the receiver receipt present or absent as expected, a window of at least 180 seconds, and no unattributed receiver arrivals. The run marker appears in the platform URL path and the receipt JSON. `OperationId` and UI-only IDs don't substitute.

Local runs, including `app:run-allowed` and `app:run-denied`, are functional tests, not containment proof. Missing evidence is inconclusive.

Record results with the runbook's [evidence record](../demo-runbook.md#evidence-record). For Copilot and ACS, use the [governance walkthrough](../governance-demo.md).

**Next:** [10 Monitoring](10-monitoring.md)
