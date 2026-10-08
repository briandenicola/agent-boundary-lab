# Telemetry and evidence map

**Owner:** Lambert (telemetry / evidence). **Last validation pass: 2026-10-08.**

Every row below is exactly one of:

- **VERIFIED** — read from a real query result against this lab's resources, from this
  repo's source, or from a primary Microsoft reference. Source and date are given.
- **NOT VERIFIED** — not yet observed. The exact procedure to verify it is given. These
  must never be presented as fact, quoted in a report, or used in a demo narrative.

There is no third state. A plausible-looking KQL column that returns nothing is worse than
no query at all, because the audience concludes the platform did nothing.

**Live resources used for verification (read-only):**

| Thing | Value |
| --- | --- |
| Subscription | `ccfc5dda-43af-4b5e-8cc2-1dda18f2382e` |
| Resource group | `humble-phoenix-46689-rg` (canadacentral) |
| Log Analytics workspace | `humble-phoenix-46689-logs`, customerId `def03e45-a400-4fed-957f-25d133ab1993` |
| Application Insights | `humble-phoenix-46689-ai`, AppId `bddb3269-3c02-44a4-bb2e-baf979538d6c` |
| Foundry account / project | `humble-phoenix-46689-foundry` / `humble-phoenix-46689-project` |

---

## 0. Blocking finding — platform egress evidence has nowhere to land today

**VERIFIED 2026-10-08.** The Foundry project has **no connections at all**:

```
GET .../accounts/humble-phoenix-46689-foundry/projects/humble-phoenix-46689-project
    /connections?api-version=2025-06-01
→ {"value": []}
```

`docs/compatibility.md` C1/C4 establish that egress-decision visibility is tied to the
**project's** Application Insights, and that no separate diagnostic-settings category was
found. The App Insights component `humble-phoenix-46689-ai` exists and is healthy, but it
is **not linked to the project**. Until it is, Layer 2 of the evidence model produces
nothing, and a run would be **inconclusive by construction** — not a pass, not a fail.

Fix is Parker's (Terraform, project connection of category `AppInsights`). Flagged in the
decision inbox. Do not schedule a demo run before this is done and a decision row is
observed.

**VERIFIED 2026-10-08:** App Insights `IngestionMode` is `LogAnalytics` and its
`WorkspaceResourceId` points at `humble-phoenix-46689-logs`. Consequence for every query
below: this is a **workspace-based** component, so at workspace scope the table names are
the `App*` set (`AppTraces`, `AppDependencies`, …), while the classic names (`traces`,
`dependencies`, with `message` / `customDimensions` / `operation_Id`) only resolve when you
query the App Insights **resource** scope. Both are correct; the scope decides. See §5 for
the reconciliation with `docs/compatibility.md` C1.

---

## 1. Layer 1 — application / tool traces (emitted by our own code)

Source of truth: `src/containment_demo/telemetry.py`, `src/containment_demo/tools.py`,
`src/containment_demo/settings.py`. These are **our** field names, so they are verified
from source. What is *not* verified from source is how the Azure Monitor exporter lands
them in a table — that needs a live run.

### 1.1 Span attributes attached to every span — VERIFIED (source)

`telemetry.py :: run_attributes()`

| Attribute | Type | Source |
| --- | --- | --- |
| `demo.run_id` | string, `run-<uuid4>` | `telemetry.py` `run_attributes` |
| `demo.policy_mode` | string enum: `local` \| `audit` \| `enforced` | ditto; evidence label only, never branched on |
| `demo.agent_name` | string | ditto |
| `demo.agent_version` | string; `FOUNDRY_AGENT_VERSION` env, or `local` | `settings.py` `agent_version` |

### 1.2 Tool-outcome span event — VERIFIED (source)

`telemetry.py :: emit_tool_evidence()` adds a span event named **`demo.tool_result`**.
Its attributes are an explicit allow-list — a new field on a tool result cannot leak by
default. Attributes whose value is `None` are omitted.

