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

## Learnings (2026-10-08 — PLAN.md re-gate)

### A plan written before verification is a liability, not a baseline

`docs/PLAN.md` survived four agents' verification work unchanged. By the time I read it, it
was describing a deployment path that cannot work (`az` CLI cannot attach an RAI policy, so
it cannot deploy either side of a single-variable experiment), a payload shape that does not
exist in the SDK that actually ships, and a correlation that nobody has.

**Rule going forward:** whenever `docs/compatibility.md` gains a correction, the plan gets
re-gated in the same session. A stale plan looks authoritative, which is worse than no plan.

### The biggest hole was absence, not error

The worst thing in the old plan was not a wrong fact. It was the **missing gate**: nothing
anywhere said "find out whether `demo_run_id` reaches the platform layer before building
the evidence story on top of it". Wrong facts get caught on contact. Missing gates do not.
Audit plans for what they do not mention.

### Decide the branch before running the test

GATE 0 now carries both outcomes written down in advance. If Q6 returns `joined == false`
after a long build, the pressure to call the time-plus-hostname fallback "correlation" will
be considerable. Pre-committing the weaker sentence — "three consistent observations in one
short window, not three rows joined on a shared key" — removes the room to negotiate with
ourselves later.

### Terraform authoring is not evidence, and neither is client-side acceptance

Two instances of the same error pattern in this repo:
- the App Insights project connection exists in Terraform; nobody has re-read the
  `connections` endpoint and seen a non-empty `value`
- `ContainerConfiguration.image` is an unvalidated `str`, so the digest passes client-side
  and says nothing about whether the service accepts it

Both look like progress in a diff. Neither is an observation. Always ask what was read
back, from where, and on what date.

### Documented decisions drift from code silently

`.squad/decisions.md` records the init-container command as
`["/opt/deploy-venv/bin/python", "-m", "containment_demo.deploy"]`. `infra/k8s/harness.tf`
runs `["python", ...]`, and the Dockerfile installs `azure-ai-projects` only into
`/opt/deploy-venv`. The decision record was right; the code quietly was not. Found by
reading the file, not by trusting the record. **Spot-check code against decisions.md when
re-gating.**

### Blocker 3 needed a test and had none

"The implicit allowlist is unenumerated" sat as a noted risk with no action. If an
undocumented implicit allow is what makes the permitted call succeed, the positive half of
the demo proves nothing. Removing the explicit allow rule and confirming the permitted host
is then denied too is now a Phase 6 item. **A risk without a test is a sentence.**

### 2026-10-08 — PLAN.md corrected for the kustomize migration

- `infra/k8s/` is gone. Cluster workloads are `kubectl` + kustomize manifests under
  `deploy/kustomize/base/`, streamed through `sed` from `terraform output -raw` against
  `infra/cloud`. Manifests are never mutated on disk. Task names unchanged.
- The Terraform failure mode is worth remembering: hashicorp/kubernetes 2.38.0 on
  Terraform 1.16.4 wrote `kubernetes_deployment_v1.harness` tainted with an all-null
  `identity` block after a failed rollout wait, and every later refresh tripped
  `Unexpected Identity Change`. Deleting the state file was the adoption mechanism; the
  live objects kept running. Manifests have no state to corrupt.
- `harness-plan` is a server-side dry run, not `kubectl diff`, because a diff prints the
  Secret into any captured demo log. `--server-side --force-conflicts` is permanent, not
  first-run-only.
- The init-container interpreter defect is **fixed in the manifest** and has never been
  observed to run. I recorded it as resolved without promoting it to a tested result.
  Phase 4 stays blocked on digest acceptance, RBAC, and managed-VNet attribution.
- Phase numbering in the brief was off by one: Dapr Workflow on AKS is **Phase 8**, not
  Phase 9. Fixed both — Phase 8 no longer calls for `infra/aks/` or `infra/dapr/`
  Terraform roots, Phase 9's `samples/onprem_harness/` gets its own kustomize overlay.
- GATE 0 and every acceptance criterion untouched. The only GATE 0 edit was removing the
  dangling pointer to a defect that no longer exists; the gate's branch table and the
  "procedural control" caveat are unchanged.

### 2026-10-08 — Verified the kustomize migration for drift, phase numbers, and scope

- **Orchestration log created; session log 2026-10-08T18:32:44Z-kustomize-migration.md (Commit 2f5a086)**
- **PLAN.md corrections:**
  - Removed all references to `infra/k8s/harness.tf` (deleted by Parker)
  - Clarified that cluster workloads are `kubectl` + kustomize, not Terraform
  - Corrected phase numbering: Dapr Workflow is Phase 8, not Phase 9
  - Phase 8 no longer calls for `infra/aks/` and `infra/dapr/` Terraform roots — they are now kustomize overlays
  - Moved "Init-container interpreter defect" from Blocked → Resolved; defect was fixed in the manifest before it was ever observed to run
- **Scope finalized:** Future phases (8–10) use kustomize overlays exclusively. No new Terraform root modules for Dapr or on-premises harness.
- **All acceptance criteria and GATE 0 remain intact.** The cutovers were organizational, not technical.

