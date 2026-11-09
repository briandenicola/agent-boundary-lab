# Telemetry and evidence map

Consolidated 2026-11-09 from observed rows and the shipped emission code.
Superseded empty-sink probes and rejected `AppTraces` egress queries are in Git
history. Do not use those early experiments as current operator instructions.

## Sources and correlation

| Layer | Actual source | Run correlation |
| --- | --- | --- |
| Application | `AppTraces`, `Message == "demo.tool_result"` observed for Audit | `Properties["demo.run_id"]` |
| ACS governance | `demo.governance_decision` source emission | Candidate hosted mapping; inspect real rows before relying on it |
| Foundry egress | `AppDependencies`, `DependencyType == "NetworkEgressDecision"` | Run marker in `Data` / `Properties.path` |
| API receipt | `ContainerAppConsoleLogs_CL`, JSON string `Log_s` | Parsed `demo_run_id` |
| Policy API authorization | Same console table, parsed `event == "authorization_decision"` | Parsed `demo_run_id`; identity only |
| AKS stdout/stderr | `ContainerLogV2` | Only safe application metadata; not platform decision evidence |

The path join was observed 2026-10-09. `/policy/{run_id}` and `/ingest/{run_id}`
retain the same marker that API receipt JSON records. The platform did **not** share
application `OperationId` in the checked baseline. A UI-only `ui-...` ID is not a
replacement for the hosted `run-...` marker.

Use the current state's workspace and app names, not an old environment's IDs.
Primary schema observations came from the October environment; each rebuilt
deployment must establish its own ingestion and run evidence.

## Application fields

`telemetry.py` emits an explicit allowlist, not arbitrary result dictionaries.

| Attribute | Meaning |
| --- | --- |
| `demo.run_id` | Synthetic run marker |
| `demo.policy_mode` | local / audit / enforced; evidence label only |
| `demo.agent_name`, `demo.agent_version` | Runtime identity/version labels |
| `demo.tool_name` | One of the two business tools |
| `demo.succeeded`, `demo.http_status` | Application outcome; status omitted for transport failure |
| `demo.error_category`, `demo.error_detail` | Classified and sanitized failure |
| `demo.duration_ms`, `demo.destination_host` | Duration and configured destination |
| `demo.user_token_forwarded` | Presence only; never the token or user ID |

HTTP/TLS/DNS/timeout/connection errors remain distinct. The application cannot
declare a platform denial from HTTP status. Governed blocked results separately
use `governance_denied` / `governance_error` with no HTTP status.

Audit application rows preserved dotted keys in the October observation.
Enforced telemetry was blocked by the old egress policy; later dedicated governance
policies explicitly allow the existing telemetry ingestion hostname. That configuration
is not yet a new hosted event-ingestion result.

## ACS decision evidence

The source-defined governance record contains run/trace/session/tool-call identifiers,
agent/version, mode, policy ID/version, verdict, host action, reason, duration and
timestamp. It contains no token, tool arguments, prompt, payload or raw ACS snapshot.
See `src/containment_demo/telemetry.py` for exact current emission.

`scripts/verify_governance.py` has candidate Azure mappings. Real hosted ACS rows
have not yet been inspected, so absent events cannot pass the comparison.
ACS blocking occurs before HTTP execution; requiring a platform denial for a call
that did not execute would be the wrong evidence contract.

## Platform fields

Observed 2026-10-09 in workspace-scoped `AppDependencies`:

| Column / property | Observed use |
| --- | --- |
| `TimeGenerated`, `Target`, `Data` | Timestamp, host and outbound URL |
| `DependencyType` | `NetworkEgressDecision` |
| `Properties.decision` | Allow / Deny |
| `Properties.decisionResultCode` | Allow / AuditWouldDeny / Deny |
| `Properties.enforcement` | Audit / Enforced |
| `Properties.decisionReasonCode` | MatchedAllowRule / AuditWouldDefaultDeny / DefaultDeny |
| `Properties.denyReasonCode` | NoMatchingAllowRule on the observed default deny |
| `Properties.host`, `Properties.path` | Destination and run-bearing path |
| `Properties.matchedRule` | Matched policy rule |
| `Properties.egressDecisionId` | Platform decision identifier |
| `OperationId`, `ParentId` | Platform tracing; not an observed app-layer join |

These are observed fields, not names inferred from portal UI labels.
Keep raw-row schema discovery separate from projecting prompt/response data.
Do not substitute `AMLManagedNetworkEvent`, `AzureDiagnostics`, generic firewall
logs or application error traces for the RAI decision source.

```kusto
AppDependencies
| where TimeGenerated between (datetime(<RUN_START>) .. datetime(<RUN_END>))
| where DependencyType == "NetworkEgressDecision" and Data has "<RUN_ID>"
| extend p = parse_json(Properties)
| project TimeGenerated, Target, Data,
          decision = tostring(p.decision),
          result = tostring(p.decisionResultCode),
          enforcement = tostring(p.enforcement),
          reason = tostring(p.decisionReasonCode),
          host = tostring(p.host), path = tostring(p.path)
| order by TimeGenerated asc
```

## Receipts and identity decisions

Both services emit JSON lines to stdout; parse `Log_s`.
Filter on `event`, not stdout stream or access-log message text.