| Attribute | Type | Values |
| --- | --- | --- |
| `demo.tool_name` | string | `get_servicing_policy` \| `send_to_external_processor` |
| `demo.succeeded` | bool | |
| `demo.http_status` | int \| absent | absent on transport failure |
| `demo.error_category` | string | `none`, `http_error`, `tls_error`, `dns_error`, `timeout`, `connection_error`, `unexpected` (`settings.py :: ErrorCategory`) |
| `demo.error_detail` | string | `"<ExceptionType>: <first 200 chars>"`, sanitised in `tools.py :: _sanitize` |
| `demo.duration_ms` | float | |
| `demo.destination_host` | string | |
| plus all of §1.1 | | |

**There is deliberately no `policy_denied` value.** The application cannot observe a
platform decision. Attribution is the verifier's job, never a tool's.

### 1.3 Where those land in Log Analytics — NOT VERIFIED

| Question | Status | How to verify |
| --- | --- | --- |
| Does a span **event** become an `AppTraces` row with `Message == "demo.tool_result"` and attributes under `Properties`? | **NOT VERIFIED** | Deploy an agent version, run one invocation, then `AppTraces \| where TimeGenerated > ago(30m) \| take 20` and read `Message` and `Properties` off a real row. |
| …or does it become an `AppDependencies` / `AppEvents` row instead? | **NOT VERIFIED** | Same run; `union AppTraces, AppDependencies, AppEvents, AppRequests \| where Properties has "demo.run_id" \| summarize count() by Type`. This is the single most useful first query — run it before writing any other. |
| Are attribute keys preserved verbatim as `demo.run_id`, or flattened/renamed (e.g. `demo_run_id`)? | **NOT VERIFIED** | Read `Properties` keys off the real row. Do **not** assume dots survive. |
| Does the no-recording-span fallback path (`tracer.start_as_current_span("demo.tool_result")`) ever fire in the hosted runtime? | **NOT VERIFIED** | If it does, the record appears as a span, not an event — likely `AppDependencies` with `Name == "demo.tool_result"`. Check both. |
| Do the `httpx` calls themselves appear as `AppDependencies` rows (`Target` = destination host)? | **NOT VERIFIED** | Requires httpx instrumentation to be active in the hosted image; not confirmed. Check `AppDependencies \| where Target has "policy-api"`. |

**VERIFIED 2026-10-08** (workspace table schema, read via
`az monitor log-analytics workspace table show`) — these column names are real in *this*
workspace, independent of whether our data has arrived yet:

- `AppTraces`: `TimeGenerated`, `Message`, `SeverityLevel`, `Properties`, `Measurements`,
  `OperationName`, `OperationId`, `ParentId`, `AppRoleName`, `AppRoleInstance`,
  `AppVersion`, `ItemCount`, `SDKVersion`, `IKey`.
- `AppDependencies`: `TimeGenerated`, `DependencyId`, `Target`, `DependencyType`, `Name`,
  `Data`, `Success`, `ResultCode`, `DurationMs`, `Properties`, `OperationId`, `ParentId`.
- `AppRequests`: `TimeGenerated`, `RequestId`, `Source`, `Name`, `Url`, `Success`,
  `ResultCode`, `DurationMs`, `Properties`, `OperationId`, `OperationLinks`, `ParentId`.
- `AppExceptions`: `TimeGenerated`, `ProblemId`, `ExceptionType`, `Message`, `Details`,
  `Properties`, `SeverityLevel`.

### 1.4 Privacy controls — VERIFIED (source)

`telemetry.py :: disable_content_capture()` force-sets, overwriting any existing value:

| Variable | Value | Status |
| --- | --- | --- |
| `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED` | `false` | set by us — VERIFIED in source. That the Azure SDK honours this exact name is **NOT VERIFIED** here; it is set as a safety floor so an unconfirmed name fails closed. |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `false` | same |

Also verified from source: tool results carry no request body, no response body, no
headers, no credentials; `error_detail` is truncated to 200 chars and prefixed with the
exception type. `docs/compatibility.md` E4 confirms Google ADK exporters are opt-in by
omission — we never opt in.

**Rule for anyone extending this file: no query here may project prompt or response
content. If a future `Properties` key turns out to carry message content, the fix is to
turn the capture off, not to filter it in KQL.**

---

## 2. Layer 2 — platform egress decision records

This layer is produced by the Foundry platform. We do not control any of its field names.

