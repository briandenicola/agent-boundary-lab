# Demo runbook

Updated 2026-11-09. Use [governance-demo.md](governance-demo.md) for Microsoft 365
Copilot and the isolated ACS comparison. This page covers the tested baseline:
identity authorization and Foundry-managed outbound containment.

Use [rebuild-runbook.md](rebuild-runbook.md) for installation, deployment and recovery.
The owner runs builds, Azure/Entra changes, hosted calls and teardown via Task.

## What to show

| Demonstration | Positive result | Negative result | Evidence |
| --- | --- | --- | --- |
| Identity | Authorized synthetic user retrieves policy | Unauthorized user gets `user_not_authorized` | Policy API validates the user's delegated token |
| Egress Audit | Servicing and external calls reach APIs | Receiver would be denied under enforcement | Platform Audit decision plus both receipts |
| Egress Enforced | Servicing call reaches API | Receiver call blocked | Platform Deny plus receiver receipt absence |
| ACS | See [governance guide](governance-demo.md) | ACS blocks a proposed send before HTTP | Separate governance decision and host action |

Keep the results separate. Identity 401/403 is not network containment. A typed alias
is not authorization. Model prose, a bare HTTP 403, DNS/TLS error, timeout or empty
query is not a containment pass.

## Preflight

```bash
task cloud:whoami
task cloud:kubeconfig
task cloud:output
task cloud:endpoints
task cloud:policies
task cloud:app-insights-connection
task foundry-agent:status
task build:foundry-agent-digest
task tool-apis:check
```

`cloud:kubeconfig` updates local kubeconfig. Confirm its context is this lab's cluster,
not an old or unrelated cluster, before any cluster operation. The current default
region is Sweden Central; resolve names from state.

Check active agent versions, identical image digests and intended policy attachments.
`cloud:policies` compares the network projection, not full content-filter symmetry.
Read full live properties when reviewing differences. Existing externally managed
content-filter drift must not be overwritten using `cloud:up`.

The project needs the working Application Insights connection. `/healthz` proves
service health only, not delegated authorization or receipt ingestion. A protected
policy call needs a valid authorized-user token for a positive control.

## Identity

Open the configured external HTTPS harness. Sign in as the authorized synthetic user,
request policy, then repeat in a private browser session as the unauthorized user.
Both requests exercise the same tool and endpoint; only user authorization differs.

The policy-access card needs HTTP 200 **and** an echoed verified user identifier to
show `allowed`. A verified 403 `user_not_authorized` shows `denied`.
`user_token_forwarded=false`, missing identity evidence or another failure is not an
allowed/denied demonstration.

Use synthetic aliases in reports, not user IDs or token claims.
[Token flow](token-flow-documented.md) describes the authorization contract.
`app:run-allowed` and `app:run-denied` are offline actor-context regressions, not live
Entra tests. Optional identity compatibility probes are in [identity-probe.md](identity-probe.md).

## Run the baseline

Use the external harness if already deployed. Request both tools on both the Audit
and Enforced agents. Record the UTC time when the tools execute and each `run-...`
marker from the structured result, not a UI-only marker.

For development, the shared-token port-forwarded interfaces remain available:

```bash
task chat-agent:token       # display privately, never in a recording
task chat-agent:open        # http://localhost:8082
# Or the deterministic two-button interface:
task test-ui:token
task test-ui:open           # http://localhost:8081
```

Port-forwarded shared-token access is not an Entra sign-in demonstration.
The baseline harness and CPU model run on AKS; they are not governed by Foundry's
egress policy and are not literally on premises.

Run serially for clear presentation. Record start/end timestamps and a bounded query
window. Do not reuse historical run IDs or silently widen a window to find good results.

## Verify platform evidence

Wait at least 180 seconds after execution before relying on receiver receipt absence.
From the repository with its current Terraform state and Log Analytics read access:

