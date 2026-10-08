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

### Init-Container Interpreter: Absolute Path in Variable (Parker)

**By:** Parker  
**Date:** 2026-10-08  
**Status:** Implemented (Commit b3c60a3)

- `infra/k8s/harness.tf` init container runs `[var.agent_deploy_interpreter, "-m", var.agent_deploy_module]`
- Default: `/opt/deploy-venv/bin/python`
- Validated to be an absolute path (not PATH-resolved)
- Rationale: Dockerfile installs deploy stack only in `/opt/deploy-venv`; bare `python` would be system interpreter (no module)
- **Absolute path is deliberate,** not PATH ordering. PATH-based resolution would make the pod silently sensitive to any future `ENV PATH` edit in the Dockerfile, making that failure indistinguishable from a missing dependency
- **Team caveat:** No mechanical tie between decisions.md, Dockerfile, and Terraform variables. Drift is caught only by reading or by apply. If deploy module path, interpreter path, or venv path moves, all three must move together.

### No Plan-Time-Varying Functions in Resource Attributes (Parker)

**By:** Parker  
**Date:** 2026-10-08  
**Status:** Implemented (Commit 64371ae)

- Removed `DeployedOn = timestamp()` from `infra/cloud/locals.tf` and `infra/spike/locals.tf`
- Plan-time-varying functions mark tag map unknown on every plan, causing all tagged resources to be marked for in-place update
- Live impact: clean plan became 24 changes, 22 of them tag-only churn
- Nothing consumed `DeployedOn`; `Application` and `AppName` tags remain (both consumed by tasks)
- **Team-relevant rule:** Plan cleanliness is how we demonstrate RAI policy is the **only** variable between Audit and Enforced runs. `No changes. Your infrastructure matches configuration.` between the two is the control.
  - No `timestamp()`, `uuid()`, or `bcrypt()` in any attribute of a persistent resource
  - A non-empty plan on an unchanged configuration is a defect to be fixed, not noise to be scrolled past
  - Anyone seeing one should say so
- Recorded as `docs/compatibility.md` §C6

### NOT COLLECTED is a First-Class Evidence State; Observation Window is a Fixed Constant (Dallas)

**By:** Dallas  
**Date:** 2026-10-08  
**Status:** Implemented (Commits 1450235, c3bc181)

**Three team-relevant rules now embedded in Phase 7 deliverables:**

1. **Every signal has three states; the third is not soft absent**
   - Each signal — client failure (classified by kind), platform egress decision record, receipt absence — recorded as **present**, **absent**, or **NOT COLLECTED**
   - **NOT COLLECTED forces overall verdict to inconclusive.** A signal nobody looked for is not evidence of anything
   - Collapse of absent/not-collected is how a run with two signals becomes a pass

2. **Observation window is a stated constant, owned by runbook**
   ```
   W_start = T0             (UTC, immediately before first tool trigger)
   W_end   = T_end + 120 s  (UTC, immediately after last tool result)
   ```
   - Explicit `(W_start, W_end)` pair on every query, never relative `ago(Nm)`
   - Use in-payload `received_at`, never `TimeGenerated`, for ordering
   - 120 s tail is ingestion headroom (~1.5 s measured lag), not late-arriving good news
   - **Changing the constant requires recording the change and reason in evidence template**
   - Window closes once; longer look is a new run id

3. **"What this run did NOT prove" is mandatory section with named rows**
   - Evidence template §8 lists specific claims and requires each answered: Blocker 3 (positive may ride undocumented implicit allow), Blocker 1 stage 2 (managed-VNet attribution), server-side digest acceptance, authoring ≠ enforcement, private endpoint direction, protocols beyond HTTP/HTTPS, ungoverned harness, preview status, prompt injection
   - Template with blank §8 is not completed; reviewers send it back