| Item | Status | Detail |
| --- | --- | --- |
| Records land in the **project's** Application Insights | VERIFIED (primary doc, accessed 2026-10-08) | `docs/compatibility.md` C1 / `docs/egress-control.md` §9 |
| Filter is the literal message string `"Network egress decision"` | VERIFIED (primary doc, 2026-10-08) | same |
| Events include destination host, matched rule, decision, enforcement mode (as *concepts*) | VERIFIED (primary doc, 2026-10-08) | same |
| **The sub-field / `Properties` key names** | **NOT VERIFIED** | Undocumented. Must be read off a live row. See procedure below. |
| Portal UI labels: Decision, Reason, Matched rule, Rule source, Enforcement, Destination, Default action | VERIFIED as *UI labels* (primary doc, 2026-10-08) | **These are not confirmed to be Log Analytics column or property names.** Do not type them into KQL. |
| A separate `Microsoft.CognitiveServices` diagnostic-settings category for egress | **NOT FOUND** (searched, 2026-10-08) | `docs/compatibility.md` C1. Project-linked App Insights is the only known path. |
| Whether egress decisions reach a custom `OTEL_EXPORTER_OTLP_ENDPOINT` | **NOT VERIFIED** | `docs/compatibility.md` C4 — the telemetry how-to scopes hosted telemetry to the protocol runtime and agent code and never mentions egress. **Do not claim an OTLP pipeline carries platform decisions.** |
| Audit mode emits the same record with enforcement showing audit | VERIFIED (primary doc, 2026-10-08) | `docs/compatibility.md` C2 |

**Verification procedure for the field names** (requires a deployed agent version with a
policy attached, and §0 fixed):

1. Run one invocation that calls `send_to_external_processor`.
2. `AppTraces | where TimeGenerated > ago(15m) | where Message == "Network egress decision" | take 5`
3. If that is empty, retry at App Insights **resource** scope with the classic schema:
   `traces | where message == "Network egress decision"`. Record which scope worked.
4. Project the raw bag — `| project TimeGenerated, Message, Properties` — and paste the
   real keys into §2.1 below, with the date.
5. **Empty result is inconclusive, never a pass.** Primary guidance, quoted in
   `docs/compatibility.md` C2: *"Do not treat a missing event as proof that a call was
   allowed."*

### 2.1 Observed egress-decision property keys

**NOT VERIFIED — intentionally blank.** Fill only from a real row. Do not pre-populate
from the portal labels above.

| Property key (as seen in `Properties`) | Example value | Date observed |
| --- | --- | --- |
| *(discover during run)* | | |

---

## 3. Layer 3 — receipt logs at the two controlled endpoints

Both services write **one JSON object per line to stdout**; the Container Apps environment
is configured with `logsDestination: log-analytics` pointing at workspace
`def03e45-…` (**VERIFIED 2026-10-08** via `az containerapp env list`).

### 3.1 Receipt payloads — VERIFIED (source)

`services/policy_api/main.py` — emitted on `GET /policy` only:

| Field | Value |
| --- | --- |
| `service` | `policy-api` |
| `event` | `receipt` |
| `received_at` | ISO-8601 UTC |
| `demo_run_id` | from `X-Demo-Run-Id` header, else `demo_run_id` query param, else `""` |
| `method`, `path` | HTTP method and path |
| `outcome` | `served` |

`services/test_receiver/main.py` — emitted on `POST /ingest` only:

| Field | Value |
| --- | --- |
| `service` | `test-receiver` |
| `event` | `receipt` |
| `received_at` | ISO-8601 UTC |
| `demo_run_id` | same two carriers |
| `content_length_bytes` | int — body is measured then discarded; **no payload is retained** |

**VERIFIED (source):** `/healthz` on both services is deliberately *not* logged as a
receipt. This is load-bearing: probe traffic in the arrival log would stop "no receipt"
from meaning "nothing arrived".

### 3.2 Where receipts land — VERIFIED end to end

**VERIFIED 2026-10-08** by querying real receipt rows from the deployed services: table
`ContainerAppConsoleLogs_CL`, columns `TimeGenerated`, `ContainerAppName_s`,
`ContainerName_s`, `RevisionName_s`, `ContainerGroupName_s`, `ContainerImage_s`,
`EnvironmentName_s`, `Log_s`, `Stream_s`, `Category`, `Type`, `time_t`, `_timestamp_d`.