| Receipt field | Meaning |
| --- | --- |
| `event` | `receipt` for a served business request |
| `service` | `policy-api` / `test-receiver` |
| `demo_run_id` | Header/query marker |
| `received_at` | Service UTC timestamp |
| `outcome` | `served` on policy retrieval |
| `method`, `path` | Policy request metadata; protected paths can be redacted |
| `content_length_bytes` | Receiver measures/discards body, never records payload |

Policy API failures emit `authorization_decision`, `auth_error`, `outcome` and
`determination=identity_only`. A verified unauthorized user can appear in the receipt,
but raw identifiers must not be copied into demo reports. Tool-result identity fields
and receipt fields are separate schemas; `user_token_forwarded` is not a receipt field.

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated between (datetime(<RUN_START>) .. datetime(<RUN_END>))
| where ContainerAppName_s in ("<POLICY_APP>", "<RECEIVER_APP>")
| extend r = parse_json(Log_s)
| where tostring(r.event) == "receipt" and tostring(r.demo_run_id) == "<RUN_ID>"
| project TimeGenerated, service = tostring(r.service),
          demo_run_id = tostring(r.demo_run_id),
          received_at = tostring(r.received_at), outcome = tostring(r.outcome)
```

`/healthz` is deliberately not a receipt. A health ping is not a positive control.
For protected servicing, require an identity-verified successful receipt, not a 401/403.

An empty-marker receiver receipt was observed in the early baseline. Always check
for unattributed arrivals in the same bounded window. A matching receiver receipt
contradicts a claimed block; empty-marker arrivals make absence inconclusive.
Wait at least 180 seconds after run completion before counting absence, and prove
receipt ingestion with a successful same-run servicing call.

## Monitoring configuration

The project Application Insights connection is the platform egress telemetry route.
Resource diagnostic settings are independent; `logAnalyticsDestinationType` is omitted
because Azure did not support the requested `Dedicated` value for this resource.
New setting acceptance alone is not data ingestion.

After the owner-applied 2026-10-19 monitoring repair, read-only checks observed
`ContainerLogV2` (219 rows), `AzureDiagnostics` (38 rows), application tables,
`KubeEvents` and `KubePodInventory`. Existing governance destinations remained intact.
This establishes routing, not per-run containment.

`task cloud:logging-status` checks configured destinations, associations and recent
table activity without log bodies. A naturally quiet table is not automatically broken.
`ManagedNetworkEvent` and underlying managed-firewall traffic logs are not established
RAI egress evidence. Microsoft's managed-network reference explicitly limited outbound
firewall logging as checked 2026-10-19.

## Dated baseline results

These are historical results, not current environment inventory or new ACS evidence.

| Date / path | Run marker | Recorded result |
| --- | --- | --- |
| 2026-10-09 direct, Audit v9 | `run-2b95fdf4-0570-4719-ab1d-31d5ab110967` | Allow + servicing receipt; AuditWouldDeny + receiver receipt; path join directly observed |
| 2026-10-09 direct, Enforced v7 | `run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4` | Allow + servicing receipt; Deny/Enforced and no receiver receipt, rechecked 229 s later |
| 2026-10-09 A2A facade, Audit | `run-ebc8e204-9f05-4068-a9cd-8daf8c0d7723` | Verifier B PASS |
| 2026-10-09 A2A facade, Enforced | `run-a86344d2-5c00-44f1-803c-771e8682af6c` | Verifier C PASS, absence read at 333 s |
| 2026-10-09 UI, Audit | `run-c9e4afa5-fd3e-4afa-953c-e8b048776fef` | Verifier B PASS |
| 2026-10-09 UI, Enforced | `run-ac17f6c6-02f4-4e77-b697-35d73bab3e06` | Verifier C PASS, absence read at 220 s |
| 2026-10-09 CPU harness, Audit | `run-533642af-d2db-4147-95bc-e9147145eedd` | B PASS, decision/receipt join independently queried |
| 2026-10-09 CPU harness, Enforced | `run-7b3574d2-d11c-4a7b-b4c8-122516a549c9` | C PASS, independent query, absence read at 627 s |
| 2026-10-19 Sweden Central, Audit v2 | `run-8c7cf2d5-84f5-4479-bb4e-a7f164935c60` | Owner-reported tools 200/202 and verifier PASS |
| 2026-10-19 Sweden Central, Enforced v2 | `run-1cf1dc35-dffa-41de-bbe6-655ea8c2d0f0` | Owner-reported tools 200/403 and verifier PASS |

The four facade/UI verifier joins were inferred from the verifier's queries, not
independently requeried in that record. The October 19 full verifier JSON was not
retained in the session. Sample sizes are small, and a no-receipt observation is
bounded by its read time. Model prose misreported a tool failure in the CPU run;
the structured records and platform rows were authoritative.

On 2026-11-06 the owner confirmed the identity/egress baseline had been tested.
On 2026-11-09 the real APIs and isolated governance versions were deployed/configuration
verified, with no hosted comparison calls. Do not relabel either update as new ACS
runtime evidence.

## Privacy and run checklist

- Capture stays off at the SDK/ADK source, not merely hidden by KQL projection.
  No prompts, responses, payloads, authorization headers, token claims or environment
  dumps in telemetry.
- Keep real request markers and timestamps; do not infer correlation from prose.
- Check served version, policy and shared image digest.
- Collect decision rows, successful positive control, receiver count and unattributed
  arrivals for the same explicit window.
- Keep identity, ACS and network verdicts separate.
- Save [an evidence record](evidence-template.md); missing signals are inconclusive.