**Why this matters:**
- **Ripley:** Runbook assumes `joined == false` (Layer 1↔2 correlation missing) until Q6 answers otherwise; carries weaker "three consistent observations in one bounded window" claim
- **Lambert:** Runbook names no platform property or table not verified in `telemetry-map.md`; §2.1 blank is documented gap, not hole to paper over
- **Parker:** Two pre-flight checks are now gates on interpreting denial, not health pings. A5 (receiver accepts unauthenticated POST) and P7 (App Insights `authType == ApiKey`); either failure makes denial unattributable
- **Brett:** Deterministic diagnostic route is documented trigger; model refusal proves nothing
- **Everyone:** Local runs and hosted runs never share verdict; run class filled in before execution; strict-serial rule labeled as procedural stand-in (enforced by operator reading, nothing else)

### Cluster Context Is a Pre-Flight Gate, Not an Assumption

**By:** Dallas (found by Brian)  
**Date:** 2026-10-08  
**Status:** Implemented in `docs/demo-runbook.md` §3.0 and `docs/evidence-template.md` §3

- No one applies anything to the cluster until three checks pass, in this order:
  P0a `kubelogin` on `PATH`, P0b `task cloud:kubeconfig`, P0c active context string-matches `terraform -chdir=infra/cloud output -raw aks_cluster_name`, confirmed live with `kubectl cluster-info` naming the cluster and **canadacentral**.
- Observed failure when P0b was skipped: `Unable to connect to the server: remote error: tls: unrecognized name` against a dead AKS FQDN from an unrelated project (`model-osprey-…swedencentral`). That message means **wrong/dead kubeconfig context**. It is not auth, not network policy, not our cluster.
- `kubelogin` is mandatory: the cluster has local accounts disabled with Entra RBAC, so there is no admin kubeconfig fallback. A missing binary looks like an auth failure.
- Rationale for checking *before* the apply rather than reading the error after: a dead wrong cluster fails loudly, a **live** wrong cluster would accept the apply.
- A step that exists only in a Taskfile is not a procedure. If an operator must run it, the runbook names it.

### A Harness Dry Run Is Not Containment Evidence

**By:** Dallas  
**Date:** 2026-10-08  
**Status:** Implemented (evidence template §8 mandatory row)

- `task cloud:harness-plan` is a **server-side dry run**. It establishes that the API server would accept the apply. It does **not** establish which fields are about to change, and it establishes **nothing** about egress — it is a statement about a Kubernetes API server in a cluster the Foundry egress policy does not govern.
- It is deliberately not `kubectl diff`: a diff of the rendered stream prints the Secret's contents into any captured demo log.
- Related mechanics now documented: `infra/k8s/` is deleted; manifests live in `deploy/kustomize/base/` with committed `REPLACE_WITH_*` placeholders, substituted only inside the apply pipe, never on disk. Every apply uses `--server-side --force-conflicts` to adopt Terraform-owned objects, so the **first apply reports `configured`, not `created`**, and the workload keeps running.

### Kubernetes workloads move from terraform to kubectl + kustomize

**By:** Brian (call), Parker (implementation), Coordinator (review fixes)  
**Date:** 2026-10-08  
**Status:** Implemented — supersedes "Kubernetes Cluster in Separate Terraform Root"