The JSON receipt line arrives as a **string** in `Log_s` and must be parsed with
`parse_json(Log_s)`. Three real receipt rows observed, both services, run id
`verify-3f17f3a0-…`, from revisions `…--0000001` on images
`humblephoenix46689acr.azurecr.io/containment-demo-policy-api:latest` and
`…/containment-demo-test-receiver:latest`. Verbatim:

```json
{"service": "policy-api", "event": "receipt", "received_at": "2026-10-08T17:09:32.441332+00:00",
 "demo_run_id": "verify-3f17f3a0-...", "method": "GET", "path": "/policy", "outcome": "served"}
{"service": "test-receiver", "event": "receipt", "received_at": "2026-10-08T17:09:32.489916+00:00",
 "demo_run_id": "verify-3f17f3a0-...", "content_length_bytes": 210}
```

**Layer 3 is the only one of the three layers that is fully verified today.** Field names,
table, parsing, and `demo_run_id` propagation all confirmed against real rows.

**VERIFIED 2026-10-08:** `Stream_s == "stdout"` on real receipt rows (older placeholder-image
rows were `stderr`). Still **do not filter on `Stream_s`** in evidence queries — it adds no
selectivity over `event == "receipt"` and only creates a way to silently drop rows.

**VERIFIED 2026-10-08 — hygiene defect:** one observed `test-receiver` receipt had
`demo_run_id == ""` (`content_length_bytes: 52`), i.e. a call that carried neither the
`X-Demo-Run-Id` header nor the query param. Unattributed receipts exist in the log.
Consequence: Q2's "zero receipts" claim must be paired with a check that no empty-run-id
receipts landed in the same window, or an un-attributed arrival could hide a real one.
See Q2a.

**VERIFIED 2026-10-08 — ingestion lag:** `received_at` 17:09:32.44 → `TimeGenerated`
17:09:33.90, ≈1.5 s. Use `received_at` from the parsed receipt, not `TimeGenerated`, for
any ordering argument. Feeds §5 point 3.

**NOT VERIFIED:** whether FastAPI/uvicorn access logs are also on stdout and therefore mixed
into `Log_s`. The queries in §4 filter on `event == "receipt"` after parsing, which is
robust to that either way.

---

## 4. KQL queries

Every query carries a header: runnable today or blocked, and which columns are unverified.

All queries are **workspace-scope** (`humble-phoenix-46689-logs`), because the App Insights
component is workspace-based (§0). If a query returns empty, re-try the classic equivalent
at App Insights resource scope before concluding anything.

Replace `<RUN_ID>` with the `demo_run_id` for the run.

---

### Q1 — Receipts at both endpoints for one run

**Runnable today, and executed 2026-10-08 — returned 3 real receipt rows.**
**Unverified columns:** none. Both column names and receipt content verified against real
rows (§3.2).

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(2h)
| where ContainerAppName_s in ("humble-phoenix-466-policy-api", "humble-phoenix-466-test-receiver")
| extend rec = parse_json(Log_s)
| where tostring(rec.event) == "receipt"
| where tostring(rec.demo_run_id) == "<RUN_ID>"
| project TimeGenerated,
          service       = tostring(rec.service),
          demo_run_id   = tostring(rec.demo_run_id),
          received_at   = tostring(rec.received_at),
          path          = tostring(rec.path),
          bytes         = toint(rec.content_length_bytes),
          ContainerAppName_s, RevisionName_s, ContainerImage_s
| order by TimeGenerated asc
```

---

### Q2 — The negative half: did anything arrive at the un-allowlisted receiver?

**Runnable today.** **Unverified columns:** none.

This is the query the whole demo turns on. Expect **zero rows** under Enforced.

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(2h)
| where ContainerAppName_s == "humble-phoenix-466-test-receiver"
| extend rec = parse_json(Log_s)
| where tostring(rec.event) == "receipt"
| where tostring(rec.demo_run_id) == "<RUN_ID>"
| count
```

