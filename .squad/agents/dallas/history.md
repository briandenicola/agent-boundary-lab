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

### 2026-10-08 — PLAN re-gate: Sections B and C stubs cannot return pass (Dallas action)

Ripley re-gated the plan against verified facts. Sections B and C are stubs returning
`not_implemented` (exit 2). They cannot return a pass and should not pretend to. They remain blocked
on Phase 4 completion. Sections B and C implementation is pending no agent version yet.

- `scripts/verify_demo.py` exists and Section A is real. B and C are stubs that return
  `not_implemented`; they can never return a pass. Exit codes: 0 pass, 1 fail, 2
  inconclusive/not-implemented.
- Endpoints resolve from `DEMO_POLICY_API_URL` / `DEMO_TEST_RECEIVER_URL` first, then
  `terraform -chdir=infra/cloud output -raw policy_api_url|test_receiver_url`. No address
  is written into the script. Unresolvable endpoints are **inconclusive**, not a failure —
  nothing was attempted, so nothing is known.
- Section A roll-up is split in two on purpose: **endpoint transport baseline** (A1–A5)
  can pass; **receipt-log retrievability** (A6) is inconclusive until the Container Apps
  console-log query is confirmed in `docs/telemetry-map.md`. Inventing a table name to
  make it green is forbidden, so Section A overall stays INCONCLUSIVE today. That is the
  honest state, not a bug.
- A5 is the check the Enforced run depends on: the receiver is POSTed to with **no
  credentials and no marker**. It answers 202. A destination that answered 401/403/407 on
  its own would make a later in-sandbox 403 unattributable (`docs/egress-control.md` §6),
  so A5 fails the baseline in that case. The verdict lives in `judge_own_rejection()` so it
  can be exercised directly — the live endpoint cannot be made to return its own 403.
- Observed live on 2026-10-08: both Container Apps healthy, policy API echoes the run
  marker on `/policy` (200), receiver acknowledges on `/ingest` (202).
- Failure-kind classification was observed working, not assumed: timeout (`--timeout
  0.002`), connection_error (`https://127.0.0.1:9`), tls_error (a `.invalid` host that the
  local resolver wildcards — DNS genuinely resolved, so "tls" was the correct call, and
  this is a reminder that a DNS-failure test cannot be written against a wildcard
  resolver), http_error (status >= 400).
- `task verify:baseline`, `task verify:baseline-json`, `task verify:all` added. `evidence/`
  is gitignored.
- `tests/unit/test_agent.py`: both tools registered in every `PolicyMode` and with
  `FOUNDRY_AGENT_*` set, zero-argument signatures, wrappers actually delegate to
  `tools.*`, no URL literal (only the Entra token scope), no policy-mode branch, no
  prompt-level refusal in the instruction.
- `tests/unit/test_dependency_overrides.py`: Blocker 0 is "pip cannot install this
  project". The guard is four-part — override declared for **both** otel distributions,
  installed version actually above ADK's declared ceiling (proof the override applied),
  the upstream conflict still exists (so the override gets deleted when it stops being
  needed rather than becoming folklore), and the overridden stack imports and constructs.
- `LlmAgent` rejects an arbitrary stub model (pydantic validation). Use
  `LiteLlm(model="azure/...")` — it constructs with no credential and no network call.
- Tamper-tested, each observed failing then reverted: conditional registration by mode,
  a URL argument added to a tool, a hardcoded destination literal, a prompt-level refusal,
  a wrapper bypassing the real tool implementation, the uv override block deleted, the
  sdk half of the override dropped, the override floor lowered to ADK's ceiling, a
  simulated pip-built environment at otel 1.42.1, and a simulated upstream relaxation.
- 136 unit tests pass with no network, no Azure, no credentials.

### 2026-10-08 — A6 wired to the verified receipt table; Section A reaches PASS

- `task verify:baseline` now reports **Section A: PASS** against the live endpoints and
  real rows in `ContainerAppConsoleLogs_CL`. Exit 0.
- A6 is a **positive control**, not a liveness ping: it polls for the receipts that A3/A4
  just caused, and requires rows from *both* services for *this* run id. That is what
  licenses a later absence claim in the same window. Query, columns and `parse_json(Log_s)`
  come from Lambert's verified §3.2 / Q1 — nothing invented.
