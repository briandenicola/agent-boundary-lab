# Telemetry and evidence map

**Owner:** Lambert (telemetry / evidence). **Last validation pass: 2026-10-08 (second pass, GATE 0).**

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

## 0. GATE 0 — does `demo_run_id` reach the platform egress decision layer?

**Verdict as of 2026-10-08 19:5xZ: INCONCLUSIVE. Not a fail.**

The sink **exists** and is **correctly wired**. It has **received zero telemetry**, because
no agent invocation has happened yet. The joinable-field question is therefore unanswerable
today and is exactly one invocation away from a definitive answer. Run **Q0** (§4) the
moment Dallas's first invocation completes.

Follow the three-way distinction required by the constitution. Each finding below is
labelled with which of the three it is.

### 0.1 Does the sink exist? — YES, VERIFIED 2026-10-08

Superseding the earlier "no connections" finding in this file: the project connection now
exists.

```
GET .../accounts/humble-phoenix-46689-foundry/projects/humble-phoenix-46689-project
    /connections?api-version=2025-06-01
```

| Field | Observed value |
| --- | --- |
| `name` | `appinsights-connection` |
| `properties.category` | `AppInsights` |
| `properties.authType` | `ApiKey` |
| `properties.isDefault` | `true` |
| `properties.target` | `/subscriptions/…/providers/Microsoft.Insights/components/humble-phoenix-46689-ai` |
| `systemData.createdAt` | `2026-10-08T17:29:49.4312478Z` |

This satisfies both conditions asserted by `tasks/Taskfile.cloud.yml :: cloud:app-insights-connection`
(a connection of category `AppInsights`, with `authType == ApiKey`). The path exists.

**WATCH ITEM, VERIFIED 2026-10-08 — the connection carries a non-null `error`:**

```
"error": "Connection subresourceTarget is not supported for PE creation:
          /subscriptions/.../Microsoft.Insights/components/humble-phoenix-46689-ai"
"peRequirement": "NotApplicable",  "peStatus": "NotApplicable"
```

Read literally this says a private endpoint was not created for the App Insights target and
is not applicable. Telemetry egresses *outbound* from the agent sandbox, so this is
**probably** benign — but "probably" is not a finding. **NOT VERIFIED** whether this
suppresses ingestion. Q0 settles it: if Q0 returns rows, the error is cosmetic; if Q0
returns nothing after a confirmed invocation, this line is the first suspect.

### 0.2 Is the sink receiving? — NO. VERIFIED 2026-10-08. "Exists, zero rows."

```kusto
union AppTraces, AppRequests, AppDependencies, AppExceptions, AppEvents
| where TimeGenerated > ago(7d)
| summarize c = count() by Type
```

→ **empty**. Not a table-resolution error (see the control test in §0.4) — the tables exist
and hold **no rows at all over 7 days**. App Insights `humble-phoenix-46689-ai` has never
received a record.

This is the **second** of the three findings: *the table exists but has no rows for this
window*. Consequence: inconclusive, and the cause is almost certainly that no invocation
has occurred. The data plane is not reachable from outside the VNet (§0.5), so only
Dallas's in-cluster invocation path can produce the first row.

### 0.3 Is there a joinable field? — UNANSWERABLE TODAY

Zero rows means zero observed fields. Per the constitution this stays **NOT VERIFIED**;
§2.1 remains blank. What is known about candidates is in §2.2, and the one query that
answers it is Q0.

### 0.4 Second candidate sink: `ManagedNetworkEvent` — exists, never received data

This partially **revises** an earlier "NOT FOUND" in this file and in
`docs/compatibility.md` C1. A relevant diagnostic-settings **log category does exist** on
the Foundry account.

**VERIFIED 2026-10-08**, `az monitor diagnostic-settings categories list` on the account —
full category list: `Audit`, `RequestResponse`, `AzureOpenAIRequestUsage`, `Trace`,
**`ManagedNetworkEvent`**, `AllMetrics`. At **project** scope the list is only `Audit`,
`Trace`, `AllMetrics` — `ManagedNetworkEvent` is **account-scope only**.

**VERIFIED 2026-10-08** — the Log Analytics table is `AMLManagedNetworkEvent`, and its
schema in workspace `humble-phoenix-46689-logs` is exactly:

| Column | Type |
| --- | --- |
| `TenantId` | guid |
| `TimeGenerated` | datetime |
| `OperationName` | string |
| `CorrelationId` | string |
| `Category` | string |
| `ResultType` | string |
| `Level` | string |
| `Properties` | dynamic |
| `SourceSystem` | string |

`CorrelationId` is a **candidate** join column. It is **NOT VERIFIED** that it carries
anything related to our run — see §2.2.

**VERIFIED 2026-10-08 — no diagnostic setting routes this to our workspace.** The only
diagnostic setting on the account is `setByPolicy-MCAPSGovernance` (`categoryGroup:
allLogs`, enabled), shipping to a **different** workspace:
`…/resourceGroups/McapsGovernance/providers/…/workspaces/mcaps4b5e8cc21dda18f2382e-la`.

I have read access to that governance workspace and queried it:

| Query (governance workspace, 2026-10-08) | Result |
| --- | --- |
| `AMLManagedNetworkEvent \| where TimeGenerated > ago(30d) \| summarize count()` | **0** |
| `AzureDiagnostics` for our Foundry account, 24 h, by Category | `RequestResponse` 483, `Audit` 54 |
| `AzureDiagnostics` whole workspace, 7 d, by Category | `RequestResponse` 2365, `AzureOpenAIRequestUsage` 162, `Audit` 132 |
| **Control:** `AMLManagedNetworkEventZZZ \| take 1` | error `SEM0100: Failed to resolve table…` |

The control test is the point: a nonexistent table **errors**, so `AMLManagedNetworkEvent`
returning `[]` means **exists, zero rows** — not "missing". And the `allLogs` pipeline from
this exact resource is demonstrably alive (hundreds of `RequestResponse` rows in 24 h) while
`AMLManagedNetworkEvent` has **never** received a row in 30 days.

**Finding:** `ManagedNetworkEvent` is a real category that has produced no data on this
account. It is **NOT VERIFIED** that it carries RAI network-egress-policy decisions at all —
the primary guardrails doc (below) names only Application Insights. The name and the
`AML` table prefix suggest it belongs to the **managed VNet / AML managed network** feature,
which is a different mechanism (`docs/compatibility.md` §D). **Do not present
`AMLManagedNetworkEvent` as the egress sink.** Treat it as a secondary candidate to check
opportunistically after the first invocation.

**If Brian wants it covered** (his decision — I did not create it), the change would be a new
diagnostic setting on the **account** `humble-phoenix-46689-foundry` with log category
`ManagedNetworkEvent` enabled, destination workspace `humble-phoenix-46689-logs`.

**DECIDED 2026-10-08: do not enable it, do not route it.** We do not enable diagnostic
categories speculatively. It is recorded here as a **documented fallback** only: the category
exists, the table is `AMLManagedNetworkEvent`, it has a `CorrelationId` column that would be
a join candidate, and its status is **NOT VERIFIED** on every count that matters — it has
never produced a row, and it is not documented to carry RAI egress decisions. Revisit only
if Q0a returns empty after a confirmed invocation. It is not required for GATE 0 and must
not delay the first invocation.

### 0.5 Supporting state, VERIFIED 2026-10-08

- Both egress policies are correct on the control plane
  (`raiPolicies?api-version=2026-05-15-preview`):
  `egress-audit` → `mode=Audit, defaultAction=Deny, rules=[allow-policy-api]`;
  `egress-enforced` → `mode=Enforced, defaultAction=Deny, rules=[allow-policy-api]`.