- `infra/k8s` is DELETED, state file included. `hashicorp/kubernetes` 2.38.0 tainted `kubernetes_deployment_v1.harness` with a null `identity` after a rollout-wait failure, and every later refresh failed with `Unexpected Identity Change`.
- Manifests now live in `deploy/kustomize/base/` (namespace, serviceaccount, secret, deployment, kustomization) with committed `REPLACE_WITH_*` placeholders.
- Task names are UNCHANGED — `cloud:harness-plan`, `cloud:harness-up`, `cloud:harness-status`, `cloud:harness-down` — so `docs/demo-runbook.md` and `docs/evidence-template.md` need no edits. `harness-init` and `harness-validate` are gone; nothing referenced them.
- Apply order is unchanged: `cloud:up` → `build:agent` → `cloud:kubeconfig` → `cloud:harness-up`.
- **Adoption:** the first `harness-up` runs against objects terraform created. It uses `--server-side --force-conflicts`, which moves field ownership from the `Terraform` field manager to `kubectl`. The objects keep running; expect `configured`, not `created`.
- **Secrets never touch disk.** The diagnostics token and App Insights connection string are placeholders in git and exist only inside the apply pipe. `.gitignore` blocks rendered manifests and kubeconfigs.
- **Technical context:** Coordinator found two defects in the migration: (a) placeholder guard ran on unsubstituted source after apply (commit f533ea8), (b) hardcoded fallback image digest risked control-variable drift; resolve live from ACR instead (commit b52d58c). The second defect also identified the fourth instance of the az auto-upgrade chatter bug.
- **Forward scope rule — this is the durable part.** Cluster workloads do **not** go back into Terraform. Terraform owns Azure resources; `kubectl` + `kustomize` own anything with a `kind:`. This binds work not yet written: Phase 8's Dapr components and workflow app, and Phase 9's `samples/onprem_harness/`, are kustomize overlays. The earlier plan called for `infra/aks/` and `infra/dapr/` Terraform roots — those are void. A future phase proposing a `kubernetes_*` resource is re-opening a settled decision and needs Brian, not an agent.

### Every `az` Read Routes Through `tasks/Taskfile.arm.yml` (Azure CLI Output Parsing Bug)

**By:** Coordinator  
**Date:** 2026-10-08  
**Status:** Policy — enforce on all future `az` calls

- The Azure CLI outputs tool upgrade notices to stdout, making simple `az … | xargs` or `az … -o tsv` pipelines fragile.
- Example: `az acr show --query ".* loginServer"` returned `"WARNING: defaulting to X for ..." + value`, breaking digest resolution.
- Fourth instance of this bug class found in recent work:
  1. Taskfile arm:account-lookup: `az account show -o tsv`
  2. Taskfile arm:foundry-account: `az provider show -o tsv`
  3. Taskfile build:agent-digest: `az acr repository show -o tsv`
  4. Coordinator defect B review: `az acr …` capturing chatter into deploy digest variable
- **Fix:** Encapsulate all `az` reads in `tasks/Taskfile.arm.yml` with filtering (grep/jq/sed). Callers invoke the task, never the CLI directly. Proven patterns keep this class of defect local to one file.
- **Enforcement:** `scripts/check_no_az.sh` must reject raw `az` commands in all Taskfiles except `tasks/Taskfile.arm.yml`.

### Verify Status Vocabularies Against Running Service, Not SDK Enums

**By:** Brett  
**Date:** 2026-10-08  
**Status:** Implemented

- **The lesson:** A client library's enum is the SDK's *claim* about the service, not the service's contract. It can be stale, partial, or generated from a different API version.
- `AgentVersionStatus` in `azure-ai-projects` declares: creating / active / failed / deleting / deleted. The live service also returns `running`, and Brian's production deployer (primary reference: `briandenicola/banking-agent-foundry-orchestrator`) confirms `starting` and `updating`.
- **What happened:** A hosted agent version was created and provisioned (portal showed `Status: Running` in under a minute), but `wait_until_active` polled for 45+ minutes and never terminated. Two bugs made polling invisible:
  1. `_TERMINAL_OK = "active"` was incomplete. Service said `running`, which was in no status set.
  2. `str(status).lower()` on an enum mixin produced `'agentversionstatus.active'` — polling could not terminate on success even if the service said `active`.
  3. The poll loop logged **nothing**. Healthy and hung deployments emitted byte-identical output.
