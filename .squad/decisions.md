# Squad Decisions

## Active Decisions (2026-10-08)

### No `az` CLI in Shipped Code (Enforced by `scripts/check_no_az.sh`)

**By:** Parker, Brett, Coordinator  
**Date:** 2026-10-08  
**Status:** Implemented

- No Azure CLI in application code or Docker image
- `tasks/` directory (operator tooling) is exempt
- Shipped code uses Terraform or Azure SDK only
- Read-only CLI operations (`az account show`, `az resource list`, `az aks get-credentials`, `az acr` operations, teardown `az group delete`) remain in `tasks/` as operator tooling
- Enforced by lint target `lint:all`

### No GitHub Actions (Everything Driven by `task`)

**By:** Coordinator  
**Date:** 2026-10-08  
**Status:** Implemented

- Removed `.github/workflows/checks.yml` per Brian's instruction
- All CI/CD workflows driven through Taskfile and `task` command
- GitHub Actions no longer involved in project automation

### Two Separately-Named Agent Versions

**By:** Brett  
**Date:** 2026-10-08  
**Status:** Implemented

- Not two versions of one agent, but **two agents with distinct names:**
  - `containment-demo-audit`
  - `containment-demo-enforced`
- Deployed with different RAI policies as the only environment difference
- Evidence label: `DEMO_POLICY_MODE` (audit / enforced)
- `assert_single_variable` and unit tests enforce no other differences

### Digest Pinning Required (No Tag Fallback)

**By:** Brett, Parker  
**Date:** 2026-10-08  
**Status:** Implemented

- `DEMO_AGENT_IMAGE` must be `repo@sha256:<64 hex>` format
- If service rejects digest: `DigestRejectedError`, exit 3, STOP
- No retry with tag; no configuration for fallback
- Experiment control (image digest) cannot drift
- Server-side acceptance unverified until first hosted run

### Deploy SDK in Separate venv (Same Image)

**By:** Brett, Parker  
**Date:** 2026-10-08  
**Status:** Implemented

- `azure-ai-projects` requires `openai>=3`, which drags litellm 1.104→1.83, openai 2.54→3.26
- Separate venv `/opt/deploy-venv` inside agent image isolates deployer dependencies
- Init container uses: `["/opt/deploy-venv/bin/python", "-m", "containment_demo.deploy"]`
- Agent's model stack remains unaffected; image digest is uncontrolled variable
- One image, one digest, two isolated dependency sets

### One Image Tag for Both Controlled Endpoints

**By:** Parker  
**Date:** 2026-10-08  
**Status:** Implemented

- Single `endpoint_image_tag` variable covers policy API and test receiver
- Both endpoints built from one `services/Dockerfile` in one CI run
- Prevents drift between endpoint versions
- Moved from CLI (`az containerapp update --image`) to Terraform (`endpoint_image_tag` variable)
- Empty default means "run placeholder"; set to `latest` or digest for controlled endpoints

### Missing Evidence is Inconclusive, Never Pass

**By:** Dallas  
**Date:** 2026-10-08  
**Status:** Implemented

- Four outcomes for "zero receipts for our run id":
  - Rows with `demo_run_id`: **FAIL** (call not blocked)
  - Rows without marker: **INCONCLUSIVE** (unattributed arrival hides real one)
  - No rows, retrievability proven in same window: **PASS** (receipt leg only)
  - No rows, retrievability unproven or query failed: **INCONCLUSIVE**
- Unattributed arrival outranks a healthy pipeline
- An unattributable row is not proof of containment
- Exit codes: `0` pass, `1` fail, `2` inconclusive + not_implemented

### Init-Container Contract (Parker + Brett)

**By:** Parker, Brett  
**Date:** 2026-10-08  
**Status:** Implemented

- Pod runs same digest-pinned agent image with entrypoint override
- Command: `["/opt/deploy-venv/bin/python", "-m", "containment_demo.deploy"]`
- No `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_FEDERATED_TOKEN_FILE` hardcoded (workload-identity webhook injects them)
- All config via `DEMO_*` environment variables from Terraform
- `main()` guarded under `if __name__ == "__main__"`
- Module path stored in `var.agent_deploy_module` for portability
- Idempotent; every pod restart runs it again

### Kubernetes Cluster in Separate Terraform Root