- A7 runs Q2a (unattributed arrivals). It is mandatory, not decorative: Lambert observed a
  live receipt with `demo_run_id == ""`.
- **I was generating that defect myself.** A5 POSTed to the receiver with no marker to
  prove "no credentials required", and every run therefore planted an unattributable
  receipt. Fixed: A5 sends no credential but does carry the marker. A credential is the
  thing under test; the marker is not a credential.
- **The log window must be an explicit (start, end) pair.** A relative "last N minutes"
  window with a safety pad reached back past the start of the run, and a *previous* run's
  markerless probe answered this run's question. Caught only because A7 stayed red after
  the A5 fix. Padding a window is not conservatism, it is contamination.
- `classify_receipt_absence()` keeps four cases apart: arrived-for-this-run (FAIL, it was
  not blocked), arrived-unattributed (INCONCLUSIVE), no-rows-in-window (PASS **only** with
  proven same-window retrievability, otherwise INCONCLUSIVE), query-unavailable
  (INCONCLUSIVE). An unattributed arrival outranks a healthy pipeline.
- A failed query and an empty result set are different facts and are kept apart by a
  reason string. Collapsing them would make every "no receipt" inherit every outage.
- Log reads use `azure-monitor-query` + `DefaultAzureCredential` (new `verify` extra). No
  az CLI. Run ids are validated against `^[A-Za-z0-9._:-]{1,128}$` before interpolation.
- Ingestion lag measured ~1.5 s but polled up to `--receipt-wait` (default 180 s). A miss
  inside the window is inconclusive: a late receipt and a dead pipeline look identical at
  the moment of asking.
- New tamper tests, each observed failing then reverted: unattributed arrival collapsed
  into no-rows; passing without proven retrievability; unavailable query treated as a
  pass; query exception reported as `ok`; wrong table name against the live workspace
  (A6 and A7 both went inconclusive, neither passed); and a live markerless POST landed
  mid-run, which correctly drove the run to INCONCLUSIVE.
- `tests/unit/test_verify_harness.py` (28 tests) institutionalises all of it. Suite is 164
  passing, still no network/Azure/credentials.

### 2026-10-08 — Section A now PASS, receipt absence classification finalized

- **Section A overall status: PASS** (exit 0, via `task verify:baseline`). Transport baseline (A1–A5) and receipt retrievability (A6) both working.
- **Receipt absence is four outcomes, not two.** Implemented in `classify_receipt_absence()`. Must be called by Section C before deriving logic again:
  - Rows with `demo_run_id`: **FAIL** (call was not blocked)
  - Rows present, none with marker: **INCONCLUSIVE** (unattributed arrival could be ours)
  - No rows, retrievability proven in same window: **PASS** (receipt leg only)
  - No rows, retrievability unproven or query failed: **INCONCLUSIVE**
- **A5 is a hard gate on attribution.** Test receiver POST with no credentials must answer 2xx. Parker: do not add authentication or IP restrictions. A 403 from inside sandbox stops being attributable to egress policy. Demo design changes if this ever happens.
- **Never probe without run marker.** Unmarked probe plants unattributable receipt on every run, manufacturing the ambiguity A7 detects. Marker is traceability, not credential.
- **Explicit (start_time, end_time) on every log query.** Relative windows contaminate. Previous run's traffic can answer this run's question. Use in-payload `received_at`, not `TimeGenerated`.
- **`task verify:baseline` is pre-demo gate.** Run before any demo run, never after failure. Endpoint state is experiment variable; a dead endpoint makes denial unattributable.
- Blocker 0 (guard against `google-adk` OpenTelemetry pin relaxation): `test_dependency_overrides.py` fails on purpose if pin relaxes. Operator must delete `[tool.uv]` override and update compatibility.md.
- Sections B and C remain NOT IMPLEMENTED (exit 2, cannot return pass). B requires hosted agent version; C requires platform decision record path.

### 2026-10-08 — Phase 7 docs: demo runbook and evidence template written

`docs/demo-runbook.md` and `docs/evidence-template.md` now exist. Documentation only; no
Azure, no applies. `task lint:all` green (164 passed, 1 skipped).

