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
