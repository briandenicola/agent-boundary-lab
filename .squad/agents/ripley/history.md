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

## Learnings (from 2026-10-08 squad hiring session)

### Agent Deployment Architecture (Brett, Parker)

- `src/containment_demo/deploy.py` uses `azure-ai-projects` 2.8.0 SDK to create agent versions
- Init container runs same digest-pinned image with command override: `["/opt/deploy-venv/bin/python", "-m", "containment_demo.deploy"]`
- All config from `DEMO_*` environment variables injected by Terraform
- **Digest-only validation:** image must be `repo@sha256:<64 hex>`; server-side acceptance unverified until first run
- If service rejects digest: `DigestRejectedError`, exit 3, STOP (no tag fallback)
- Idempotent: version matching both image digest AND policy ARM id is reused; restart creates nothing

### Dependency Isolation: Deploy venv (Brett)

- `azure-ai-projects` requires `openai>=3`, which would drag litellm 1.104→1.83 and openai 2.54→3.26
- That changes the agent's own model stack (uncontrolled variable)
- **Solution:** `/opt/deploy-venv` inside agent image, separate from system interpreter
- Agent's dependencies untouched; image digest remains the control variable
- Unit test `test_dependency_overrides.py` guards this (if `google-adk` relaxes OpenTelemetry pin, suite fails on purpose)

### Telemetry and Evidence Paths (Lambert)

- **Layer 2 blocker resolved:** Foundry project had zero App Insights connections; now connected via Terraform (`infra/cloud/project-connections.tf`)
- Schema verified from SDK source (2026-10-08): category `AppInsights`, auth type `ApiKey`, credentials key is **connection string** (not instrumentation key)
- **Query scope matters:** App Insights workspace (LogAnalytics mode) uses `AppTraces`; resource scope uses `traces`. Both forms in `docs/telemetry-map.md`.
- **Correlation gap (Layer 1 ↔ Layer 2):** Platform not documented to carry run id into egress decision records. Fallback: serial runs with timestamps as procedural control.
- **First post-deploy action:** Run Q6 (test OperationId propagation) before building anything else

### Verification Harness (Dallas)

- **Section A now PASS** (exit 0): baseline transport + receipt retrievability both working
- Receipt absence has four outcomes (rows with marker / without marker / no rows proven retrievable / no rows unproven). Call `classify_receipt_absence()` in any probe.
- **A5 hard gate:** test receiver POST with no credentials must answer 2xx. Parker: do not add authentication or IP restrictions.
- **Never probe without marker.** Unmarked baseline plants unattributable receipt, manufacturing the ambiguity A7 detects. Marker is not credential; it is traceability.
- **Bound log queries:** explicit (start_time, end_time), never "last N minutes". Padded windows contaminate results.
- `task verify:baseline` is pre-demo gate; run before any demo run, never after failure

### Known Risks (All Phases)

1. **Server-side digest acceptance:** SDK accepts client-side; service behavior unknown. First hosted run answers it.
2. **RBAC assumption on `agents/versions` write:** `Cognitive Services User` wildcard presumed to cover it (unverified). If 403 on init container, suspect this before federated credential.
3. **Missing evidence is inconclusive, never pass.** Unattributed arrival outranks healthy pipeline. Proof requires both the positive signal (rows with run id) and proven absence (no rows at all + retrievability confirmed in same window).
4. **Demo runs must be strictly serial.** One run id at a time, start/end timestamps recorded. Substitutes process control for missing technical join.
5. **ACTION REQUIRED (Brian before next deploy):** Add to `.env`:
   ```
   ENDPOINT_IMAGE_TAG=latest
   ```
   Current apps live on `:latest` out of band; empty tag rolls them back to placeholder.

### Team Decisions (Binding)

- No `az` CLI in shipped code (tasks/ exempt); Terraform or SDK only. Enforced by `scripts/check_no_az.sh`.
- Two separately-named agents: `containment-demo-audit` and `containment-demo-enforced` (not versions).
- One image tag for both endpoints (policy API + test receiver); cannot drift apart.
- Init-container contract: venv path, module path, env vars all specified in `infra/k8s/variables.tf`.
- Kubernetes cluster in separate Terraform root (`infra/k8s/`) with own state; Apply order: `cloud:up` → `build:agent` → `cloud:harness-up`.

<!-- Append new learnings below. Each entry is something lasting about the project. -->