- **The runbook leads with what is executable today**, because a runbook that reads as if
  the hosted sections work is itself a false pass. Pre-flight and Section A run; Sections B
  and C are stubs returning `not_implemented` and cannot return a pass; the hosted verdict
  available right now is **inconclusive — not collected**.
- **GATE 0 is honoured, not worked around.** The runbook forbids joining a platform egress
  decision on `demo_run_id`, names no platform property key or table absent from
  `docs/telemetry-map.md` (§2.1 is blank and stays blank), and carries the weaker sentence —
  *"three consistent observations in one bounded window, not three rows joined on a shared
  key"* — until Q6 is answered. The `joined == true` branch is written in advance so nobody
  gets to decide the wording after seeing the number.
- **The observation window is a stated constant, not an improvisation.** `W_start = T0`,
  `W_end = T_end + 120 s`, explicit pair on every query, order by `received_at`. The 120 s
  tail is ingestion headroom over the one lag we measured (≈1.5 s), not a search for late
  good news. Changing it requires recording why. The window closes once; a longer look is a
  new run id.
- **Two pre-flight checks are gates on interpretation, not health pings**, and the runbook
  says which: A4 (negative endpoint genuinely reachable from a control client) and A6
  (receipt logging demonstrably working in the same window). Without A4 a denial proves
  nothing; without A6 an absence proves nothing. A5 and P7 join them as hard gates — a
  self-authorizing receiver or a missing App Insights connection makes a denial
  unattributable before it happens.
- **The serial-run rule is labelled procedural in the runbook text itself.** It is enforced
  by the operator reading one sentence and by nothing else. Saying so is the point; a
  procedural control presented as a technical one is the same error as a 403 presented as
  enforcement.
- **The evidence template's third state is NOT COLLECTED, and it is load-bearing.** Each of
  the three signals is present / absent / NOT COLLECTED, and NOT COLLECTED forces
  inconclusive. A signal nobody looked for is not a soft absent.
- **"What this run did NOT prove" is mandatory with named rows**, not a free-text
  afterthought: Blocker 3 (the positive leg may ride an undocumented implicit allow),
  Blocker 1 stage 2 (managed-VNet attribution), server-side digest acceptance, authoring ≠
  enforcement, the private endpoint being inbound-only, and preview status. A template with
  §8 blank is not reviewable and gets sent back.
- Task names were read from `task --list-all`, not recalled: `cloud:whoami`, `cloud:output`,
  `cloud:endpoints`, `cloud:policies`, `cloud:app-insights-connection`, `cloud:caveats`,
  `cloud:harness-status`, `cloud:harness-down`, `cloud:down`, `build:check-endpoints`,
  `build:agent-digest`, `verify:baseline`, `verify:baseline-json`, `lint:all`.
- The diagnostic route is the documented trigger (`POST /internal/diagnostics/run`, bearer
  token, port 8088, optional `?tool=`), because a model declining to call a tool means
  nothing was attempted and proves nothing about the network.

### 2026-10-08 — Runbook pre-flight gains a cluster-context gate; harness deploy is kubectl + kustomize

Two corrections to `docs/demo-runbook.md` and `docs/evidence-template.md`, both found by
Brian running the real thing. Docs only, no Azure, no applies. `task lint:all` green (164
passed, 1 skipped).

- **A missing pre-flight step cost twenty minutes.** The harness deploy failed with
  `Unable to connect to the server: remote error: tls: unrecognized name` against
  `model-osprey-55220-aks-2pll9qwn.hcp.swedencentral.azmk8s.io` — a dead cluster from an
  unrelated project that was still the active kubectl context. Ours is
  `humble-phoenix-46689-aks` in canadacentral. `task cloud:kubeconfig` already existed; the
  runbook never told anyone to run it. **A step that only exists in a Taskfile is not a
  procedure.**
- **The check is a string comparison, not a hope.** New P0a/P0b/P0c: `kubelogin` on PATH,
  `task cloud:kubeconfig`, then `kubectl config current-context` string-matched against
  `terraform -chdir=infra/cloud output -raw aks_cluster_name`, plus `kubectl cluster-info`
  to confirm the control-plane URL names the cluster and the region. Verified live: both
  strings print `humble-phoenix-46689-aks`.