**Zero is not proof on its own.** Zero receipts + a tool trace showing the attempt + a
platform decision record showing a deny is proof. Zero receipts alone is **inconclusive**:
the agent may never have run, the run id may have been stripped, or the log pipeline may be
lagging. Always pair this with Q2a, Q3 and Q5, and with a positive control (Q1 must show
the policy-api receipt for the same run).

---

### Q2a — Unattributed arrivals in the same window

**Runnable today.** **Unverified columns:** none.

Required companion to Q2. A receipt with an empty `demo_run_id` was observed on
2026-10-08 (§3.2), so "zero rows for our run id" is not the same as "nothing arrived".
Expect zero rows here too.

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated between (datetime(<RUN_START>) .. datetime(<RUN_END>))
| where ContainerAppName_s == "humble-phoenix-466-test-receiver"
| extend rec = parse_json(Log_s)
| where tostring(rec.event) == "receipt"
| where isempty(tostring(rec.demo_run_id))
| project TimeGenerated, received_at = tostring(rec.received_at),
          bytes = toint(rec.content_length_bytes)
```

Any row here makes the run **inconclusive**, not a pass.

---

### Q3 — Application tool traces for one run

**BLOCKED — needs a deployed agent version and §0 fixed.**
**Unverified columns:** the table choice (`AppTraces` vs `AppDependencies` vs `AppEvents`),
and every `Properties` key name. Run Q3a first.

```kusto
// Q3a — DISCOVERY. Run this before trusting Q3b. Finds which table our data lands in.
union AppTraces, AppDependencies, AppEvents, AppRequests
| where TimeGenerated > ago(30m)
| where tostring(Properties) has "<RUN_ID>"
| summarize rows = count(), sample = any(tostring(Properties)) by Type
```

```kusto
// Q3b — assumes AppTraces + verbatim dotted keys. BOTH ASSUMPTIONS ARE UNVERIFIED.
// Do not present output from this query until Q3a has confirmed the table and key names.
AppTraces
| where TimeGenerated > ago(30m)
| where Message == "demo.tool_result"
| extend p = parse_json(Properties)
| where tostring(p["demo.run_id"]) == "<RUN_ID>"
| project TimeGenerated,
          tool        = tostring(p["demo.tool_name"]),
          host        = tostring(p["demo.destination_host"]),
          succeeded   = tostring(p["demo.succeeded"]),
          http_status = tostring(p["demo.http_status"]),
          error_cat   = tostring(p["demo.error_category"]),
          duration_ms = tostring(p["demo.duration_ms"]),
          mode        = tostring(p["demo.policy_mode"]),
          OperationId, ParentId
| order by TimeGenerated asc
```

---

### Q4 — Both tools attempted? (completeness check)

**BLOCKED — same dependency as Q3.** **Unverified columns:** as Q3b.

A run where only one tool fired is not a result, it is a broken run. Both tools are always
registered; both must appear.

```kusto
AppTraces
| where TimeGenerated > ago(30m)
| where Message == "demo.tool_result"
| extend p = parse_json(Properties)
| where tostring(p["demo.run_id"]) == "<RUN_ID>"
| summarize attempts = count() by tool = tostring(p["demo.tool_name"])
| extend verdict = iff(attempts > 0, "attempted", "MISSING — run is invalid")
```

---

### Q5 — Platform egress decision records

**BLOCKED — needs a deployed agent version with a policy attached, and §0 fixed.**
**Unverified columns:** every property key. `Message` and the literal string are verified
from the primary doc; nothing inside the bag is.

```kusto
// Q5a — raw. This is the only safe form until §2.1 is filled in.
AppTraces
| where TimeGenerated > ago(30m)
| where Message == "Network egress decision"
| project TimeGenerated, Message, Properties, OperationId, ParentId, AppRoleName
| order by TimeGenerated asc
```

If Q5a returns nothing, before concluding anything run the resource-scope classic form and
record which worked:

```kusto
// Q5b — App Insights resource scope, classic schema.
traces
| where timestamp > ago(30m)
| where message == "Network egress decision"
| project timestamp, message, customDimensions, operation_Id, operation_ParentId
```

Do **not** write a `Q5c` that projects named sub-fields until §2.1 has real keys in it.

---

### Q6 — Correlation attempt: egress decision ↔ application trace

**BLOCKED, and expected to fail. This query exists to *test* the correlation gap, not to
rely on it.** **Unverified:** that `OperationId` is shared between the two layers at all —
see §5. That is generic App Insights behaviour, not a documented Foundry guarantee.

```kusto
let app_ops =
    AppTraces
    | where TimeGenerated > ago(30m)
    | where Message == "demo.tool_result"
    | where tostring(Properties) has "<RUN_ID>"
    | distinct OperationId;
