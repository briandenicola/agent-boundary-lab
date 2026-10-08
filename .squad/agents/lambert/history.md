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

### 2026-10-08 — telemetry-map.md first validation pass

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

### 2026-10-08 — Telemetry-map complete, App Insights connection blocker unblocked

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
