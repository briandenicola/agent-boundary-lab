# Project Context

- **Owner:** briandenicola (Brian)
- **Project:** agent-boundary-lab — a demo proving that outbound network containment for an
  AI agent is enforced by the **Microsoft Foundry platform**, not by application code. A
  Python Google ADK agent with exactly two HTTP tools runs in a Foundry hosted-agent
  container. One tool calls an allowlisted hostname (expected success); the other calls a
  hostname deliberately omitted from the allowlist (expected platform denial). The same
  image digest is deployed twice, and the Audit vs Enforced RAI network egress policy is
  the **only** experimental variable.
- **Stack:** Python 3.12 (uv — **pip cannot install this project**), Google ADK 2.11,
  Terraform with the azapi provider for preview Foundry resources, Azure Foundry hosted
  agents, AKS, Container Apps, Azure Database for PostgreSQL, Dapr Workflow (Phases 8–9),
  pytest, go-task. Region canadacentral. Model gpt-5.4-mini.
- **Created:** 2026-10-08

## Core Context

Non-negotiable project rules (from `.github/copilot-instructions.md` — violating any of
these invalidates the demo):

- Both tools are **always registered**, in every mode. No conditional registration, no
  code-level hostname allowlist, no prompt-only refusal, no mode-specific branching.
- No arbitrary-URL tools. Destinations come from validated startup config.
- Never present an application check as platform enforcement. A bare HTTP 403, DNS error,
  timeout, model refusal, or missing log is **not** proof of containment. Classify HTTP /
  TLS / DNS / timeout failures separately. **Missing evidence is inconclusive, never a pass.**
- Do not invent SDK APIs, platform field names, or monitoring tables. Verify against
  primary references and record the access date. Preview feature unavailable → mark
  **blocked** and stop.
- Approval gate: generate code, tests, and deployment artifacts freely; get Brian's
  approval before creating billable resources, changing Azure policies, publishing images,
  or sending telemetry somewhere new.
- HTTP hygiene: TLS verification always on, explicit bounded timeouts, redirects disabled,
  no fallback destination.
- Synthetic data only. Label local runs as functional tests, not containment proof.

Brian's standing preferences:

- **He runs every `task` command himself.** Read-only `az` queries are fine. Never apply
  Terraform or create billable resources.
- **No `az` CLI in anything that ships.** Terraform or SDK only — that is what the client
  uses.
- Short, plain, actionable output. No hedging, no unsolicited caveats, no long recaps.
- Commit and push completed work after each feature.

## Current state (2026-10-08)

Deployed and working in canadacentral: Foundry account (inbound-private), AKS, ACR,
Postgres, both Container Apps serving real images, both RAI policies live and correct.
80 unit tests pass. Agent image built and digest known.

**Nothing is enforced yet — no agent version exists**, so neither policy is attached to
anything. That is the active blocker. See `docs/egress-control.md` for the full mechanism
and `docs/compatibility.md` §B9 for the deployment API.

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

### 2026-10-08 — GATE 0 established: Q6 (OperationId correlation) runs first (Lambert's action)

`demo_run_id` reaches Layer 3 (receipts) but is not documented to reach Layer 2 (platform egress
decisions). Q6 (test OperationId propagation) becomes GATE 0 and must run on the first hosted
agent run before any other build. **Pre-committed outcome:** if Q6 returns false, the evidence model
needs rework and the demo claims "three consistent observations", never "joined rows". Procedural
control (serial runs + timestamps) then substitutes for missing technical correlation.

- **The Foundry project has zero connections** (`GET .../projects/.../connections?api-version=2025-06-01`
  → `{"value": []}`). App Insights `humble-phoenix-46689-ai` exists but is **not linked to the
  project**. Per compatibility C1/C4 that is the only known path for egress decision records,
  so Layer 2 currently produces nothing. Any run today is inconclusive by construction.
- **App Insights is workspace-based** (`IngestionMode: LogAnalytics`, workspace
  `humble-phoenix-46689-logs` / `def03e45-a400-4fed-957f-25d133ab1993`). So at workspace scope
  the tables are `AppTraces`/`AppDependencies`/`AppRequests`/`AppExceptions`, not the classic
  `traces`/`dependencies`. Compatibility C1 quotes `traces`, which is correct at App Insights
  *resource* scope. Not a contradiction — a scope difference. Always try both and record which
  one returned rows.
- Workspace table schemas read directly (not guessed): `AppTraces` has `Message`, `Properties`,
  `OperationId`, `ParentId`, `AppRoleName`; `AppDependencies` has `Target`, `DependencyType`,
  `Success`, `ResultCode`, `DurationMs`.