AppTraces
| where TimeGenerated > ago(30m)
| where Message == "Network egress decision"
| extend joined = OperationId in (app_ops)
| summarize decisions = count() by joined
```

`joined == true` for any row ⇒ **strong** correlation exists; record it immediately in §5
with the date, and upgrade the demo narrative. `joined == false` for all rows ⇒ fall back
to Q7 and state the weakening out loud.

---

### Q7 — Fallback correlation: time window + hostname

**BLOCKED — same dependency as Q5.** **Unverified columns:** the destination-host property
key. The `??` placeholder below is deliberate and must not be guessed.

```kusto
// Fill the host key from §2.1 after observing a real row. Until then, read Properties raw.
AppTraces
| where TimeGenerated between (datetime(<RUN_START>) .. datetime(<RUN_END>))
| where Message == "Network egress decision"
| project TimeGenerated, Properties
// | extend host = tostring(parse_json(Properties)["??"])   // NOT VERIFIED — do not enable
```

---

### Q8 — Negative control: is the pipeline alive?

**Runnable today.** **Unverified columns:** none.

Run this before every demo. It distinguishes "nothing happened" from "logging is broken",
which is the difference between a result and an inconclusive run.

```kusto
ContainerAppConsoleLogs_CL
| where TimeGenerated > ago(1h)
| summarize last_seen = max(TimeGenerated), rows = count()
          by ContainerAppName_s, RevisionName_s, ContainerImage_s