- **The failure signature is written down verbatim** so the next person recognises it in a
  second. It is NOT an auth failure, NOT a network policy, NOT our cluster being broken.
  And the sharper point: a *dead* wrong cluster fails loudly; a *live* wrong cluster would
  accept the apply. That is why the check runs before the apply, not after the error.
- **`kubelogin` is a hard dependency**, because the cluster has `local_account_disabled =
  true` with Entra RBAC — there is no admin kubeconfig fallback. A missing binary surfaces
  as an exec-plugin error that reads exactly like bad credentials.
- **Cluster workloads moved out of Terraform.** `infra/k8s/` is deleted;
  `deploy/kustomize/base/` holds namespace/serviceaccount/secret/deployment with committed
  `REPLACE_WITH_*` placeholders, stream-substituted at apply time from `terraform output
  -raw`. Files on disk are never mutated and the two secrets (diagnostics token, App
  Insights connection string) exist only inside the apply pipe. Runbook says so, including
  "do not redirect the rendered stream to a file to have a look at it".
- **Task names were verified, not assumed.** `task --list-all` confirms all six of
  `cloud:up`, `build:agent`, `cloud:kubeconfig`, `cloud:harness-plan`, `cloud:harness-up`,
  `cloud:harness-status` exist, and the order is right. The existing `cloud:harness-*`
  references in the runbook were already correct and did not change.
- **`cloud:harness-plan` is a server-side dry run, and the runbook states its limits.** It
  proves the API server would accept the apply; it does NOT say which fields are about to
  change. It is deliberately not `kubectl diff`, because a diff of this stream prints the
  Secret into any captured demo log. **A clean dry run is not evidence about containment**
  — new mandatory §8 row in the evidence template says so, so nobody can present it as one.
- **Expect `configured`, not `created`, on the first apply.** `--server-side
  --force-conflicts` adopts objects written by Terraform's field manager, which carry no
  `last-applied-configuration` annotation. Ownership moves to kubectl; the workload keeps
  running.
- Evidence template now records the AKS context, the control-plane URL, and where the
  harness was applied from — so a later reader can tell which cluster the run touched.

### 2026-10-08 — cluster-context pre-flight gate and kustomize harness documentation (Commit 217e5b7)

- **Orchestration log created; session log 2026-10-08T18:32:44Z-kustomize-migration.md**
- **Runbook §3.0 added:** Six-step bring-up order with three pre-flight gates that must pass before any cluster operation.
  - P0a: `kubelogin` on `PATH`
  - P0b: `task cloud:kubeconfig` (acquires credentials)
  - P0c: active context string-matches `terraform -chdir=infra/cloud output -raw aks_cluster_name`, confirmed live with `kubectl cluster-info`
- **Recorded the failure signature** for wrong/dead context: `tls: unrecognized name` means "wrong or dead kubeconfig context", **not** auth or network policy. Observed it against a dead AKS FQDN from an unrelated project. **A live wrong cluster would accept the apply,** so this check must run before applying.
- **Evidence template §8:** Added mandatory row preventing a server-side dry run from being presented as containment evidence. The dry run proves API server acceptance; it proves nothing about egress policy enforcement.
- **Kustomize mechanics documented:** placeholders, stream substitution, secrets-only-in-pipe pattern, `--server-side --force-conflicts` adoption, expect `configured` not `created` on first apply, `kubectl diff` prints secrets into logs (wrong tool).


### 2026-10-08 — The invocation primitive, and the marker that nearly only worked on the easy half

Built `src/containment_demo/invoke.py`: call a named hosted agent version, trigger both
business tools, report each outcome classified separately. Offline tests only; nothing
invoked live. Committed as `9bbb747`.

Things worth remembering:

**I did not invent the API shape, and it took reading two of our own files plus the SDK
to avoid doing so.** `deploy.py`'s `build_definition` registers
`ProtocolVersionRecord(protocol="responses", version="v1")`, and `protocol_adapter.py`
hosts `ResponsesAgentServerHost`. That maps to
`AIProjectClient.get_openai_client(agent_name=...)` → `responses.create`. The base URL
is *agent-scoped*, which matters more than it looks: `agent_name` is the only thing
selecting audit versus enforced, and there is no client-side version pin at all. The
version and digest can only be asserted from the control plane.

