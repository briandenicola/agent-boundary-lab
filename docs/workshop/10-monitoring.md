# Module 10: Monitoring

One Log Analytics workspace holds the evidence ([`monitoring.tf`](../../infra/cloud/monitoring.tf)).

| Layer | Table | Filter |
| --- | --- | --- |
| Platform egress decisions | `AppDependencies` | `DependencyType == "NetworkEgressDecision"` |
| Receipts at the controlled services | `ContainerAppConsoleLogs_CL` | `Log_s` JSON with `event == "receipt"` |
| Application and tool spans | `AppTraces` | `Message == "demo.tool_result"`; not proof of containment |

Field names are in the [telemetry map](../telemetry-map.md). The two that matter most:

- Decision rows carry `decisionResultCode` (`Allow` or `AuditWouldDeny`), `decision`, `enforcement`, `host` and `path`.
- Receipts carry `service`, `received_at` and `demo_run_id`.

## Joining the layers

The platform row has no `demo_run_id`. The run marker is in its `Data` path and in the receipt's `demo_run_id`. Join on that, not on `operationId`.

## Steps

Confirm logging works:

```bash
task cloud:app-insights-connection
task cloud:logging-status
```

`logging-status` reports observed or inconclusive, never pass or fail.

Run the queries in [`kql-queries.md`](../kql-queries.md) in the workspace Logs blade. Query 6 is the main one: it shows decisions and receipts for one run side by side. Set `let run = "run-...";`.

- Enforced: a `Deny / DefaultDeny / Enforced` row for the external host and no `test-receiver` receipt afterward.
- Audit: an `AuditWouldDeny` row followed by a receipt.
- Positive control: an `Allow` row then a `policy-api` receipt.

Wait 180 seconds before treating an absence as meaningful.

The workbook (`cloud:workbook-plan`, `cloud:workbook-up`) mirrors these queries. `cloud:up` also creates it. To link it from the harness, see [module 08](08-harness-ui.md#diagnostics-links).

## Limits

- `AMLManagedNetworkEvent` has returned no rows and isn't known to carry decisions.
- The original Enforced policy blocked the agent's own telemetry export. The newer governance policies allow it; confirm ingestion actually works.
- Never project `gcp.vertex.agent.*` properties; they can contain prompt text. Prompt, response, payload and authorization-header capture stay off.

**Next:** [11 Teardown and rebuild](11-teardown-and-rebuild.md)