```

---

## 5. The correlation gap — first-class risk

**Status: the demo's weakest joint. Treat as a named risk, not a detail.**

| Correlation | Status |
| --- | --- |
| Application trace → endpoint receipt | **Works, by our own design — VERIFIED 2026-10-08 end to end.** `demo_run_id` is set in `settings.py`, sent on every tool call as the `X-Demo-Run-Id` header **and** as a query param (`tools.py`), and read from either carrier by both services (`_run_marker`). Real receipts carrying run id `verify-3f17f3a0-…` were observed in `ContainerAppConsoleLogs_CL` (§3.2). Two carriers means a receipt stays attributable if one is stripped in transit. |
| Application trace → platform egress decision | **BROKEN / NOT FOUND.** No documented correlation key. `docs/compatibility.md` C3 and Blocker 4; `docs/egress-control.md` §9.1. |
| Platform egress decision → endpoint receipt | **Not applicable by definition** — a denied call produces no receipt. The evidence is the *absence*, which is exactly why it needs the other two legs to be sound. |

### Why this matters

Our run marker travels in an HTTP header and a query string. The platform egress decision
is made by the sandbox proxy and written by the platform. **There is no reason to believe
the platform copies our header into its decision record**, and it is not documented to.
`demo_run_id` therefore correlates Layer 1 ↔ Layer 3 and does *not* reach Layer 2.

If Q6 comes back `joined == false`, the honest statement is:

> We have an application trace showing the attempt, a platform decision record showing a
> deny for that hostname, and no receipt at the destination — three observations in the
> same short window, **not** three rows joined on a shared key.

### The fallback, and exactly how much weaker it is

Fallback key = **run window (timestamp) + destination hostname + agent version**.

It is weaker in four specific ways. State all four; do not soften them:

1. **It is not a join, it is a coincidence argument.** It says the records are consistent,
   not that they describe the same event.
2. **It breaks under concurrency.** Two overlapping runs against the same hostname produce
   decision records that cannot be attributed to either run. **Mitigation: run demos
   strictly serially, one run id at a time, and record start/end timestamps.** This is a
   procedural control substituting for a technical one — say so.
3. **It depends on clock agreement** between the Foundry sandbox and the Container Apps log
   pipeline. **Measured 2026-10-08: Container Apps ingestion lag was ≈1.5 s** (`received_at`
   17:09:32.44 → `TimeGenerated` 17:09:33.90). Foundry-side lag is unmeasured. Use the
   in-payload `received_at`, never `TimeGenerated`, for ordering — and treat anything
   inside a few seconds as not safely orderable.
4. **The hostname leg is itself unverified.** We do not yet know the property key that
   carries the destination host in the decision record (§2.1), so even the weak join has an
   unverified column in it today.

### What would close the gap

In preference order:

1. **Q6 returns `joined == true`.** Cheapest possible fix — it may already work via generic
   App Insights `operation_Id` propagation. **Run Q6 first, immediately after the first
   successful deployed run.** Do not build anything else until Q6 has been answered.
2. **A property key in the decision record that echoes a request header.** Inspect raw
   `Properties` (Q5a) for anything resembling our run id. If the sandbox proxy records
   request headers, we may get the join for free. Unknown; check, do not assume.
3. **Distinct hostnames per run.** Expensive, and changes the egress allowlist — which is
   the experimental variable. Rejected: it contaminates the experiment.
4. **Accept the fallback and label it.** Acceptable, *if* labelled. "Correlated by time
   window and hostname, not by a shared identifier" is a defensible sentence. "Correlated"
   unqualified is not.

---

## 6. Reconciliation with `docs/compatibility.md`

`docs/compatibility.md` is the verified-facts file and wins on conflict. Checked §C1–C4 and
§D on 2026-10-08. **No contradictions.** Two refinements, neither of which overturns it:

1. **C1 says the table is `traces`; this file's queries use `AppTraces`.** Not a conflict —
   a scope difference. C1 quotes the primary doc, which is written for App Insights
   resource scope where `traces` is correct. This lab's component is workspace-based
   (`IngestionMode: LogAnalytics`, VERIFIED 2026-10-08), so at workspace scope the same
   data is `AppTraces`. Both names are live; §4 gives both forms (Q5a / Q5b) and requires
   recording which one actually returned rows. **C1's load-bearing claim — the literal
   message string `"Network egress decision"` and that sub-field names are undocumented —
   stands unchanged and is restated verbatim in §2.**

2. **C1 says "`docs/telemetry-map.md` stays unfilled until we observe real rows."** This
   file honours that. §2.1, the platform field table, is **blank**. What is filled in is
   only what was verified from our own source, from live workspace schema reads, or from
   primary docs — each labelled. Nothing in §2.1 is pre-populated from portal labels.

**C2** (audit evidence appears in the same places; *"do not treat a missing event as proof
that a call was allowed"*) — adopted directly; it is the governing rule for Q2 and Q5.

**C3 / Blocker 4** (no confirmed correlation key) — §5 is built on it and does not soften
it. Q6 is written specifically to test C3 empirically and record the answer.

**C4** (OTel export probably does not carry egress decisions) — §2 restates it. No query in
this file depends on an OTLP path carrying platform decisions.

**§D — managed VNet composability, blocking gap.** No telemetry conflict. One consequence
worth naming: if the managed-VNet path is ever adopted and outbound traffic ends up
governed by managed-VNet outbound rules instead of the egress policy, the decision record
in §2 may not be produced at all, and every Layer-2 query here goes silent. That would be a
**change of evidence source**, not a pass. Re-verify §2 end to end if §D is resolved in the
VNet direction.

---

## 7. Validation checklist before any demo run

1. §0 fixed — project has an App Insights connection, verified by re-running the
   `connections` GET and seeing a non-empty `value`.
2. Q8 green — both container apps logging from our ACR images (**confirmed 2026-10-08**,
   revisions `…--0000001`), recent rows.
3. Q1 green for a throwaway run id — Layer 3 proven live before the agent is involved.
4. Q3a run — the table and real `Properties` keys for our spans recorded in §1.3 with a date.
5. Q5a run — at least one raw decision row observed, §2.1 filled in with real keys and a date.
6. Q6 run — correlation answer recorded in §5 with a date, either way.
7. Q2 and Q2a both zero for the un-allowlisted receiver.
8. Only then does a run produce a result. Before that, every run is **inconclusive**.