**There were already two vocabularies for failure kinds and I nearly wrote a third.**
`ErrorCategory` in settings.py and `FailureMode` in verify_demo.py already mirror each
other member for member. I reused `ErrorCategory` and added a test that fails if the
two ever drift. Checking first cost one grep.

**Lambert's GATE 0 finding changed the design late and was right to.** Marking a run
only with an HTTP header correlates the ALLOWED call and silently loses the DENIED one,
because egress decision records log at URL granularity and our receiver — which logs
whatever we hand it — is the only thing that would have proved the header "worked". It
would have tested perfectly and been useless for the entire point of the demo. The fix
is a query parameter on both destinations, built by one shared helper, plus keeping the
header. The asymmetry risk is the real hazard: mark one tool and not the other and you
get the same silent failure by a different route. There is now a test that compares the
two requests' parameters and headers directly.

**Tamper-testing the new guard was worth it.** I removed the marker from the POST only —
exactly the mistake a hurried edit would make — and watched three tests fail, including
the symmetry one. Then reverted. A guard I have not seen fail is a guard I do not have.

**The blocker I did not fix.** `protocol_adapter.py:70` calls the async-only
`context.get_input_text()` without awaiting it, so a coroutine lands in
`types.Part(text=...)` and raises. Every real invocation against the deployed digest
fails before a tool is reached. It is Brett's file and fixing it changes the image
digest, invalidating both deployed agent versions — so it is Brian's sequencing call,
not mine. Reported with the proof rather than quietly patched.

**Deployment coupling I keep having to re-state.** Anything under `src/` changes the
image digest. The marker change means the deployed digest `…bfa0d45` does *not* carry
the query parameter. Until Brian rebuilds and redeploys both versions, a live run would
produce exactly the correlation gap this change exists to close.

### 2026-10-08 — Debugging batch: evidence coordination and receiver readiness verification

- **Orchestration log created: 2026-10-08T19:49:02Z-dallas.md**
- **Session log 2026-10-08T19:51:57Z-deploy-poller-debugging.md documents the batch**
- **Critical finding — `demo_run_id` placement risk flagged:**
  - `get_servicing_policy` sends `demo_run_id` as both URL query param **and** header ✓
  - `send_to_external_processor` sends `demo_run_id` as **header only** (no query string) ⚠️
  - If platform egress decision record logs URL but not headers, evidence would correlate **allowed** call only (headers captured), missing **denied** call (headers-only, denied because stripped from URL)
  - **Mitigation:** If Q0c shows URL-logged / header-ignored pattern, add `demo_run_id` to query string on `send_to_external_processor` — one-line change in agent tool code
- **Verified:** Test receiver endpoint ready, accepts unauthenticated POST, marker extraction working, receipt logging ready for first invocation
- **Next:** Run Q0 with first invocation to test Layer 1 ↔ Layer 2 correlation. If Q0c shows URL-logged pattern, apply mitigation. Run Layer-3 queries.
- **Note on deployment coupling:** This batch did not change deployed digests (decision merging only). However, Brett's poller fix changes `src/containment_demo/deploy.py`, so image digest changes on next build. Dallas's earlier `protocol_adapter.py` fix also changed digest (bug: `context.get_input_text()` not awaited). Until Brian rebuilds and redeploys both versions, live runs will carry Brett's fix but not the marker-in-query-string pattern if Dallas's PR is merged. Sequencing is Brian's call.


### 2026-10-09 — Sections B and C: verdicts as pure functions

Implemented B/C in `verify_demo.py` as functions of supplied rows, so the whole absence
logic is testable offline. Key judgement: the permitted call's receipt for the same run,
read in the same query, is the positive control for "no receiver receipt" — no extra
query needed, and it reuses `classify_receipt_absence`. The 3-minute wait is measured
from the later of the call and the Deny row, and `queried_at` is taken from the clock,
not the operator. Exact-path matching matters: a prefix match lets run-abc claim run-abcd.
Tamper-testing found five guards my tests did not actually pin (redundant checks whose
removal changed nothing, or a verdict reachable through a later branch); I added tests
asserting the *reason text* or the one-signal-of-two cases. 38+2 tests. Live KQL for
decision rows is unexecuted; field locations come from telemetry-map §0.6.3.