- **Decisions (all implemented):**
  1. Status sets cited inline with sources: `_READY_STATUSES = {"active", "running"}`, etc. No uncited strings.
  2. Loop bounded by iteration count `for attempt in range(1, attempts + 1)`, not `while True` with a deadline. A bounded loop cannot fail to terminate.
  3. Every poll logs: agent name, version, verbatim status, attempt `n/N`, elapsed seconds, flushed immediately.
  4. Unrecognised status: WARNING on every sighting, then `UnrecognisedStatusError` at bound. Never silently succeed, never pending forever.
  5. Timeouts remain FAILURE, never optimistic pass. Budget 120s (was 900s; 4x headroom after sub-60s observed provisioning), poll 3s, request timeout 15s, retry 2.
  6. SDK HTTP logging downgraded to WARNING (was burying the signal).
- **Constraints unchanged:** Two business tools, RAI policy handling, digest pinning untouched.
- **Primary reference:** `briandenicola/banking-agent-foundry-orchestrator` must be consulted before deriving behaviour from SDK type definitions.

### Foundry's System-Assigned Identity Needs AcrPull on the Agent Registry

**By:** Parker  
**Date:** 2026-10-08  
**Status:** ⚠️ **DISPROVEN — superseded 2026-10-08 19:35Z. The reasoning below is wrong.**

> **DO NOT USE THE DEBUGGING HEURISTIC IN THIS ENTRY.** It is the exact false lead that
> cost a day. Preserved unedited because this ledger is append-only and because the
> mistake is more instructive than its removal would be.
>
> **What actually happened.** The role assignment was applied *after* the agent was
> already healthy, and fixed nothing. `containment-demo-audit` reached `active` at
> 18:39:26Z with **no** Foundry AcrPull role in place — so the platform could already
> pull, and `registry_connection_id=None` was correct all along.
>
> **The real defect** was one line in `deploy.py`: `str(AgentVersionStatus.ACTIVE).lower()`
> yields `'agentversionstatus.active'`, which can never equal `'active'`. The poller could
> not terminate on success under *any* status vocabulary or *any* set of permissions.
> After the fix, both versions were created and matched on attempt 1/40 at elapsed 0.0s.
>
> **Specifically false:** "accepted, then hangs in `creating`" does **not** indicate a
> missing pull permission. The version was never in `creating` — it was `active` within
> seconds, and our poller simply could not say so. The hypothesis was built to explain a
> **silence**, and a silent poll loop makes a healthy system and a hung one byte-identical.
>
> **The rule this violated**, which this repository already states and which applies to
> debugging the demo and not only to the demo's findings: *missing evidence is
> INCONCLUSIVE, never a signal.* Demand the observed value before constructing a theory.
>
> The role assignment itself is retained: harmless, registry-scoped, defensible on
> least-privilege grounds — but **unproven-necessary**, and the reference implementation
> grants AcrPull to the *project's* identity rather than the account's, so it does not
> corroborate this entry either. See `docs/compatibility.md` B9b (DISPROVEN block) and B9d.

- The Foundry account's `SystemAssigned` principal had no role on ACR. `acr.tf` granted `AcrPull` only to AKS kubelet and Container Apps identities.
- Hosted-agent runtime pulls the agent image as its own principal (distinct from kubelet). Without `AcrPull`, a pull is retryable rather than fatal, and the version hangs in `creating`.
- Added `azurerm_role_assignment.foundry_acr_pull`: `AcrPull`, scoped to the registry, principal `azapi_resource.foundry.output.identity.principalId`.
- **This is a hypothesis, not proof.** It fits the symptom (version accepted, then stuck in `creating`), but the data plane is private-endpoint-only and backend pull errors are unreadable from outside. The grant is necessary regardless of sufficiency.
- **Failure mode (for debugging):** "accepted, then hangs in `creating`" = missing pull permission. Check this role before re-debugging provisioning time.
- **For Brett:** `find_matching_version` does not skip `creating`, so a stuck version is reused by the next run. Once the role is granted, a stuck version should recover; deletion requires a data-plane call from inside the VNet (no SDK surface in B9a).

