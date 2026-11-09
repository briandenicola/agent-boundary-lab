# Module 10: Monitoring and evidence queries

**Duration:** about 45 minutes

## Objectives

- Find the three evidence layers in Log Analytics and Application Insights.
- Join a platform egress decision to a receipt by run id.
- Deploy the evidence workbook and wire diagnostics links into the harness.

## Concepts

One Log Analytics workspace holds everything ([`monitoring.tf`](../../infra/cloud/monitoring.tf)):

| Layer | Table | Filter |
| --- | --- | --- |
| Platform egress decisions | `AppDependencies` | `DependencyType == "NetworkEgressDecision"` |
| Receipts at the controlled services | `ContainerAppConsoleLogs_CL` | `Log_s` JSON with `event == "receipt"` |
| Application / tool spans | Application Insights (see below) | privacy limited; not the proof |

**Real field names only** (from the [telemetry map](../telemetry-map.md)):

- Egress decision `Properties` keys (observed 2026-10-09): `decisionResultCode` (`Allow` or `AuditWouldDeny`), `decision` (`Allow` or `Deny`), `enforcement`, `decisionReasonCode` (`MatchedAllowRule`, `AuditWouldDefaultDeny`, and `DefaultDeny` under Enforced), `denyReasonCode`, `matchedRule`, `host`, `path`, `egressDecisionId`, `operationId`.
- Receipt fields: `service` (`policy-api` or `test-receiver`), `event` (`receipt`), `received_at`, `demo_run_id`, plus `outcome` (policy API) or `content_length_bytes` (receiver).

**How the join works.** The platform row carries no `demo_run_id` property.
The agent's run marker is in the decision's `Data` path and the receipt's
`demo_run_id`. Do not substitute an unrelated UI/harness marker or join on
`operationId`; see [the actual correlation contract](../telemetry-map.md).

Caveats you must repeat when presenting:

- The historical Enforced policy denied application telemetry export. New dedicated
  governance policies allow the existing ingestion host; validate real ingestion.
- `AMLManagedNetworkEvent` has returned zero rows and is not verified to carry decisions.
- Never project the `gcp.vertex.agent.*` keys of `Properties`; they can hold prompt content.
- Prompt, response, payload and authorization-header capture stays disabled.

## Walkthrough

### 1. Confirm logging is live

```bash
task cloud:app-insights-connection   # project must be connected to Application Insights
task cloud:logging-status            # read-only: diagnostic destinations, AKS collection, recent table activity
```

`cloud:logging-status` reports **observed** or **inconclusive**, never containment pass/fail. A declared diagnostic setting alone does not prove records arrived.

### 2. Run the KQL

Open the workspace Logs blade and use the queries in [`../kql-queries.md`](../kql-queries.md):

| Query | Use |
| --- | --- |
| 1 | Every egress decision in a window |
| 2 | Only Deny under Enforced for our tools |
| 3 | Audit `AuditWouldDeny` rows |
| 4 | Counts by mode and outcome (audit vs enforced contrast) |
| 5 | Receipts for one run id |
| 6 | **Proof for one run**: decisions and receipts side by side |
| 8 | The agent's own telemetry being denied |
| 10 | Policy API authorization decisions and served receipts for one tool run marker; identity evidence only. See [token flow](../token-flow-documented.md). |

Set `let run = "run-...";` to your id. Read query 6 like this: a `Deny / DefaultDeny / Enforced` row for the external host with no `test-receiver` receipt after it is the platform block. An `Allow` row then a `policy-api` receipt is the positive control. Wait at least 180 s after the call before counting an absence. The queries' own status note applies: they were written from verified columns but not all run as written, so report any error.

### 3. Deploy the workbook

```bash
task cloud:workbook-plan   # shows exactly one new resource
task cloud:workbook-up     # prompts first; creates the egress evidence workbook only
```

`cloud:up` also declares the workbook. The JSON lives at [`infra/cloud/workbooks/egress-evidence.workbook.json`](../../infra/cloud/workbooks/egress-evidence.workbook.json) and mirrors the KQL file.

### 4. Link diagnostics from the harness

The harness shows optional links to the workbook, Logs and Application Insights. They come from three env vars read when you create the Secret:

```bash
export HARNESS_WORKBOOK_URL='<portal URL of the workbook>'
export HARNESS_LOGS_URL='<portal URL of the workspace Logs blade>'
export HARNESS_APPINSIGHTS_URL='<portal URL of the Application Insights resource>'
task chat-agent:secret
```

`chat-agent:secret` keeps the existing token unless `ROTATE=1`, writes only the variables that are set, and restarts the harness deployment so it picks them up. If the links are missing, you skipped this step ([Module 12](12-troubleshooting.md)). Use `task chat-agent:token` to read the login token. URLs are links only; they contain no secrets.

### 5. Optional: cross-check with the verifier

`scripts/verify_demo.py` queries the same tables and prints the `matched_run_ids` it found, which is a quick sanity check against your manual KQL.

## Code tour

| What | Where |
| --- | --- |
| Workspace, App Insights, DCR, diagnostics | [`infra/cloud/monitoring.tf`](../../infra/cloud/monitoring.tf) |
| Workbook resource | [`infra/cloud/monitoring.tf` L118-L139](../../infra/cloud/monitoring.tf#L118-L139) |
| Diagnostics link settings | [`src/containment_demo/harness/settings.py` L58-L64](../../src/containment_demo/harness/settings.py#L58-L64) |
| Secret creation with optional links | [`tasks/Taskfile.harness.yml` L60-L91](../../tasks/Taskfile.harness.yml#L60-L91) |
| Receipt emitters | `services/policy_api/main.py`, `services/test_receiver/main.py` |
| Telemetry privacy controls | [Telemetry map](../telemetry-map.md#privacy-and-run-checklist) |

## Checkpoint

- [ ] Query 6 for your audit run shows a decision row and a `test-receiver` receipt.
- [ ] Query 6 for your enforced run shows `Deny / DefaultDeny / Enforced` and no receiver receipt after at least 180 s.
- [ ] The workbook opens and the harness shows its diagnostics links.

**Next:** [Module 11: Teardown and rebuild](11-teardown-and-rebuild.md)