- **Layer 3 is fully verified.** Real receipts observed in `ContainerAppConsoleLogs_CL` from
  both Container Apps on our ACR images, carrying `demo_run_id` end to end. JSON arrives as a
  string in `Log_s`; parse with `parse_json(Log_s)`. `Stream_s == "stdout"` on real receipts
  (older placeholder-image rows were `stderr`) — do not filter on it.
- **Hygiene defect found:** a `test-receiver` receipt with `demo_run_id == ""` exists in the
  log. "Zero receipts for our run id" therefore is not "nothing arrived". Added Q2a as a
  required companion query.
- **Measured ingestion lag ≈1.5 s** for Container Apps console logs. Use in-payload
  `received_at`, never `TimeGenerated`, for ordering arguments.
- Evidence strength today: Layer 1 verified from source but unverified in the sink; Layer 2
  unobservable; Layer 3 fully verified. The correlation Layer 1↔2 remains NOT FOUND — Q6 is
  written to test it empirically the moment an agent version exists, and must be the first
  query run.

### 2026-10-08 — Runbook carries weaker "three consistent observations in one window" claim until GATE 0 answered

Dallas delivered `docs/demo-runbook.md` and `docs/evidence-template.md` with three embedded team
rules:

1. **NOT COLLECTED is a first-class evidence state.** Every signal has three states
   (present/absent/NOT COLLECTED), and NOT COLLECTED forces inconclusive. Runbook Sections B and
   C are stubs returning `not_implemented`, which is NOT COLLECTED by another name, which is why
   no hosted verdict is possible today.

2. **Observation window is an explicit constant.** `W_start = T0`, `W_end = T_end + 120s` (UTC).
   Query bounds are explicit pair, never relative. Use in-payload `received_at`, not
   `TimeGenerated`. 120 s tail is ~1.5s measured ingestion lag plus headroom, not late-good-news
   fishing.

3. **"What this run did NOT prove" is mandatory** (Evidence template §8). Reviewers send back any
   template with blank §8. Addresses 11 specific potential claims: Blocker 3 implicit allow, Blocker
   1 stage 2 attribution, digest acceptance server-side, authoring ≠ enforcement, private endpoint
   direction, protocol coverage, harness governance, preview status, prompt injection, etc.

**Impact on Layer 1↔2 correlation:** Runbook assumes `joined == false` (platform egress records do
not copy `demo_run_id`) until Q6 says otherwise. **Weaker claim in force:** three consistent
observations in one bounded window, never "three rows joined on shared key". Q6 (OperationId
propagation test) is GATE 0 and runs first on first hosted agent invocation. If Q6 returns
`joined == false`, runbook §4 and template §4 stay as written. If Q6 returns true, they are
replaced (not softened). Pre-committed outcome branches written in advance.

**Commits:** 1450235 (demo-runbook.md), c3bc181 (evidence-template.md)

- **Platform egress property keys (§2.1) left deliberately blank.** Portal UI labels (Decision, Reason, Matched rule, Rule source, Enforcement, Destination, Default action) are **not** Log Analytics column names. Fill this table only after a real row is observed in live run. Do not guess.
- **Correlation gap is structural, not a query problem.** Layer 1 (app trace) carries `demo_run_id` in HTTP header/query param. Platform egress decision records are not documented to copy it. Fallback: run window + hostname + agent version, which breaks under concurrency and depends on unmeasured Foundry-side clock lag. **Procedural control required:** demo runs strictly serial with timestamps.
- **First post-deploy action: Run Q6.** Test whether generic OperationId propagation closes the Layer 1↔2 gap for free. If it does, join works. If not, serial-run procedural control stays in place.
- **App Insights project connection schema fully verified (2026-10-08)** from installed SDK source, not documentation:
  - Type: `Microsoft.CognitiveServices/accounts/projects/connections@2026-05-15-preview` (preview, not stable)
  - Scope: child of project, not account
  - `category: "AppInsights"`, `authType: "ApiKey"`, `credentials: { key: <connection string> }`
  - The "API key" is the **connection string**, not instrumentation key or resource id
  - Trap: `AAD` or `ManagedIdentity` would apply cleanly and silently do nothing. Auth type check is not optional.
  - **Parker's action:** Add connection in Terraform (completed; see parker-appinsights-connection-and-endpoint-images.md).
- **Pre-run validation checklist (§7):** Treat query failures as INCONCLUSIVE, never fail. Q2 always paired with Q2a. Use in-payload `received_at`, not `TimeGenerated`.
- **Standing rule:** §2.1 stays blank until real observation. Platform telemetry audit cannot invent column names.

### 2026-10-08 (second pass) — GATE 0: does demo_run_id reach the platform egress layer?

**Verdict: INCONCLUSIVE, not a fail. The sink exists and is correctly wired; it has received
zero telemetry because no invocation has happened yet.**