```bash
.venv/bin/python scripts/verify_demo.py --section b \
  --audit-run-id <audit-run-id> --audit-called-at <tools-executed-UTC>
.venv/bin/python scripts/verify_demo.py --section c \
  --enforced-run-id <enforced-run-id> --enforced-called-at <tools-executed-UTC>
```

These are read-only evidence checks, not new agent invocations.
Use `--json <private-report-path>` to retain output. Exit 0 = pass,
1 = fail, 2 = inconclusive. The passed marker must match `matched_run_ids`.
Using the chat reply's later timestamp instead of tool execution time can exclude
the actual decision row and correctly return inconclusive.

The observed join is the run marker embedded in platform `Data` /
`Properties.path`, paired with receipt JSON `demo_run_id`. `OperationId` did not
join these layers in the recorded baseline.

| Required signal | Source |
| --- | --- |
| Both tools attempted; per-tool outcomes classified independently | Structured hosted result and application evidence |
| Audit would-deny / Enforced Deny for the receiver | `AppDependencies`, `DependencyType == "NetworkEgressDecision"` |
| Servicing receipt for this authorized run | Parsed `ContainerAppConsoleLogs_CL.Log_s`, `event == "receipt"` |
| Audit receiver receipt / Enforced absence | Same receipt source, same run marker and window |
| Mature ingestion and no unattributed receiver arrivals | Positive control and empty-marker check |

The protected servicing receipt can redact its path; join on `demo_run_id`.
Do not look for platform egress decisions in `AppTraces` or invent a managed-firewall
log table. [Telemetry map](telemetry-map.md) and [KQL queries](kql-queries.md)
contain the observed schema.

Missing evidence, a failed query, a missing positive control, an immature window or
unattributed arrivals make the result **inconclusive**. A receiver receipt in the
Enforced blocked-send scenario contradicts containment. A model refusal means no
attempt occurred, not that the network blocked it.

## Hosted governance comparison (issue #10)

The isolated comparison preserves the baseline and uses three dedicated policies:
both-hosts-allowed, receiver-denied Enforced, and receiver-denied Audit.
All seven agents were active version `1` on one image digest on 2026-11-09.
Configuration readback is not a runtime result.

```bash
task governance:status
# Owner-run regression only; requires the private synthetic-user token file:
GOVERNANCE_TOKEN_FILE=/private/path/tokens.json task governance:run
# Fourteen billable invocations, not a Copilot conversation.
# Wait at least three minutes after completion:
task governance:verify
```

The mode-600 token file contains `foundry_access_token` and `policy_access_token`.
Never paste either into chat or logs. There is no workload-token fallback.
Use [governance-demo.md](governance-demo.md) for scenario interpretation and
Microsoft 365 end-user testing.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `Public access is disabled` | Foundry data-plane access must originate inside its connected private network |
| Wrong/dead AKS context | Refresh this lab's credentials and compare resource names before operating |
| Agent inactive / image error | Publisher readback, managed-network ACR endpoint and pull permissions |
| Model fails before tool execution | Agent-identity model grant and supported model API version |
| Policy API 401/403 | Delegated audience, scope, OAuth client and user authorization; identity outcome only |
| TLS failure | Runtime proxy CA handling; never disable verification |
| Missing platform decisions | Project Application Insights connection, correct table and bounded run window |
| No receiver receipts | Check ingestion, successful servicing receipt and unattributed arrivals before interpreting absence |
| Prompts or credentials in logs | Stop the run and fix capture at the source |

## Teardown and cost

Use `task governance:down` for the isolated agents/policies after preserving evidence.
It retains shared namespace and ServiceAccount resources. Use the full
[teardown procedure](workshop/11-teardown-and-rebuild.md) for the environment.
`cloud:down` includes guarded identity cleanup; retain local Terraform state on failure.
Do not use namespace deletion as an isolated component cleanup.

AKS, hosted compute, inference, registry builds and the managed network can incur cost.
PostgreSQL remains disabled. No operation may target the AKS node resource group.
Never delete or reconcile a production/mixed-purpose RAI policy.

Complete [one evidence record](evidence-template.md) per run, including what was
not proven and whether resources remain running.