### GATE 0 Verdict: Inconclusive (Correlation Unresolved, Verified Prerequisites Met)

**By:** Lambert  
**Date:** 2026-10-08  
**Status:** Policy (Q0 closes this gate; first invocation required)

- **Does `demo_run_id` reach platform egress decisions? UNANSWERABLE TODAY.**
  - Sink exists: YES (verified, `humble-phoenix-46689-ai` App Insights connection, ApiKey auth, created 2026-10-08T17:29:49Z)
  - Receiving rows: NO (zero in 7 days across Traces, Requests, Dependencies, Exceptions, Events)
  - Joinable field: UNKNOWN (zero rows means zero observed fields to join on)
- **Verdict: INCONCLUSIVE, not FAIL.** No invocation has happened yet; platform had no opportunity to emit a decision. Gate closes with one real invocation and `docs/telemetry-map.md` §4 **Q0**.
- **For Dallas — run id placement:** `get_servicing_policy` sends `demo_run_id` as URL query param **and** header; `send_to_external_processor` sends header **only**. Primary doc: decision record Destination is "method and URL". If platform logs URL not headers, we correlate allowed call only, missing the denied half. Fix: add `demo_run_id` to query string on `send_to_external_processor` if Q0c shows URL-logged / header-ignored pattern.
- **For Brian — watch items:**
  1. `ManagedNetworkEvent` category exists on Foundry account but **zero rows ever**. **Status: NOT VERIFIED** to carry RAI egress decisions. Do not enable it. Revisit only if Q0a empty after confirmed invocation.
  2. App Insights connection carries non-null `error`: *"Connection subresourceTarget is not supported for PE creation"*. Probably benign (telemetry egresses outbound from sandbox). NOT VERIFIED. If Q0 empty after invocation, investigate this first.
- **Corrected:** Policy attachment **IS confirmed** (not unverified). `verify_version()` in-cluster readback confirms policy field set to expected ARM id on both versions with same digest. Init containers exited 0 at 19:35Z. Readback confirms *acceptance*, not *runtime enforcement* — which is why Q0 and Layer-2 evidence exist. `docs/telemetry-map.md` §0.5 and §7 corrected; `docs/compatibility.md` C1 needs update (ManagedNetworkEvent category does exist, even if never populated).

### No Variable Default May Encode Current-Environment State

**By:** Parker  
**Date:** 2026-10-08  
**Status:** Implemented

- `infra/cloud/variables.tf` defaulted `region = "eastus2"` while environment runs in `canadacentral`. Bare `terraform -chdir=./infra/cloud plan` with no `-var region=` produced `38 to add, 0 to change, 37 to destroy` — resource group, Foundry account, **both RAI policies**, registry, cluster all marked for replacement.
- **The danger:** Resource names derive from region; wrong region replaces the environment rather than drifting it. The plan output reads as a legitimate first-time deploy, making it subtle rather than obviously catastrophic.
- **Fixed:** Removed default outright. `region` is now required and fails with "No value for required variable" before refresh. `task cloud:plan` unchanged; bare plan now errors.
- **The rule:** No variable may carry a default that encodes current-environment state. A default is a claim that the value is a safe fallback; for anything participating in resource identity there is no safe fallback, only a quiet one. Sibling of decision C6 (no plan-time-varying functions).
- **Sibling survives untouched:** `infra/spike` still defaults to `eastus2` because it has no state file, so a bare plan has nothing to destroy. Spike is disposable by design; remove the default only if it gains persistent state.
- **Role survey (recorded, not applied):** Brian's reference deployer (`briandenicola/banking-agent-foundry-orchestrator`, fetched 2026-10-08) compared in `docs/compatibility.md` B9d. Likely needs `Foundry Agent Consumer` scoped to project (for Dallas's invocation path); add with that work, not speculatively. `AcrPull` on project identity vs. our account identity noted; ours kept (harmless, least-privilege, registry-scoped, proven-working) but unproven-necessary.

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