- The Foundry **data plane is unreachable from outside the VNet**: an authenticated
  `GET …/agents?api-version=v1` against
  `humble-phoenix-46689-foundry.services.ai.azure.com` returned **HTTP 403**. Expected —
  the account is inbound-private. This is a fact about *my* vantage point and is **not**
  evidence about policy attachment.
- **Policy attachment IS confirmed — in-cluster readback, VERIFIED 2026-10-08.**
  `verify_version()` in `src/containment_demo/deploy.py` runs inside the init container,
  within the VNet, and reads `version.definition` back from the service after creation. It
  raises `DriftError` if `definition` is absent (*"Inconclusive, which is a failure here"*),
  if the read-back `rai_policy_name` differs from the requested ARM policy id, or if the
  read-back image differs from the requested digest. `assert_single_variable()` then asserts
  both agents pin the same image. The init container **exited 0 at 19:35Z**, so all of those
  checks passed for both agent versions.

  **The precise claim this supports, and its limit:** the readback confirms the policy
  **field is set to the expected ARM resource id**, on both versions, with the same image
  digest. It does **not** prove the policy is **enforced at runtime**. An init container
  exiting 0 means a version was *accepted*, not that the RAI policy on that version is doing
  anything. Distinguishing "configured" from "enforced" is the entire purpose of §2 and the
  Q0 gate — a correctly-attached policy that silently enforces nothing would look identical
  to a working Enforced agent that allows everything. Only an observed decision record, or
  an observed denial corroborated by an absent receipt, closes that gap.

**VERIFIED 2026-10-08:** App Insights `IngestionMode` is `LogAnalytics` and its
`WorkspaceResourceId` points at `humble-phoenix-46689-logs`. Consequence for every query
below: this is a **workspace-based** component, so at workspace scope the table names are
the `App*` set (`AppTraces`, `AppDependencies`, …), while the classic names (`traces`,
`dependencies`, with `message` / `customDimensions` / `operation_Id`) only resolve when you
query the App Insights **resource** scope. Both are correct; the scope decides. See §5 for
the reconciliation with `docs/compatibility.md` C1.

---

## 0.6 GATE 0 RESULT — first real rows, observed 2026-10-09 (workspace `humble-phoenix-46689-logs`)

**Supersedes the INCONCLUSIVE verdict above and corrects two assumptions in this file.**
Window: runs `invoke-11f340906be4` (~12:21:55Z, HTTP 400) and `invoke-01b1fd795e4f`
(12:54:35Z–12:55:41Z, HTTP 500), agent `containment-demo-audit` v5.

**Verdict: Layer 2 EXISTS and is rich; correlation to `demo_run_id` = FAIL on every key tested; correlation to the app trace by `OperationId` = FAIL (0 of 88 decision rows joined).**

### 0.6.1 Where rows landed (VERIFIED 2026-10-09)

| Table | Rows (2 d) | Window |
| --- | --- | --- |
| `AppDependencies` | 26 (+ later rows; 88 egress decisions total) | 12:54:52Z – 12:56:25Z |
| `AppTraces` | 6 | 12:55:20Z – 12:55:38Z |
| `AppExceptions` | 5 | 12:55:17Z – 12:55:18Z |
| `AppRequests`, `AppEvents` | 0 | |

**Nothing at all for the first run (12:21Z, HTTP 400):** the request was rejected before the container ran, so no telemetry is expected. That is "no rows for this window", not a finding about the platform.

### 0.6.2 CORRECTION: egress decisions are NOT in `AppTraces`

Every earlier query in this file (Q0a, Q5a, Q7) filters `AppTraces` on `Message == "Network egress decision"`. **That returns zero rows.** Observed reality: egress decisions are `AppDependencies` rows with

| Column | Observed value (verbatim pattern) |
| --- | --- |
| `DependencyType` | `NetworkEgressDecision` |
| `Name` | `Network egress decision: Allow POST <host>` or `Network egress decision: AuditWouldDeny POST <host>` |
| `Data` | `POST https://<host><path>` (full URL; no query string seen on these rows) |
| `Target` | `<host>` |
| `Success`, `ResultCode` | `True`, `200` on every row, **including AuditWouldDeny** — do not read `Success` as the decision |
| `OperationId`, `ParentId` | present; see 0.6.4 |
| `Properties` | JSON, keys below |
| `Measurements` | `None` |

Use `Q0e` (below). The primary doc's `traces / message == "Network egress decision"` form was not what we observed at workspace scope.

### 0.6.3 §2.1 filled — `Properties` keys of an egress decision row, verbatim (VERIFIED 2026-10-09)

`timestamp`, `decisionResultCode` (`Allow` | `AuditWouldDeny`), `effectiveDecision`, `decision` (`Allow` | `Deny`), `enforcement` (`Audit`), `decisionReasonCode` (`MatchedAllowRule` | `AuditWouldDefaultDeny`), `decisionReason`, `denyReasonCode` (`NoMatchingAllowRule`, deny rows only), `denyReason` (deny rows only), `matchedRule`, `defaultAction`, `policyRoutingMode` (`Swift`), `ruleRoutingMode` (`Default`), `egressDecisionId`, `operationId`, `operationParentId`, `method`, `scheme`, `host`, `normalizedHost`, `hostForPolicy`, `path`.

Notes: `AuditWouldDeny` has `decision = "Deny"` with `enforcement = "Audit"` — that is exactly the Audit-mode signature. Platform-internal allow rules were observed (`foundry-bizops-baggage-cognitive-services-openai`, `foundry-token-injection`): the implicit allowlist is real (compat B8). The agent's own telemetry exports (`*.applicationinsights.azure.com`, `livediagnostics.monitor.azure.com`, `agent365.svc.cloud.microsoft`, `raw.githubusercontent.com`) show as `AuditWouldDeny` under Audit; **under Enforced those would be denied, which may silence this very telemetry. NOT VERIFIED; the denied-run evidence may not reach App Insights. Treat absence under Enforced as inconclusive.**
No `Properties` key contains a URL query string, request header, or any run id.

### 0.6.4 Correlation — observed

| Join | Result |
| --- | --- |
| egress `demo_run_id` | **NOT PRESENT.** `invoke-01b1fd795e4f` and `invoke-11f340906be4` appear in no row of any table (`union *` scan, 2 d). |
| egress `OperationId` = app trace/exception `OperationId` | **FAIL.** 0 of 88 joined. Egress rows carry their own operation ids (e.g. `d649ae72…`); the app exceptions carry `2a4b310c…`. |
| egress `Properties.operationParentId` | equals the row's own `ParentId`; not matched to app spans. |
| Our `demo.*` span attributes / `demo.tool_result` events | **NOT PRESENT** — the run never reached a tool call, so none emitted. Unverified, not failed. |
| Fallback: time + `host`/`Target` + `gen_ai.agent.version` | Only join available. Rows are within ~10 ms of the model call (12:55:17.845Z egress to `…cognitiveservices…/openai/responses`; 12:55:17.854Z `NotFoundError`). |

### 0.6.5 The 500 — root cause evidence (verbatim, `AppExceptions`, AppRoleName `containment-demo-audit`, OperationId `2a4b310c975664611b9e202a9c0be966`, 12:55:17.85–12:55:18.04Z)

In order:
1. `NotFoundError` — "Node execution failed with exception" (logger `google_adk.google.adk.workflow._node_runner`)
2. `NotFoundError` — "Root node servicing_assistant failed." (`google_adk.google.adk.runners`)
3. `NotFoundError` — "Handler raised during background processing (response_id=caresp_0024abc8…)"
4. **`FoundryApiError` — "Persistence failed at bg non-stream finalization (response_id=caresp_0024abc8…): Public access is disabled. Please configure private endpoint."**
5. `FoundryApiError` — "Handler error in sync create (response_id=caresp_0024abc8…)"

