# KQL queries for the containment evidence

Run these in the Log Analytics workspace `humble-phoenix-46689-logs` (Logs blade). Both `AppDependencies`
(the platform egress decisions) and `ContainerAppConsoleLogs_CL` (receipts) are in that one workspace.

**Status:** every table and column used here is listed as VERIFIED in `telemetry-map.md` (§0.6.3, §0.12 to §0.14, §3.2).
These exact query texts were written on 2026-10-09 from those columns and **have not been run as written**; Dallas
ran equivalent queries for §0.14. Run one first and report any error before relying on it.

Set the run id once at the top of each query. The `run-…` id appears in the URL path of the decision row (`Data`)
and in the receipt line; the `ui-…` and harness ids do not join to it.

## 1. Every platform egress decision in a time window

```kusto
AppDependencies
| where TimeGenerated > ago(1h)
| where DependencyType == "NetworkEgressDecision"
| extend p = parse_json(Properties)
| extend run_id = extract(@"(run-[0-9a-f-]{36})", 1, Data)
| project TimeGenerated, run_id, Data,
          decision = tostring(p.decision), result = tostring(p.decisionResultCode),
          reason = tostring(p.decisionReasonCode), enforcement = tostring(p.enforcement),
          denyReason = tostring(p.denyReasonCode), host = tostring(p.host)
| order by TimeGenerated desc
```

## 2. Only the blocks of our tool calls (Deny under Enforced)

This excludes the agent's own telemetry export to Application Insights, which the policy also denies (query 8).

```kusto
AppDependencies
| where TimeGenerated > ago(24h)
| where DependencyType == "NetworkEgressDecision"
| extend p = parse_json(Properties)
| where tostring(p.decision) == "Deny" and tostring(p.enforcement) == "Enforced"
| where tostring(p.host) !endswith "applicationinsights.azure.com"
| extend run_id = extract(@"(run-[0-9a-f-]{36})", 1, Data)
| project TimeGenerated, run_id, host = tostring(p.host), reason = tostring(p.decisionReasonCode),
          denyReason = tostring(p.denyReasonCode), Data
| order by TimeGenerated desc
```

## 3. Audit would-denies (the same call allowed through)

```kusto
AppDependencies
| where TimeGenerated > ago(24h)
| where DependencyType == "NetworkEgressDecision"
| extend p = parse_json(Properties)
| where tostring(p.decisionResultCode) == "AuditWouldDeny"
| extend run_id = extract(@"(run-[0-9a-f-]{36})", 1, Data)
| project TimeGenerated, run_id, host = tostring(p.host), reason = tostring(p.decisionReasonCode), Data
| order by TimeGenerated desc
```

## 4. Decision counts by mode and outcome (the audit vs enforced contrast)

The `applicationinsights.azure.com` rows are the agent's own telemetry export, not our tools. Filter on `host` to separate them.

```kusto
AppDependencies
| where TimeGenerated > ago(24h)
| where DependencyType == "NetworkEgressDecision"
| extend p = parse_json(Properties)
| summarize calls = count() by enforcement = tostring(p.enforcement),
          decision = tostring(p.decision), result = tostring(p.decisionResultCode),
          host = tostring(p.host)
| order by enforcement asc, calls desc
```

## 5. Receipts at the controlled services for one run id

```kusto
let run = "run-REPLACE-ME";
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(24h)
| where Log_s has run
| extend j = parse_json(Log_s)
| project TimeGenerated, service = ContainerAppName_s, event = tostring(j.event),
          demo_run_id = tostring(j.demo_run_id), Log_s
| order by TimeGenerated asc
```

An enforced run that was blocked returns **no** `test-receiver` row here. Only count that absence if you read it
at least 180 s after the call.

## 6. The proof for one run id: decision rows and receipts side by side

```kusto
let run = "run-REPLACE-ME";
let decisions = AppDependencies
    | where TimeGenerated > ago(24h)
    | where DependencyType == "NetworkEgressDecision" and Data has run
    | extend p = parse_json(Properties)
    | project TimeGenerated, source = "platform decision", detail = strcat(
        tostring(p.decision), " / ", tostring(p.decisionReasonCode), " / ", tostring(p.enforcement)),
        where_ = tostring(p.host);
let receipts = ContainerAppConsoleLogs_CL
    | where TimeGenerated > ago(24h)
    | where Log_s has run and Log_s has "\"event\""
    | project TimeGenerated, source = "receipt", detail = "reached the destination", where_ = ContainerAppName_s;
union decisions, receipts
| order by TimeGenerated asc
```

Read it like this: a `Deny / DefaultDeny / Enforced` row on the external host with no `test-receiver` receipt after it
is the platform block. An `Allow` row followed by a `policy-api` receipt is the positive control. An `AuditWouldDeny`
row followed by a `test-receiver` receipt is the audit slot letting the same call through.

## 7. Which hosts did a run try to reach (any run)

Expect the Application Insights ingestion host to appear as `Deny` under `Enforced`.

```kusto
AppDependencies
| where TimeGenerated > ago(24h)
| where DependencyType == "NetworkEgressDecision"
| extend p = parse_json(Properties)
| summarize calls = count(), last = max(TimeGenerated) by host = tostring(p.host),
          decision = tostring(p.decision), enforcement = tostring(p.enforcement)
| order by last desc
```

## 8. The platform also denies the agent's own telemetry (seen in the portal, 2026-10-09)

```kusto
AppDependencies
| where TimeGenerated > ago(24h)
| where DependencyType == "NetworkEgressDecision"
| extend p = parse_json(Properties)
| where tostring(p.host) endswith "applicationinsights.azure.com"
| summarize calls = count(), last = max(TimeGenerated) by enforcement = tostring(p.enforcement),
          decision = tostring(p.decision), reason = tostring(p.decisionReasonCode), host = tostring(p.host)
| order by enforcement asc
```

Observed in the Application Insights end-to-end view: many `NetworkEgressDecision` rows, `Deny`, `DefaultDeny`, `enforcement=Enforced`,
host `canadacentral-1.in.applicationinsights.azure.com`, `POST //v2.1/track`. So the Enforced policy also blocks the agent's
telemetry exporter. **Not verified:** that this is why enforced app spans never land (telemetry-map §0.10). Confirm by comparing
the audit slot (same host should be `Allow`/`AuditWouldDeny`) before stating it.

## What these queries do not show

- The agent's HTTP 403, a DNS error, a timeout or the model's reply. Those are application-layer.
- `AMLManagedNetworkEvent`. It has returned zero rows on this account and is not verified to carry these decisions.
- The harness or façade traffic. Neither is governed by the Foundry policy.
- Never project the `gcp.vertex.agent.*` keys of `Properties` in queries: they can hold prompt and payload content.