**By:** Parker  
**Date:** 2026-10-08  
**Status:** Implemented

- `infra/k8s/` has own local state, reads `infra/cloud` via `terraform_remote_state`
- Keeps plan readable on empty subscription (cluster endpoint/CA unknown on clean state)
- Apply order: `cloud:up` → `build:agent` → `cloud:harness-up`
- Both modules validate with `lint:terraform`

### No Test Receiver Authentication (Hard Gate on Attribution)

**By:** Dallas, Parker  
**Date:** 2026-10-08  
**Status:** Policy (not yet built)

- Test receiver POST must accept requests with no credentials
- If authentication (401/403/407) ever added, demo design changes
- A 403 from inside sandbox becomes unattributable to egress policy
- Parker must notify Dallas/Ripley before any auth layer is added

### Never Probe Endpoints Without Run Marker

**By:** Dallas  
**Date:** 2026-10-08  
**Status:** Implemented

- All probe traffic includes `X-Demo-Run-Id` header or query param
- Baseline unmarked POST plants unattributable receipt, manufacturing ambiguity
- Marker is not a credential; it is the experiment's traceability

### Bound Log Queries with Explicit (Start, End)

**By:** Dallas  
**Date:** 2026-10-08  
**Status:** Implemented

- Never use "last N minutes" relative windows
- Padded windows reach back before run started, contaminating results
- Explicit bounds (start_time, end_time) required for all telemetry queries
- Measured ingestion lag ~1.5s; use in-payload `received_at`, not `TimeGenerated`

### Demo Runs Must Be Strictly Serial (Procedural Control)

**By:** Lambert, Ripley  
**Date:** 2026-10-08  
**Status:** Policy (enforced by runbook)

- One run id at a time; no concurrent demo execution
- Start/end timestamps recorded for each run
- Substitutes process control for missing technical join (Layer 1 ↔ Layer 2 correlation)
- Platform egress decision record not documented to carry run id

### First Post-Deploy Action: Run Q6 (OperationId Propagation Test)

**By:** Lambert  
**Date:** 2026-10-08  
**Status:** Pending (after first hosted run)

- Test whether generic App Insights OperationId propagation closes Layer 1 ↔ Layer 2 correlation gap
- Run before building anything else
- If it closes gap: Layer 2 join works for free; if not, serial-run procedural control remains in place

### GATE 0: OperationId Propagation Test (Layer 1↔2 Correlation)

**By:** Ripley  
**Date:** 2026-10-08  
**Status:** Pending (blocks all verification phases)

- `demo_run_id` is verified to reach Layer 3 (test-receiver receipts) via HTTP header
- `demo_run_id` is verified **not documented** to reach Layer 2 (platform egress decisions)
- Marker travels in HTTP header; platform not documented to copy it into decision records
- Lambert's Q6 (OperationId propagation test) runs FIRST on first hosted run, before any other build
- **Branch decided in advance:**
  - If Q6 returns `joined == true`: Layer 2 join works; proceed with Phases 5–7 as written
  - If Q6 returns `joined == false`: evidence model needs rework; claim weaker "three consistent observations in one window", never "three rows joined on shared key"; use procedural control (serial runs with explicit timestamps) as fallback
- Fallback (hostname + window + version) is coincidence argument, not join; strict serial runs substitute for missing technical correlation

### Phase 4 Blockers (Critical Path)

**By:** Ripley, Parker, Brett  
**Date:** 2026-10-08  
**Status:** Three blockers, each with unblock criteria

1. **Init-container interpreter mismatch.** `infra/k8s/harness.tf` runs `["python", "-m", ...]` but Dockerfile installs `azure-ai-projects` only into `/opt/deploy-venv`. Should run `["/opt/deploy-venv/bin/python", "-m", ...]`. Parker to fix. Blocks first hosted deploy.

2. **Server-side digest acceptance unverified.** Client-side validation passes; service acceptance unknown. `deploy.py` raising `DigestRejectedError` with no tag fallback is correct (prevents control-variable drift). Unblocked by first in-VNet deploy; record exact error in compatibility.md B9a.

3. **RBAC on `agents/versions` write assumed, not verified.** No primary source names the required role. Role `Cognitive Services User` wildcard `Microsoft.CognitiveServices/*` presumed to cover `agents/versions` write; assumption unverified. If init container gets 403, suspect this before federated credential.