- **Sink exists (VERIFIED).** Project connection `appinsights-connection`, category
  `AppInsights`, `authType: ApiKey`, `isDefault: true`, target `humble-phoenix-46689-ai`,
  created 2026-10-08T17:29:49Z. Satisfies both assertions in
  `tasks/Taskfile.cloud.yml :: cloud:app-insights-connection`. Supersedes my earlier
  "project has no connections" finding.
- **Watch item:** that connection carries a non-null `error` — *"Connection subresourceTarget
  is not supported for PE creation"*, with `peRequirement`/`peStatus` = `NotApplicable`.
  Probably benign (telemetry egresses outbound), but NOT VERIFIED. If Q0 returns nothing
  after a confirmed invocation, this is suspect #1.
- **Sink is receiving nothing (VERIFIED).** `union AppTraces, AppRequests, AppDependencies,
  AppExceptions, AppEvents | where TimeGenerated > ago(7d)` → empty. The component has never
  received a record.
- **New: a `ManagedNetworkEvent` diagnostic log category DOES exist on the Foundry account**
  (account scope only; project scope has only Audit/Trace/AllMetrics). Table is
  `AMLManagedNetworkEvent`, schema VERIFIED: TenantId, TimeGenerated, OperationName,
  **CorrelationId**, Category, ResultType, Level, Properties, SourceSystem. This partially
  revises the "NOT FOUND" in compatibility C1 — proposed correction written into
  telemetry-map §6, for Ripley/owner to apply (compatibility is the verified-facts file, I
  don't edit it unilaterally).
- **But it has never produced data:** 0 rows in 30 days. Proven by control test — a bogus
  table name errors with `SEM0100: Failed to resolve table`, while `AMLManagedNetworkEvent`
  returns `[]`. So: *exists, zero rows*, not *missing*. Meanwhile the same account's
  `allLogs` pipeline delivered 483 `RequestResponse` + 54 `Audit` rows in 24h to the
  governance workspace. The pipeline works; this category is simply silent.
- **No diagnostic setting routes anything to OUR workspace.** The only setting on the account
  is `setByPolicy-MCAPSGovernance` → `mcaps4b5e8cc21dda18f2382e-la` in RG `McapsGovernance`.
  I have read access to that workspace, which is useful.
- **Primary doc re-read (add-hosted-agent-guardrails, accessed 2026-10-08):** egress decisions
  go to the **project's Application Insights**, `traces`, `message == "Network egress
  decision"`. It is described as **a span** that "appears next to the request that triggered
  it" — that phrasing is the basis for the OperationId join being candidate #1.
- **Rejected correlation idea, recorded so it isn't re-proposed:** using a `Transform` rule's
  `action.headers` to stamp a correlation header. Values are static or managed-identity-token
  only (no per-invocation value), it writes into the *outbound request* not the decision
  record, and changing a rule's actionType would alter the single experimental variable.
- **Asymmetry worth remembering:** `get_servicing_policy` carries `demo_run_id` in BOTH the
  URL query string and a header; `send_to_external_processor` carries it in a **header only**.
  If the platform logs the URL but not headers, we'd correlate the allowed call and not the
  denied one — a half-correlation, which is a partial result, not a pass.
- **CORRECTED same day.** I first wrote that policy attachment was unverified and needed an
  in-VNet readback. Wrong — the readback already exists and already ran. `verify_version()` in
  `src/containment_demo/deploy.py` runs in the init container, in-cluster, reads
  `version.definition` back after creation, and raises `DriftError` on a missing definition, a
  `rai_policy_name` mismatch, or an image mismatch; `assert_single_variable()` then asserts
  both agents pin the same digest. Init container exited 0 at 19:35Z, so both agents passed.
  **Lasting lesson: before declaring something unverifiable from my vantage point, check
  whether the repo already verifies it from a better one.** My HTTP 403 was a fact about
  querying the data plane from outside the VNet, not evidence about attachment.
- **The distinction that survives that correction, and matters:** a readback proves the policy
  **field is set**; it does not prove the policy is **enforced at runtime**. An init container
  exiting 0 means a version was *accepted*. A policy that attached cleanly but enforces nothing
  is indistinguishable from a working Enforced agent that allows everything — which is exactly
  what Layer 2 and Q0 exist to settle.
- **ManagedNetworkEvent: decided, do not enable.** We don't turn on diagnostic categories
  speculatively. It stays a documented fallback with its NOT VERIFIED status and the
  `CorrelationId` column noted. Revisit only if Q0a is empty after a confirmed invocation.
- Control-plane policies confirmed correct: `egress-audit` (Audit/Deny/allow-policy-api),
  `egress-enforced` (Enforced/Deny/allow-policy-api).