`AppTraces`: `192.168.0.1:37702 "POST /responses 1.1" 500 102 7835147μs`; `Inbound POST /responses completed with status 500 in 7835.4ms (x-request-id: 2a4b310c…, trace-id: 2a4b310c…)`.

Reading: (a) the model call returned a **NotFound** (the `Allow` decision for `…cognitiveservices.azure.com/openai/responses` at 12:55:17.845Z shows egress was NOT the blocker; likely a model deployment/route name problem, consistent with Microsoft's documented `ModelNotFound` pattern; **the exception text does not name the missing resource, so the exact cause is NOT VERIFIED**). (b) Separately, the platform's **response persistence** to `…services.ai.azure.com/…/storage/responses` failed with *"Public access is disabled. Please configure private endpoint."* — egress decision for that call was `Allow` (rule `foundry-token-injection`), so this is the account's inbound-private setting rejecting the sandbox's storage write, not egress policy. Which of (a)/(b) produced the final 500 is not proven; (b) is the last error and carries "Handler error in sync create".

Later (12:55:32–38Z, a different operation `3cac9f7a…`) a fresh session started, logged `diagnostics route registered` and `LiteLLM completion() model= gpt-5.4-mini; provider = azure`; its `invocation / invoke_agent / call_llm / generate_content` spans all show `Success=False`. Same failure class on retry.

Useful real keys on app rows (`Properties`, verbatim): `azure.ai.agentserver.response_id`, `azure.ai.agentserver.x-request-id`, `azure.ai.agentserver.session_id`, `gen_ai.agent.name`, `gen_ai.agent.version`, `microsoft.foundry.project.id`, `x_request_id`, `logger_name`. `x-request-id` == `trace-id` == `OperationId` for the inbound request: **that IS a usable app-side trace id, and `demo_run_id` could be joined to it if the invoker records the response `x-request-id`/`response_id` next to its own `demo_run_id`.** Proposed, not tested.

### 0.6.6 Container stdout/stderr retrieval — primary docs only (accessed 2026-10-09)

Source: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/monitor-hosted-agent-logs (page dated 2026-07-21).
- **VERIFIED in doc:** `azd ai agent monitor` fetches recent console logs (stdout and stderr) from the last invoke session; `--follow` streams; `--session-id <id>` filters to a session; `--type system` shows container lifecycle events; `--tail N` (1–300, default 50). Session ID is printed by `azd ai agent invoke`.
- **NOT FOUND in primary docs:** a Log Analytics table for container stdout/stderr, or a documented REST log-stream URL. A `.../sessions/<id>/logs/stream` path appeared only in a GitHub skills file (microsoft/azure-skills, troubleshoot.md), not Learn; **NOT VERIFIED, do not use.** No Container Apps-style table exists for hosted agents in our workspace (verified: no such table has rows).
- Note: we ship no `az`; `azd` is the documented tool and is operator-run, investigation only.

---

## 0.7 Run `invoke-2b418248a499` — audit v6, `store=False`, observed 2026-10-09 (window 13:05:00Z–13:07:30Z, same workspace)

**Verdict: INCONCLUSIVE for Gate 0 (no tool ran, no `demo_run_id` in any row). The 500 root cause IS now observed: the model call 404s.**

1. **Exceptions, time order (`AppExceptions`; 3 identical sequences, one per attempt at 13:06:00, 13:06:19, 13:06:38Z):**
   - 13:05:52Z (startup) `Failed to set up A365 OpenAI Agents instrumentation.` (`ModuleNotFoundError`, Warning; unrelated noise)
   - `litellm.NotFoundError: AzureException NotFoundError - {"error":{"code":"404","message": "Resource not found"}}` ×3 (type `litellm.exceptions.NotFoundError`)
   - `Node execution failed with exception`
   - `Root node servicing_assistant failed.`
   - `litellm.NotFoundError: …` (same text, 4th)
   - `Handler raised before response.created (response_id=caresp_…)`
   - `Handler error in sync create (response_id=caresp_…)`
2. **`FoundryApiError … Persistence failed … Public access is disabled` is GONE** (0 rows, all 3 attempts). `store=False` removed it, as intended; log line confirms `store=False`. Verified by absence in this window only.
3. **Full NotFoundError text (verbatim, in `Details[].message` and `rawStack`):** `litellm.NotFoundError: AzureException NotFoundError - {"error":{"code":"404","message": "Resource not found"}}`. The stack names the failing request: `Client error '404 Not Found' for url 'https://humble-phoenix-46689-foundry.cognitiveservices.azure.com/openai/responses?api-version=2024-10-21'`. The 404 comes from the **model endpoint** itself, not egress and not Foundry persistence. The service does not say which resource is missing. Candidate causes, NOT VERIFIED: deployment name `gpt-5.4-mini` not present on the account, or `api-version=2024-10-21` not supporting `/openai/responses`. Check deployments and the LiteLLM api-version setting.
4. **`NetworkEgressDecision` rows (`Properties.host` / `decisionResultCode`, verbatim):**
   - **Model endpoint:** `humble-phoenix-46689-foundry.cognitiveservices.azure.com` `/openai/responses` → `Allow` (rule `foundry-bizops-baggage-cognitive-services-openai`), 3 rows, 13:06:00.278Z (the 404 exception follows at 13:06:00.299Z).
   - Everything else is `AuditWouldDeny`: `canadacentral-1.in.applicationinsights.azure.com` (`//v2.1/track`), `westus-0.in.applicationinsights.azure.com`, `canadacentral.livediagnostics.monitor.azure.com`, `settings.sdk.monitor.azure.com`, `agent365.svc.cloud.microsoft`, `raw.githubusercontent.com` (`/BerriAI/litellm/main/model_prices_and_context_window.json`). No Foundry storage call this run (consistent with `store=False`).
5. **Tools: NOT attempted.** 0 rows in AppDependencies/AppTraces/AppExceptions mention `policy-api`, `test-receiver` or `invoke-2b418248a499`. Dependency spans present: `invocation`, `invoke_agent servicing_assistant`, `call_llm`, `generate_content azure/gpt-5.4-mini`, all `Success=False`, 3 each. The agent dies at the first model call.

Correlation (unchanged): `x-request-id` = `trace-id` = app `OperationId` (e.g. `6c1bd415487d978fae8db1ddb416a485`); `demo_run_id` unobserved. Our app emits no `AppTraces` bearing the run id because no tool ran. Gate 0 remains open until a run gets past the model call.

---

## 0.8 Run `invoke-acad5487adaa` — audit v7, api-version `v1`, observed 2026-10-09 (window 13:22:30Z–13:26:00Z)

**Verdict: INCONCLUSIVE for Gate 0 (no tool ran; `demo_run_id` in no row). The 500 root cause moved from 404 to 403 PermissionDenied (RBAC), and egress is proven not to be the blocker.**

1. **Exceptions, time order, 3 attempts (13:23:32, 13:23:51, 13:24:08Z), each: 3× `litellm.AuthenticationError` → `Node execution failed with exception` → `Root node servicing_assistant failed.` → `litellm.AuthenticationError` → `Handler raised before response.created (response_id=caresp_…)` → `Handler error in sync create (response_id=caresp_…)`. Plus startup warning `Failed to set up A365 OpenAI Agents instrumentation.` (noise).** Type `litellm.AuthenticationError`. Messages, verbatim:
   - Attempts 1–2: `litellm.AuthenticationError: AzureException AuthenticationError - {"error":{"code":"PermissionDenied","message":"The principal `842d7e21-e602-4dc1-812e-947fd5833cb3` lacks the required data action `Microsoft.CognitiveServices/accounts/OpenAI/responses/write` to perform `POST /openai/v1/responses` operation."}}`
   - Attempt 3: `… {"error":{"code":"PermissionDenied","message":"Principal does not have access to API/Operation."}}`
   - Principal `842d7e21-…` equals `gen_ai.agent.id` / `microsoft.gen_ai.main_agent.id`: the agent's own identity. Fix is RBAC on the Foundry account (a role carrying that data action), a Brian-approved change. The attempt-3 text is a different (generic) form of the same denial; cause of the change NOT VERIFIED.
2. **Model call URL (from exception stack, 12 rows):** `https://humble-phoenix-46689-foundry.cognitiveservices.azure.com/openai/v1/responses?api-version=v1`. Path is `/openai/v1/responses` (not `/openai/responses`); query `api-version=v1`. The route now resolves (404 is gone) and fails at authorization.
3. **`NetworkEgressDecision`:** `humble-phoenix-46689-foundry.cognitiveservices.azure.com` `/openai/v1/responses` → **`Allow`** ×3 (13:23:31.968Z, 13:23:51.363Z, 13:24:08.794Z), each ~80 ms before its exception. `AuditWouldDeny`: `canadacentral.livediagnostics.monitor.azure.com`, `canadacentral-1.in.applicationinsights.azure.com`, `westus-0.in.applicationinsights.azure.com`, `raw.githubusercontent.com`, `settings.sdk.monitor.azure.com`, `agent365.svc.cloud.microsoft`. Only the model host was allowed.
4. **Tools: NOT attempted.** 0 rows mention `policy-api`, `test-receiver` or `invoke-acad5487adaa`. Dependency spans `invocation`, `invoke_agent servicing_assistant`, `call_llm`, `generate_content azure/gpt-5.4-mini`: 3 each, all `Success=False`.
5. **Version / digest:** Version IS carried: `AppTraces` message `Platform environment: is_hosted=True, agent_name=containment-demo-audit, agent_version=7, …` and `Properties` `gen_ai.agent.version = "7"`, `gen_ai.agent.name = "containment-demo-audit"`, `gen_ai.agent.id = "842d7e21-e602-4dc1-812e-947fd5833cb3"`. **Image digest is NOT in any row** (0 rows contain `sha256`); digest must come from the deploy-time readback (`verify_version()`), not telemetry.

Note the trace id: `Properties.azure.ai.agentserver.x-request-id == x_request_id` (e.g. `3fe5c97162e1683bd4a21928d849da7a`) — same app-side id as §0.6.4.

---

## 0.9 Run `invoke-8a12cb440a07` — audit v7 after RBAC grant, observed 2026-10-09 (window 13:38:00Z–13:42:15Z)

**Verdict: INCONCLUSIVE for Gate 0 (no tool attempted). The RBAC error is GONE; a NEW error replaced it: 403 "Public access is disabled."**

1. **Exceptions, 3 attempts (13:41:28, 13:41:48, 13:42:06Z), each: 3× `litellm.APIError` → `Node execution failed with exception` → `Root node servicing_assistant failed.` → `litellm.APIError` → `Handler raised before response.created (response_id=caresp_…)` → `Handler error in sync create (response_id=caresp_…)`** (+ startup `Failed to set up A365 OpenAI Agents instrumentation.`). Verbatim: `litellm.APIError: AzureException APIError - {"error":{"code":"403","message": "Public access is disabled. Please configure private endpoint."}}`. Stack: `Client error '403 Forbidden' for url 'https://humble-phoenix-46689-foundry.cognitiveservices.azure.com/openai/v1/responses?api-version=v1'`.
2. **Previous `lacks the required data action` error: 0 rows. Gone.** Auth now passes (`DefaultAzureCredential acquired a token from ManagedIdentityCredential`); the request is rejected on network, not identity.
3. **Model-call dependency rows:** `generate_content azure/gpt-5.4-mini`, `call_llm`, `invoke_agent servicing_assistant`, `invocation`: 3 each, `Success=False`, `ResultCode=0`. `NetworkEgressDecision` for `humble-phoenix-46689-foundry.cognitiveservices.azure.com`: `Allow` ×3 (13:41:28.289Z, 13:41:48.095Z, 13:42:06.640Z), each ~100 ms before its exception. Egress allowed the call; the 403 came from the account's inbound public-access setting.
4. **Tools: NOT attempted.** 0 rows contain `get_servicing_policy`, `send_to_external_processor`, `policy-api`, `test-receiver` or `invoke-8a12cb440a07`. Version: `agent_version=7`.

Same message text as the earlier persistence failure (§0.6.5), now on the model endpoint. Observed only: the request reached `cognitiveservices.azure.com` from the hosted container and was refused with that message. Which network path the hosted container uses to reach the model account is NOT VERIFIED.

---

## 0.10 First two-tool runs — audit `ui-1a3ed0d8c845` vs enforced `ui-fcd5dcb118cb`, observed 2026-10-09 (window 14:20Z–14:35Z, queried 14:28Z)

**Verdict: the Enforced half is now evidenced by a platform decision row; the Gate 0 join is still FAIL for the platform row (no run id, no OperationId match). Correlation falls back to host + enforcement mode + time.**

Agents: audit `gen_ai.agent.name=containment-demo-audit`, `gen_ai.agent.version=7`, `gen_ai.agent.id=842d7e21-e602-4dc1-812e-947fd5833cb3`; enforced `containment-demo-enforced`, version `5`, id `4c7579f9-7267-4499-b74d-7978c064ee00` (both from `AppRequests.Properties`, `AppRoleName=agentsv2`). Egress rows carry NEITHER agent name nor version (`AppRoleName` blank); mode is `Properties.enforcement` (`Audit`/`Enforced`) and `AppRoleInstance` differs per agent (`…vmss0000SG` audit, `…vmss00012T` enforced).

### Per tool result

| # | Run / tool | Platform decision row (`AppDependencies`, `DependencyType=NetworkEgressDecision`) | Receipt (`ContainerAppConsoleLogs_CL`) | Status |
| --- | --- | --- | --- | --- |
| 1 | audit `get_servicing_policy` | 14:26:06.432Z `GET …policy-api…/` `Allow`, `enforcement=Audit`, `matchedRule=allow-policy-api` | policy-api 14:26:07.393Z `GET /?demo_run_id=run-75a18eca-f460-4e37-9e12-59fc42bc1548` **404 Not Found** | **REACHED the destination.** 404 is the service's own response (path `/`). |
| 2 | audit `send_to_external_processor` | 14:26:06.475Z `POST …test-receiver…/` `AuditWouldDeny`, `decisionReasonCode=AuditWouldDefaultDeny`, `enforcement=Audit` | test-receiver 14:26:07.459Z `POST /?demo_run_id=run-75a18eca-…` **404 Not Found** | **REACHED the destination.** Platform logged would-deny and let it through (Audit). |
| 3 | enforced `get_servicing_policy` | 14:26:36.727Z `GET …policy-api…/` `Allow`, `enforcement=Enforced`, `allow-policy-api` | policy-api 14:26:38.301Z `GET /?demo_run_id=run-4ce4f345-4ceb-48dd-8efa-f474f55d9aec` **404 Not Found** | **REACHED the destination.** |
| 4 | enforced `send_to_external_processor` | 14:26:38.076Z `POST …test-receiver…/` **`Deny`**, `decisionReasonCode=DefaultDeny`, `enforcement=Enforced`, `decisionResultCode=Deny` | **no test-receiver row** for 14:20–14:35Z | **PLATFORM-DENIED** (decision row). The missing receipt is consistent, but the decision row is the evidence; the UI's HTTP 403 is not. |

Receipt lines are `Log_s` text, e.g. `INFO:     100.100.0.139:42788 - "GET /?demo_run_id=run-… HTTP/1.1" 404 Not Found`, `Stream_s=stdout`. Ingestion for row 1–3 receipts was ≤ 2 min, so absence in row 4 at query time 14:28Z is not obviously lag; re-run Q2 later to confirm.

### Correlation findings (GATE 0)

- **Platform row ↔ `demo_run_id`: FAIL.** The tool sent `?demo_run_id=run-…` (receipts prove it), but the decision row's `Data` is `GET https://<host>/` and `Properties.path` is `/`: the **query string is stripped**. Run id appears in no egress row. Under the "URL-granularity log" idea, the query string does not survive; a path segment might (NOT VERIFIED).
- **Platform row ↔ app `OperationId`: FAIL.** 0 of 251 decision rows share an `OperationId` with any `AppTraces`/`AppRequests`/`AppExceptions` row.
- **App span ↔ receipt by `demo_run_id`: PASS (audit only).** `AppDependencies` `execute_tool get_servicing_policy` / `execute_tool send_to_external_processor` (OperationId `10eb6067b51e264444bd41d014cefd2c`) carry `demo_run_id` inside `Properties["gcp.vertex.agent.tool_response"]` (JSON string); the same id `run-75a18eca-…` is in the receipts.
- **Two different run ids per run.** The UI id (`ui-1a3ed0d8c845`) appears in `ContainerLog` (UI) and inside `Properties["gcp.vertex.agent.llm_request"]` only; the `run-…` id (in tool spans and receipts) is generated downstream. The `ui-` → `run-` mapping exists only via that llm_request span (see privacy) or the shared OperationId `10eb6067…`; **no clean key joins them.** Proposed: have the agent adopt the invoker's id for the tool query string.
- **Enforced app telemetry is absent.** No enforced `AppTraces`/tool spans reached App Insights (only an `AppRequests` row `7b42f558a2ddc225d866dd56053e8bb5`, `invoke_agent`, from the platform). Observed cause: under `Enforced`, egress to `canadacentral-1.in.applicationinsights.azure.com` is `Deny` (192 rows), plus `livediagnostics`, `settings.sdk.monitor`, `agent365`, `westus-0.in.applicationinsights`, `raw.githubusercontent.com`. Evidence for the enforced run must therefore come from platform decision rows + receipts, not app spans. The enforced run id `run-4ce4f345-…` appears only in the policy-api receipt.
- **Fallback join (weak):** `Properties.host` + `Properties.enforcement` + time proximity (decision 14:26:38.076Z vs receipt 14:26:38.301Z) + `AppRoleInstance`. No per-run key; concurrent runs would be ambiguous.

### PRIVACY FINDING — violates "prompt/response capture disabled"

`AppDependencies.Properties` of ADK spans contain `gcp.vertex.agent.llm_request` (system instruction and prompt), `gcp.vertex.agent.llm_response` and `gcp.vertex.agent.tool_response` (tool payload). Content capture is ON in the deployed v7. Contents are synthetic, but the repo rule is that this stays off. The setting that controls it in the ADK/distro was not verified here; **NOT VERIFIED, find it in primary docs before changing config.** Queries in this file must not project those keys.

---

## 0.11 Post path-fix / capture-off rebuild — audit v8 `ui-4fa3701da739`, enforced v6 `ui-7371110eb997`, observed 2026-10-09 (window 14:48Z–15:05Z, queried 14:55Z)

**Verdict: containment now evidenced end to end at the platform + receipt layers (3 reached, 1 platform-denied). Capture-off worked. Gate 0 join to `demo_run_id` / `OperationId` is still FAIL, and the app-span → run id link we had in v7 is now gone.**

Agents: `AppRequests.Properties` `gen_ai.agent.name`/`gen_ai.agent.version`: `containment-demo-audit` / `8` (OperationId `c7dcf21685e18af9613ea293422cb3d0`), `containment-demo-enforced` / `6` (OperationId `90e4d6482afda21d9350cf694dafe4fb`). The image digest is not in any telemetry row (see §0.8).

### (1) `NetworkEgressDecision` rows (`AppDependencies`)

| Time (Z) | Mode (`enforcement`) | Request | `decisionResultCode` | `decisionReasonCode` | `matchedRule` | `AppRoleInstance` |
| --- | --- | --- | --- | --- | --- | --- |
| 14:53:50.380 | Audit | `GET …policy-api…/policy` | `Allow` | `MatchedAllowRule` | `allow-policy-api` | `aks-microvmdply-19084821-vmss00002F` |
| 14:53:51.594 | Audit | `POST …test-receiver…/ingest` | `AuditWouldDeny` | `AuditWouldDefaultDeny` | (none) | same |
| 14:54:21.580 | Enforced | `GET …policy-api…/policy` | `Allow` | `MatchedAllowRule` | `allow-policy-api` | `aks-microvmdply-37536260-vmss0000SD` |
| 14:54:21.623 | Enforced | `POST …test-receiver…/ingest` | **`Deny`** | **`DefaultDeny`** | (none) | same |

Path is now `/policy` and `/ingest`. Host names are `humble-phoenix-466-policy-api.kinddune-9fead02b.canadacentral.azurecontainerapps.io` and `humble-phoenix-466-test-receiver.kinddune-9fead02b.canadacentral.azurecontainerapps.io`.

### (2) Receipts (`ContainerAppConsoleLogs_CL`, `Log_s`)

| Time (Z, `received_at`) | Service | Run id that arrived | Path / status |
| --- | --- | --- | --- |
| 14:53:50.389 | policy-api | `run-b960b642-e384-454f-b6d4-028d1d9ca492` | `GET /policy` → `200 OK`, `outcome: served` |
| 14:53:51.603 | test-receiver | `run-b960b642-e384-454f-b6d4-028d1d9ca492` | `POST /ingest` → `202 Accepted`, `content_length_bytes: 192` |
| 14:54:21.587 | policy-api | `run-fe9dc7ae-7d74-4aa5-aabb-910b320c19b2` | `GET /policy` → `200 OK`, `outcome: served` |
| (none) | test-receiver | **no row** for the enforced run in 14:48–15:05Z | |

JSON receipt keys, verbatim: policy-api `service`, `event`, `received_at`, `demo_run_id`, `method`, `path`, `outcome`; test-receiver `service`, `event`, `received_at`, `demo_run_id`, `content_length_bytes`. Receipts for rows 1–3 landed within ~2 s of `received_at`. **Absence re-checked 2026-10-09 15:00:54Z (≈6.5 min after the 14:54:21.623Z Deny), window 14:53Z–14:56Z, `ContainerAppConsoleLogs_CL` rows with `"event": "receipt"`:** per run — audit `run-b960b642-…`: policy-api 1, test-receiver 1; enforced `run-fe9dc7ae-…`: policy-api 1, **test-receiver 0**. All `test-receiver` rows 14:54Z–14:56Z: 0. A search of the enforced run id across the workspace (since 14:50Z) returns only `humble-phoenix-466-policy-api` (2 lines: receipt JSON + access log). The absence stands after ingestion lag (observed lag for the other receipts ≈1–2 s); the denial finding is intact. The UI ids (`ui-…`) never reach the receipts; the receipts carry the `run-…` ids.

### Classification of the four tool results

| Run / tool | Class | Evidence |
| --- | --- | --- |
| audit `get_servicing_policy` | **REACHED the destination** | `Allow` row 14:53:50.380Z + policy-api receipt `/policy` 200 |
| audit `send_to_external_processor` | **REACHED the destination** (Audit let it through) | `AuditWouldDeny` row 14:53:51.594Z + test-receiver receipt `/ingest` 202 |
| enforced `get_servicing_policy` | **REACHED the destination** | `Allow` row 14:54:21.580Z + policy-api receipt `/policy` 200 |
| enforced `send_to_external_processor` | **PLATFORM-DENIED** | `Deny`/`DefaultDeny`/`Enforced` row 14:54:21.623Z + no test-receiver receipt (absence confirmed at 15:00:54Z) |

The UI's `http_error 403` is not the evidence; the decision row is.

### (3) Capture-off — WORKED, with a leftover

For v8 spans in `AppDependencies.Properties`, `gcp.vertex.agent.llm_request`, `llm_response`, `tool_call_args` and `tool_response` keys still exist, but their values are `{}` (length 2) on `call_llm` and `execute_tool …` rows; no prompt, response or payload text is present. The keys remain, so do not test capture by key existence. No `AppTraces` row matched `run-b960b642`, `ui-4fa3701da739` or `ui-7371110eb997`. **v6 (enforced): no app spans/traces landed at all** (the only `AppTraces` role in the window is `containment-demo-audit`), as in §0.10.

### (4) Gate 0 status — FAIL for the egress row, window 14:48Z–15:05Z

- Egress row ↔ `demo_run_id`: NOT PRESENT. `Data` is `GET https://<host>/policy` / `POST https://<host>/ingest`; the query string is absent even though the receipts show `?demo_run_id=run-…` was sent. No egress `Properties` key holds a run id.
- Egress row ↔ app `OperationId`: 0 of 129 decision rows join.
- Run id ↔ app spans: **LOST with capture-off.** In v7 the `run-…` id lived inside `tool_response`; in v8 that value is `{}` and no app row carries a run id. `run-…` now appears only in receipts (`ContainerAppConsoleLogs_CL`), `ui-…` only in the UI `ContainerLog`. There is no observed key from `ui-…` to `run-…`.
- Working join today: `Properties.host` + `Properties.path` + `Properties.enforcement` + time proximity to receipt `received_at` (denied row to the policy-api receipt: 14:54:21.623Z vs 14:54:21.587Z; same second as the two Allow/Deny pairs). Weak: no per-run key.
- Needed for a real join: put the run id where a URL-granularity decision log keeps it, i.e. in the **path** (egress `Properties.path` keeps `/policy` and `/ingest`; the query is stripped). NOT VERIFIED that a path segment is preserved; test by observing one decision row.

---

## 0.12 GATE 0 experiment — run id in the URL path. Audit v9 `ui-7de690b0a9a9`, enforced v7 `ui-e73b582c569c`; observed 2026-10-09 (window 15:10Z–15:20Z, queried 15:16:06Z and 15:17:21Z)

**Verdict: JOIN OBSERVED (egress decision row ↔ run id, by the path). Still FAIL for `OperationId`. Scope: one audit run, one enforced run.**

Agents (`AppRequests.Properties`): `containment-demo-audit` v9 (OperationId `fb79e2891c334e8b627997ba3812ddf2`), `containment-demo-enforced` v7 (`d866041db6657d826a0c83333666eca7`).

### (1) Egress decision rows, `AppDependencies`, `DependencyType=NetworkEgressDecision`

`Data` and `Properties.path` now contain the run id. Rows, verbatim `Data` + fields:

| Time (Z) | Mode | `Data` | `decisionResultCode` / `decisionReasonCode` / `matchedRule` |
| --- | --- | --- | --- |
| 15:11:06.384 | Audit | `GET https://humble-phoenix-466-policy-api.kinddune-9fead02b.canadacentral.azurecontainerapps.io/policy/run-2b95fdf4-0570-4719-ab1d-31d5ab110967` | `Allow` / `MatchedAllowRule` / `allow-policy-api` |
| 15:11:06.439 | Audit | `POST https://humble-phoenix-466-test-receiver.kinddune-9fead02b.canadacentral.azurecontainerapps.io/ingest/run-2b95fdf4-0570-4719-ab1d-31d5ab110967` | `AuditWouldDeny` / `AuditWouldDefaultDeny` / (none) |
| 15:13:31.308 | Enforced | `GET https://humble-phoenix-466-policy-api.kinddune-9fead02b.canadacentral.azurecontainerapps.io/policy/run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4` | `Allow` / `MatchedAllowRule` / `allow-policy-api` |
| 15:13:32.626 | Enforced | `POST https://humble-phoenix-466-test-receiver.kinddune-9fead02b.canadacentral.azurecontainerapps.io/ingest/run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4` | **`Deny`** / **`DefaultDeny`** / (none) |

`Properties.path` equals `/policy/run-…` or `/ingest/run-…` on each row, i.e. **the path IS preserved; the query string is still not** (the receipts' access log shows `?demo_run_id=run-…` was also sent).

### (2) Receipts, `ContainerAppConsoleLogs_CL`

| `received_at` (Z) | Service | Run id logged | Path / status |
| --- | --- | --- | --- |
| 15:11:06.394 | policy-api | `run-2b95fdf4-0570-4719-ab1d-31d5ab110967` | JSON `path: /policy/run-2b95fdf4-…`, `outcome: served`; access log `GET /policy/run-2b95fdf4-…?demo_run_id=run-2b95fdf4-…` 200 OK |
| 15:11:06.449 | test-receiver | `run-2b95fdf4-0570-4719-ab1d-31d5ab110967` | JSON `content_length_bytes: 192`; access log `POST /ingest/run-2b95fdf4-…?demo_run_id=run-2b95fdf4-…` 202 Accepted |
| 15:13:31.324 | policy-api | `run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4` | JSON `path: /policy/run-d6161cc4-…`, `outcome: served`; access log 200 OK |
| (none) | test-receiver | — | — |

The receipt JSON `demo_run_id` is the same string as the path id (the service logs both the path and the query copy; they match on every row seen).

### (3) Same id in decision row and receipt? Four tool results

| Run / tool | Decision row id | Receipt id | Same? | Class |
| --- | --- | --- | --- | --- |
| audit `get_servicing_policy` | `run-2b95fdf4-0570-4719-ab1d-31d5ab110967` | `run-2b95fdf4-0570-4719-ab1d-31d5ab110967` | **YES** | REACHED (`Allow` + receipt 200) |
| audit `send_to_external_processor` | `run-2b95fdf4-…` | `run-2b95fdf4-…` | **YES** | REACHED (`AuditWouldDeny` + receipt 202) |
| enforced `get_servicing_policy` | `run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4` | `run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4` | **YES** | REACHED (`Allow` + receipt 200) |
| enforced `send_to_external_processor` | `run-d6161cc4-…` | none | n/a | **PLATFORM-DENIED** (`Deny`/`DefaultDeny`/`Enforced` row, same run id in `Data`; no receipt) |

### (4) Enforced `send_to_external_processor`: absence re-checked

Deny row at 15:13:32.626Z. Re-queried **2026-10-09 15:17:21Z (3 min 49 s later)**: `ContainerAppConsoleLogs_CL` rows containing `run-d6161cc4-7d20-4c1f-bd2d-ab0d00d28cc4`: 2, **both `humble-phoenix-466-policy-api`**; all `test-receiver` rows 15:10Z–15:20Z: 2 (the audit run only, latest 15:11:06.910Z). A workspace `search` for the enforced run id returns only `ContainerAppConsoleLogs_CL` (policy-api) and `AppDependencies` (the two decision rows). No test-receiver receipt exists.

### App-side run id (audit only)

`AppTraces` rows (message `demo.tool_result`, audit v9) carry `Properties`: `demo.run_id` = `run-2b95fdf4-0570-4719-ab1d-31d5ab110967`, `demo.policy_mode`, `demo.agent_name`, `demo.agent_version` (`9`), `demo.tool_name`, `demo.succeeded`, `demo.http_status` (`200` / `202`), `demo.error_category`, `demo.duration_ms`, `demo.destination_host`. This is our `telemetry.py` output seen in a real row (VERIFIED), so for the audit run all three layers share one run id. The enforced run emits no app rows (egress to App Insights is `Deny` under Enforced, §0.10), so its Layer 1 is absent; the decision row + receipt absence stand on their own.

### Gate 0 verdict and limits

- **Egress decision ↔ run id: JOIN OBSERVED**, via `Properties.path` / `Data` (key `/policy/{run_id}`, `/ingest/{run_id}`). 4 of 4 decision rows in the window carry the run id; 3 of 3 receipts match their decision row's id.
- **Egress decision ↔ app `OperationId`: still FAIL** (no `OperationId` shared; Q6 `joined == false`).
- **`ui-…` ↔ `run-…`: no row links them.** `ui-7de690b0a9a9` / `ui-e73b582c569c` appear only in the UI `ContainerLog` (and the UI's own call URL); no row containing a `ui-` id also contains a `run-` id. The mapping is by time only. Reporting should key on `run-…`.
- **Limits:** one audit and one enforced run, one decision per tool call; not tested under concurrency; the path join depends on the run id being in the path (a design property of our own tools, not something the platform adds); `Data`/`path` retention of the path for other hosts is NOT VERIFIED.

## 0.13 A2A-path evidence — four `verify_demo.py` live runs through the A2A facade, observed 2026-10-09 (~17:22Z–17:28Z)

Source: Dallas's `scripts/verify_demo.py` live runs, sections B (audit) and C (enforced). Agents: audit v15, enforced v13, both on digest `sha256:33dbbf379282e675a5ef43c0cb37cfab3dac456695ff70f3b75eb63fa33e37b3`. A2A is off on the audit agent.

**Tested (observed, all four PASS):**

| Path | Mode | Run id | Tools at | Section | Result |
| --- | --- | --- | --- | --- | --- |
| direct `a2a:send` | audit | `run-ebc8e204-9f05-4068-a9cd-8daf8c0d7723` | ~17:22:39Z | B PASS | `Allow` + receipt; `AuditWouldDeny` + receipt |
| direct `a2a:send` | enforced | `run-a86344d2-5c00-44f1-803c-771e8682af6c` | ~17:23:08Z | C PASS | `Allow` + receipt; `Deny`/`Enforced`, no receipt (read 333 s after) |
| via UI | audit | `run-c9e4afa5-fd3e-4afa-953c-e8b048776fef` | ~17:27:20Z | B PASS | as above |
| via UI | enforced | `run-ac17f6c6-02f4-4e77-b697-35d73bab3e06` | ~17:27:40Z | C PASS | `Allow` + receipt; `Deny`/`Enforced`, no receipt (read 220 s after) |

**Caveats:**

- n = 2 audit and 2 enforced runs on this path.
- The harness did not print the matched egress/receipt ids. That each decision row matched its own run id is **inferred** from the script querying by run id; it was not independently re-queried here.
- The run id is generated per agent process, not per request.
- `OperationId` still does not join egress rows to app telemetry (§0.12, Q6 unchanged).
- The facade / A2A hop is the on-prem stand-in and is not policy-governed; the policy-governed hops are the agent's outbound tool calls.
- Agent-reported tool outcomes (202 / 403) are not platform evidence; only the egress decision rows and receipt presence/absence count.
- The A2A face is a facade over Responses; native A2A is unsupported for hosted agents (`docs/compatibility.md` B5d/B5e).
- The no-receipt reads at 333 s / 220 s show absence at that read time only, not forever.

**Proposed:** none added; this section records observation only.

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
| A separate `Microsoft.CognitiveServices` diagnostic-settings category for egress | **REVISED 2026-10-08 — see §0.4** | A `ManagedNetworkEvent` log category **does exist** on the account (table `AMLManagedNetworkEvent`). It has **never received a row** (0 in 30 d) and is **NOT VERIFIED** to carry RAI egress decisions. Project-linked App Insights remains the only *documented* path. |
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

### 2.2 Candidate join fields — all NOT VERIFIED

This is the GATE 0 shortlist. Nothing here is established; each row says what would prove
it. Checked in this order by **Q0** (§4).

| # | Candidate | Why it is plausible | Why it may fail | Status |
| --- | --- | --- | --- | --- |
| 1 | `OperationId` / `ParentId` on the egress `AppTraces` row matching our tool-span's `OperationId` | The guardrails doc (accessed 2026-10-08) says it is **"a span named Network egress decision"** that **"appears next to the request that triggered it"** in the Trajectories timeline. A span nested in the same trace normally shares the App Insights operation id. | *Normally* is doing the work. Generic App Insights behaviour, **not a documented Foundry guarantee** (`docs/compatibility.md` C3 / Blocker 4). The span may be emitted by the sandbox proxy under its own trace. | **NOT VERIFIED — strongest candidate. Check first.** |
| 2 | A key inside the egress row's `Properties` bag echoing a request header or URL | The decision is made on the outbound request, and the portal shows a **Destination** field described as *"the method and URL of the outbound request"*. Our `demo_run_id` travels in the URL as a `demo_run_id` query param on `get_servicing_policy`. | The doc describes Destination as method + URL at the *portal* layer; whether the logged property retains the query string is unknown, and query strings are commonly stripped. The `send_to_external_processor` call carries the id in a **header only**, not the URL — so even if this works it would only correlate the *allowed* call. | **NOT VERIFIED.** |
| 3 | `AMLManagedNetworkEvent.CorrelationId` | A real column (§0.4) literally named for correlation. | The table has never received a row, is not routed to our workspace, and is not documented to carry RAI egress decisions at all. Two unknowns stacked. | **NOT VERIFIED — weak.** |
| 4 | Time window + destination host + agent version | Always available. | Not a join. Fully analysed in §5. | **This is the fallback, not a candidate.** |

**Explicitly rejected — a Transform rule injecting our run id as a header.** The guardrails
doc (accessed 2026-10-08) documents `action.headers` with `Set` / `Insert` / `Remove` on
`Transform` and `Rewrite` rules. Someone will propose using it to stamp a correlation
header. It does not work for us, for three independent reasons:

1. Values are **static** (`value`) or a **managed-identity token** (`valueRef`). There is no
   per-invocation value, so it cannot carry a per-run `demo_run_id`.
2. It writes **into the outbound request**, not into the decision record. It is the wrong
   direction entirely.
3. Changing a rule's `actionType` from `Allow` to `Transform` alters the experimental
   variable. The RAI policy must stay the *only* difference between the two agent versions.

Recorded here so it is rejected once, with reasons, rather than re-proposed.

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

### Q0e — Platform egress decisions as OBSERVED (use this, not Q0a/Q5a)

**Runnable now. Columns VERIFIED 2026-10-09** (§0.6.2–0.6.3).

```kusto
AppDependencies
| where TimeGenerated between (datetime(<RUN_START>) .. datetime(<RUN_END>))
| where DependencyType == "NetworkEgressDecision"
| extend p = parse_json(Properties)
| project TimeGenerated, Target, Data,
          decision = tostring(p.decision), decisionResultCode = tostring(p.decisionResultCode),
          enforcement = tostring(p.enforcement), matchedRule = tostring(p.matchedRule),
          decisionReasonCode = tostring(p.decisionReasonCode), host = tostring(p.host),
          egressDecisionId = tostring(p.egressDecisionId), OperationId, ParentId
| order by TimeGenerated asc
```

Join test against app rows (expected FAIL as of 2026-10-09):

```kusto
let app_ops = union AppTraces, AppExceptions
    | where OperationId != "00000000000000000000000000000000" | distinct OperationId;
AppDependencies
| where DependencyType == "NetworkEgressDecision"
| summarize n = count() by joined = OperationId in (app_ops)
```

---

### Q0 — **THE GATE 0 QUERY.** (Q0a/Q0b/Q0c filter `AppTraces`; superseded by Q0e, see §0.6.2) Run this first, after the first invocation.

**BLOCKED on one real invocation. Runnable the instant Dallas's first call completes.**
**Unverified columns:** none in Q0a/Q0b — `AppTraces.Message`, `Properties`, `OperationId`,
`ParentId` are all confirmed columns of this workspace's `AppTraces` table (§1.3), and the
literal `"Network egress decision"` is from the primary doc (accessed 2026-10-08). What is
unverified is whether any **rows** exist and what is **inside** `Properties`.

Run the four steps in order and stop at the first one that gives a definitive answer.
Record the outcome in §2.1 and §5 with the date, whichever way it goes.

```kusto
// Q0a — Does the platform emit anything at all? Answers "exists / rows / no rows".
AppTraces
| where TimeGenerated > ago(1h)
| where Message == "Network egress decision"
| project TimeGenerated, Message, Properties, OperationId, ParentId, AppRoleName, AppRoleInstance
| order by TimeGenerated asc
```

```kusto
// Q0b — THE GATE. Does the egress decision share an OperationId with our tool span?
// Candidate 1 in §2.2. This single result decides the evidence model.
let app_ops =
    AppTraces
    | where TimeGenerated > ago(1h)
    | where tostring(Properties) has "<RUN_ID>"
    | distinct OperationId;
AppTraces
| where TimeGenerated > ago(1h)
| where Message == "Network egress decision"
| extend joined = OperationId in (app_ops)
| summarize decisions = count() by joined
```

```kusto
// Q0c — Candidate 2. Does our run id appear ANYWHERE in the decision row, in any form?
// Deliberately a blunt substring scan across the whole row. No column is assumed.
AppTraces
| where TimeGenerated > ago(1h)
| where Message == "Network egress decision"
| extend whole_row = strcat(tostring(Properties), "|", OperationId, "|", ParentId,
                            "|", OperationName, "|", AppRoleName)
| extend carries_run_id = whole_row has "<RUN_ID>"
| summarize rows = count() by carries_run_id
```

```kusto
// Q0d — Candidate 3, opportunistic. Only meaningful if a ManagedNetworkEvent diagnostic
// setting has been applied to our workspace (it has NOT been, as of 2026-10-08 — §0.4).
// Expect a table that resolves and returns nothing.
AMLManagedNetworkEvent
| where TimeGenerated > ago(1h)
| project TimeGenerated, OperationName, CorrelationId, Category, ResultType, Level, Properties
```

**How to read Q0 — the three-way rule, not negotiable:**

| Observation | Finding | Consequence |
| --- | --- | --- |
| Q0a errors with `SEM0100: Failed to resolve table` | **Table does not exist** | Schema is wrong. Re-run at App Insights resource scope as `traces` (Q5b). If both fail → **BLOCKED**, stop. |
| Q0a returns zero rows, and `union AppTraces, AppRequests, AppDependencies` is also empty | **Nothing ingested at all** | The invocation didn't happen, or ingestion is broken. First suspect: the connection `error` in §0.1. **INCONCLUSIVE.** |
| Q0a returns zero rows, but our own tool spans ARE present for this run | **Platform emitted no decision** | Genuinely interesting, and still **INCONCLUSIVE** — primary guidance: *"Do not treat a missing event as proof that a call was allowed."* |
| Q0a returns rows, Q0b `joined == true` | **GATE 0 PASS** | Strong correlation. Fill §2.1 and update §5 the same day. |
| Q0a returns rows, Q0b all `false`, Q0c `carries_run_id == true` | **GATE 0 PASS, weaker** | Correlation by embedded id. Record the exact field in §2.1. |
| Q0a returns rows, Q0b all `false`, Q0c all `false` | **GATE 0 FAIL** | No joinable field. Evidence model degrades to the §5 fallback. Report immediately; this changes the demo narrative, not just the queries. |

A FAIL is a legitimate outcome and must be reported as fast as a PASS.

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

**BLOCKED — needs one real invocation.** Q0a supersedes Q5a; keep Q5b, the resource-scope
fallback, which is the form the primary doc publishes.
**Unverified columns:** every property key. `Message` and the literal string are verified
from the primary doc (accessed 2026-10-08); nothing inside the bag is.

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

### Q6 — SUPERSEDED BY Q0

Q6 was the original correlation probe. **Q0b is its replacement** and is the version to
run. Kept here only so references to "Q6" in earlier notes resolve. Do not run both.

---

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

1. **Q0b returns `joined == true`.** Cheapest possible fix — it may already work via generic
   App Insights `OperationId` propagation. **Run Q0 first, immediately after the first
   successful deployed run.** Do not build anything else until Q0 has been answered.
2. **A property key in the decision record that echoes our run id** (Q0c). Inspect the raw
   row for anything resembling it. Note the asymmetry recorded in §2.2 candidate 2: the
   allowed call carries the id in the URL query string, the denied call carries it in a
   header only. If Q0c passes for one tool and not the other, say so — a half-correlation
   is a partial result, not a pass.
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

3. **C1's "NOT FOUND: any `Microsoft.CognitiveServices` diagnostic-settings resource-log
   category for egress decisions" needs a correction.** A `ManagedNetworkEvent` log category
   **does exist** on this account (VERIFIED 2026-10-08, §0.4), with Log Analytics table
   `AMLManagedNetworkEvent`. C1's underlying claim still holds — that category has **never
   received a row** (0 in 30 days, in a workspace where the same resource's `allLogs`
   pipeline is demonstrably delivering hundreds of `RequestResponse` rows), the primary
   guardrails doc names only Application Insights, and the `AML` prefix points at the
   managed-VNet feature rather than RAI egress. **Proposed edit to `docs/compatibility.md`
   C1:** change "NOT FOUND: any … category" to "A `ManagedNetworkEvent` category exists on
   the account but has produced no data and is NOT VERIFIED to carry RAI egress decisions;
   project-linked Application Insights remains the only documented path." Compatibility is
   the verified-facts file, so **Ripley or the owner makes that edit** — I am recording the
   evidence, not editing it unilaterally.

**§D — managed VNet composability, blocking gap.** No telemetry conflict, and §0.4 adds a
data point that cuts **against** the managed-VNet path being active: Foundry here runs with
`networkInjections` / `useMicrosoftManagedNetwork = true`, and the managed-network event
category has produced nothing. That is consistent with D's finding that the two features
are undocumented together — it is **not** evidence either way, because nothing has been
invoked yet. One consequence worth naming: if the managed-VNet path is ever adopted and
outbound traffic ends up governed by managed-VNet outbound rules instead of the egress
policy, the decision record in §2 may not be produced at all, and every Layer-2 query here
goes silent. That would be a **change of evidence source**, not a pass. Re-verify §2 end to
end if §D is resolved in the VNet direction.

---

## 7. Validation checklist before any demo run

1. §0 fixed — project has an App Insights connection, verified by re-running the
   `connections` GET and seeing a non-empty `value`.
1. **GATE 0 answered** — Q0 run after the first real invocation, outcome recorded in §2.1
   and §5 with the date. **Nothing downstream is built before this.**
2. §0.1 confirmed — project App Insights connection present with `authType: ApiKey`
   (**confirmed 2026-10-08**); re-check if anything is redeployed.
3. `rai_config.rai_policy_name` read back for both agent versions — **done, and it passes**
   (`verify_version()` in `src/containment_demo/deploy.py`, init container exited 0 at
   2026-10-08 19:35Z, §0.5). Note the limit: this proves the policy field is *set*, not that
   it is *enforced*. Steps 1 and 7 are what test enforcement.
4. Q8 green — both container apps logging from our ACR images (**confirmed 2026-10-08**,
   revisions `…--0000001`), recent rows.
5. Q1 green for a throwaway run id — Layer 3 proven live before the agent is involved.
6. Q3a run — the table and real `Properties` keys for our spans recorded in §1.3 with a date.
7. Q2 and Q2a both zero for the un-allowlisted receiver.
8. Only then does a run produce a result. Before that, every run is **inconclusive**.