### Deployment SDK Shape Correction

**By:** Ripley, Brett  
**Date:** 2026-10-08  
**Status:** Implemented in PLAN.md; code follows

- Azure CLI **cannot** attach RAI policy, so it cannot deploy either side of this single-variable experiment
- Deployment is `azure-ai-projects` 2.8.0 SDK from inside VNet (data plane rejects public access)
- Image location: `definition.container_configuration.image`, not flat `definition.image`
- Protocols field: `protocol_versions`, not `container_protocol_versions`
- No container start operation; readiness polled via `get_version(...).status`
- API version defaults to `"v1"` with separate `allow_preview` flag, not a date string

### Receipt Absence Classification (Mandatory Companion Query)

**By:** Ripley, Dallas  
**Date:** 2026-10-08  
**Status:** Implemented; Q2 paired with Q2a

- Live unattributed receipt observed: `demo_run_id == ""` in `test-receiver` logs
- "Zero receipts for our run id" is not "nothing arrived"; two cases now separate
- Q2a (unattributed arrivals) is mandatory companion to Q2
- Four outcomes for absence: (1) rows with marker = FAIL, (2) rows unattributed = INCONCLUSIVE, (3) no rows + proven retrievability in window = PASS (receipt leg only), (4) no rows + unproven retrievability = INCONCLUSIVE

### Blocker 3: Implicit Allow Rule Test

**By:** Ripley  
**Date:** 2026-10-08  
**Status:** Added to Phase 6

- Risk: undocumented implicit allow is carrying the positive result
- Test: remove explicit allow rule for permitted destination and confirm it is then denied
- If still succeeds, the positive half of the demo proves nothing
- Phase 6 exit criterion: either this test passes or the implicit allow is documented

### Phase Status Labeling and Honest Assessment

**By:** Ripley  
**Date:** 2026-10-08  
**Status:** Implemented in PLAN.md

- Every phase carries **done / partial / not started / blocked** status
- Every claim inside phase is labeled **tested result**, **proposed behaviour**, or **preview capability**
- Specific downgrades:
  - Phase 5 §B and §C: stubs returning `not_implemented`; cannot return pass
  - Phase 6: `tests/integration` is empty (unwritten, not unrun)
  - Phase 7: `demo-runbook.md` and `evidence-template.md` do not exist
  - Phase 3: App Insights connection authored in Terraform; read-back is open (authoring is not evidence)
  - Telemetry §2.1: stays blank until real row observed (no guessed platform column names)
  - Phase 4: `assert_single_variable` must verify read-back definitions, not intent

### Phases 8 and 9 Gated on Phase 5 §C and A2A Spike

**By:** Ripley, Brett  
**Date:** 2026-10-08  
**Status:** Policy

- Phase 8 does not begin before Phase 5 §C produces a result
- Phase 9 (A2A on hosted container agents) remains blocked on A2A spike (Blocker 5)
- Responses fallback is pre-agreed and costs nothing (harness transport method has no bearing on what agent tools can reach)

## Known Risks / Unverified Assumptions

### Server-Side Digest Acceptance
- Azure SDK accepts digest client-side; service-side behavior unknown
- First hosted run will answer this
- See `docs/compatibility.md` B9a

### RBAC on `agents/versions` Write
- `Cognitive Services User` role's `Microsoft.CognitiveServices/*` wildcard presumed to cover `agents/versions` write
- No primary source names the required role for creating an agent version
- `agents/versions` not separately registered; assuming it falls under `agents/write`
- If init container gets 403, suspect this before federated credential

### Layer 1 ↔ Layer 2 Correlation
- Our run id travels in HTTP header/query param; platform not documented to copy it
- Fallback: run window + destination hostname + agent version
- Breaks under concurrency; depends on unmeasured Foundry-side clock lag
- Current column (host property key) unverified in platform egress decision records

### App Insights Connection Proof
- Connection now exists; proves path exists, not that records land
- Keep "no egress record" inconclusive until real row observed in first run

## Governance

- All meaningful architectural decisions documented here
- Team consensus required before deviating from these decisions
- History (agent.md files) tracks work; decisions track direction
- Open risks and unverified assumptions listed explicitly
