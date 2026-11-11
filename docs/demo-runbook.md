# AKS/Foundry demo

[Deploy in Azure](rebuild-runbook.md) | [Copilot demo](governance-demo.md)

Show two things separately: **who may read the policy** and **where the agent
may send traffic**.

## Preflight

```bash
task cloud:target-check
task cloud:kubeconfig
task foundry-agent:status
task build:foundry-agent-digest
task cloud:policies
task cloud:app-insights-connection
task tool-apis:check
```

Check that both agents are active, use the same image digest, and have the
intended Audit/Enforced policies. Use this deployment's resources and logs.

## Show user authorization

1. Open your HTTPS harness and sign in as the allowed test user.
2. Ask for the servicing policy. The **Policy API access** card should show
   `allowed`: HTTP 200 with a verified identity.
3. Repeat in a private browser as the denied user. The same tool should return
   `403 user_not_authorized`, shown as `denied`.

The display alias does not grant access. A missing token or identity is a failed
identity demonstration, not a network block.
[How authorization works](token-flow-documented.md)

## Show network containment

As the allowed user, ask the harness to run both business tools on both agents.
Record each structured result's **`run-...` marker** and tool-execution UTC time.

| Tool | Audit | Enforced |
| --- | --- | --- |
| Policy lookup | Succeeds | Succeeds |
| External processing | Receiver gets the request | Platform blocks the request |

**What to say:** “Both agents have the same tools and code. Audit records the
denial but lets the request through. Enforced prevents it from reaching the receiver.”

Check logs before claiming the block. The agent's prose or HTTP 403 alone is
not enough.

## Verify platform evidence

Wait at least **three minutes** after execution, then run:

```bash
.venv/bin/python scripts/verify_demo.py --section b \
  --audit-run-id <audit-run-id> --audit-called-at <tool-execution-UTC>
.venv/bin/python scripts/verify_demo.py --section c \
  --enforced-run-id <enforced-run-id> --enforced-called-at <tool-execution-UTC>
```

These queries do not invoke the agent. Exit codes: **0 pass, 1 fail,
2 inconclusive**. Check `matched_run_ids`; the browser's `ui-...` marker and
later reply timestamp are not substitutes.

| Evidence | Audit | Enforced |
| --- | --- | --- |
| Platform decision for receiver | `AuditWouldDeny` | `Deny` / `Enforced` |
| Successful servicing receipt | Present | Present |
| Receiver receipt | Present | Absent after the ingestion window |

Platform rows come from `AppDependencies`, with
`DependencyType == "NetworkEgressDecision"`. Receipts come from parsed
`ContainerAppConsoleLogs_CL.Log_s`. Join by the run marker.

Missing decisions, failed queries, missing positive controls, or unattributed
receiver arrivals make the result **inconclusive**. A matching receiver receipt
contradicts an Enforced block. A model refusal means no request was attempted.
[Queries](kql-queries.md) · [Fields and recorded results](telemetry-map.md)

## Development access

Without HTTPS sign-in, use the shared-token interfaces:

```bash
task chat-agent:token
task chat-agent:open        # http://localhost:8082
# Or the deterministic two-button UI:
task test-ui:token
task test-ui:open           # http://localhost:8081
```

These are not Entra identity demonstrations. The AKS harness and CPU model are
outside Foundry's egress boundary.

## Hosted governance comparison

For the optional [seven-scenario comparison](PLAN.md#governance-comparison):

```bash
task acs:status
GOVERNANCE_TOKEN_FILE=/private/path/tokens.json task governance:run
# Wait at least three minutes after completion.
task governance:verify
```

This makes **fourteen billable hosted calls**, not a Copilot conversation.
The mode-600 token file contains `foundry_access_token` and `policy_access_token`.
Keep it private. For the end-user experience, use the [Copilot walkthrough](governance-demo.md).

## Evidence record

Save the UTC window, run marker, image digest, agent version, policy readback,
and matching decision/receipt references. Record identity, ACS, and network
outcomes separately as pass, fail, or inconclusive. Use synthetic user aliases;
exclude tokens and model content.

For cleanup, use the [deployment guide](rebuild-runbook.md#cleanup).
