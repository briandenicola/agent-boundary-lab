# Implementation plan: ADK agent containment and observability

**Re-gated 2026-10-08 by Ripley** against `docs/compatibility.md`, `docs/telemetry-map.md`,
`docs/egress-control.md`, `.squad/decisions.md`, and the code that actually exists. The
original plan was written before Brett, Parker, Dallas and Lambert did verification work,
and several facts it assumed turned out to be wrong. Everything corrected is listed in
[Re-gate changelog](#re-gate-changelog) so nobody has to diff from memory.

## How to read this plan

Every phase is labelled with a status and every claim inside it is labelled with one of
three words. They are not synonyms and they are never to be blended:

| Label | Means |
| --- | --- |
| **tested result** | Observed by us, on this subscription or in this repo, with a date. |
| **proposed behaviour** | What we intend to build or expect to see. No evidence yet. |
| **preview capability** | Documented by Microsoft, preview, no SLA, not production. Documented ≠ observed. |

Phase status values: **done**, **partial**, **not started**, **blocked**.
A phase is **blocked** only when a specific named thing would unblock it. "We are unsure"
is not blocked; it is unverified, and unverified work still gets planned.

**Standing rule:** missing evidence is **inconclusive**. Never a pass. A bare HTTP 403, a
DNS failure, a timeout, a model refusal, or an empty query result is not containment.

## Implementation contract

**Non-negotiable:** Google ADK, exactly two business tools registered unconditionally,
Foundry hosted-agent execution, externally configured egress enforcement, synthetic data,
inspectable evidence. No application-only denial presented as a platform boundary.

**Experimental control:** the attached RAI policy is the ONLY variable between the two
deployed agents. Same image digest, same environment except `DEMO_POLICY_MODE` (an
evidence label, never branched on) and the policy ARM id.

**Approval gate:** generate code, tests and deployment artifacts freely. Owner approval
before creating billable resources, changing Azure policies, publishing images, or sending
telemetry to a new destination. Never modify an existing production or mixed-purpose RAI
policy.

---

## GATE 0 — The correlation gate. Runs FIRST on the first real agent run.

**Status: blocked — needs one successful hosted agent run. Nothing downstream is
trustworthy until this is answered.**

This is the top risk to the entire demo and it outranks every remaining build task.

**Tested result (2026-10-08):** `demo_run_id` correlates Layer 1 (our application/tool
traces) to Layer 3 (receipts at the two controlled endpoints). Verified end to end against
real receipt rows — `docs/telemetry-map.md` §3.2, §5.

**Tested result (2026-10-08):** it does **not** reach Layer 2. Our marker travels in an
HTTP header and a query param; the platform egress decision record is written by the
sandbox proxy and **no primary source documents it copying our header**
(`docs/compatibility.md` C3, Blocker 4).

**Proposed behaviour:** generic Application Insights `OperationId` propagation may join the
two layers for free. Untested. `docs/telemetry-map.md` Q6 exists to test exactly that.

### Exit criteria — checkable

- [ ] One hosted agent invocation has completed and produced at least one row matching
      `Message == "Network egress decision"` (Q5a), or the equivalent classic-schema form
      at App Insights resource scope (Q5b). **Record which scope returned rows.**
- [ ] Q6 has been run and its answer recorded in `docs/telemetry-map.md` §5 **with a date**,
      `joined == true` or `joined == false`. Either answer exits this gate; no answer does not.
- [ ] Q5a raw `Properties` inspected for any key echoing our run id, and the result
      recorded even when negative.
- [ ] `docs/telemetry-map.md` §2.1 populated from a real row, or explicitly recorded as
      still empty with the query that returned nothing.

### Branch on the answer — decide this before running, not after

| Q6 result | Consequence |
| --- | --- |
| `joined == true` | Layer 1 ↔ Layer 2 join exists. Record it, use it, and say which key. Phases 5–7 proceed as written. |
| `joined == false` | **The evidence model needs rework before Phase 5 can produce a result.** The demo may then only claim "three consistent observations in one short window", never "a correlated trace". Every report, the runbook and the evidence template must be rewritten to that weaker sentence before any run is shown to anyone. |

**The fallback is weaker than it sounds.** Run window + destination hostname + agent
version is a coincidence argument, not a join. It breaks under concurrent runs; the
"strictly serial runs" rule (`.squad/decisions.md`) is a **procedural** control standing in
for a missing technical one, and a procedural control is only as good as the operator. The
hostname leg additionally depends on a property key we have never seen
(`docs/telemetry-map.md` §2.1 is deliberately blank).

**What would unblock this gate:** a deployed agent version that runs once. Which means
Phase 4, which means the init-container defect below.

---

## Phase 0 — Compatibility and availability spike

**Status: done, with named residue.** Output is `docs/compatibility.md` (research date
2026-10-07, corrections 2026-10-08).

**Tested result:** `google-adk` 2.11.0 + `azure-ai-agentserver-responses` 2.2.0 co-install
under a tested OpenTelemetry override to `>=1.43,<2` and smoke-test on 1.44.0 (Blocker 0,
resolved). LiteLLM's `azure_ad_token_provider` callback supports rotating Entra tokens
(E2). The Foundry host configures OpenTelemetry on construction; ADK no-ops if constructed
second (E3). Managed VNet + both egress policies coexist on one account and are stored
verbatim — **control-plane acceptance only** (Blocker 1 stage 1, read back from ARM
2026-10-08). Canada Central and Sweden Central pass the egress spike; Canada Central is the
target because PostgreSQL Flexible Server is restricted in East US 2 (A2a, A2b).

**Preview capability:** network egress controls are preview, no SLA, explicitly not for
production. Hosted agents are GA with preview sub-features (A1, B1, Blocker 2).

**Still unverified after Phase 0 — these are tracked, not closed:**

- Egress-decision property key names (C1, telemetry-map §2.1). Unblocked by: one real row.
- Whether egress decisions carry a joinable `operation_Id` (C3). Unblocked by: GATE 0.
- Whether egress evidence reaches a custom OTLP endpoint (C4). **Do not claim it does.**
- The 403 body/headers and whether DNS resolves for a blocked host (B5).
- The itemized implicit auto-allow list (B8, Blocker 3).
- Which layer governs when managed VNet and egress policy both apply (D2/D3, Blocker 1
  stage 2). Unblocked by: a real agent making real calls under each policy.
- ADK runtime behaviour on OpenTelemetry 1.43+ under load; the smoke test covered import
  and construction only.

---

## Phase 1 — Repository and local scaffold

**Status: done.**

**Tested result:** repository structure, `pyproject.toml` with the documented dependency
override, Dockerfile, `.env.example`, startup validation, and both controlled services
(`services/policy_api`, `services/test_receiver`) exist and run. Receipt lines are one JSON
object per line on stdout and land in `ContainerAppConsoleLogs_CL`; three real receipt rows
observed 2026-10-08 (`docs/telemetry-map.md` §3.2). `/healthz` is deliberately not logged
as a receipt, which is load-bearing for "no receipt means nothing arrived".

**Tested result — hygiene defect, open:** a live `test-receiver` receipt was observed with
an **empty** `demo_run_id`. Unattributed arrivals exist in the log, so "zero receipts for
our run id" is **not** "nothing arrived". Every negative claim must pair Q2 with Q2a.

**Exit criteria — met, with one addition:**

- [x] Both services healthy; receipts queryable by run id.
- [x] Container builds; digest-pinned image deployable.
- [ ] Source of the empty-`demo_run_id` receipt identified, or the window in which it can
      recur documented in the runbook. Open.

**Proposed behaviour, not tested:** that local compose success says anything about
Foundry containment. It does not. Local runs are functional tests. Label them that way.

---

## Phase 2 — ADK agent and deterministic execution

**Status: partial — code done, hosted execution unproven.**

**Tested result:** both tools (`get_servicing_policy`, `send_to_external_processor`) are
implemented with destinations from validated configuration, TLS verification on, explicit
timeouts, redirects disabled, no fallback destination, sanitized errors, and failure
classification by kind (`http_error` / `tls_error` / `dns_error` / `timeout` /
`connection_error` / `unexpected` — note there is deliberately **no** `policy_denied`
category, because a client cannot observe a platform decision). Unit tests in `tests/unit`
assert unconditional registration and no mode-specific branching.

**Tested result:** the runtime CA for the egress proxy's TLS interception is read from the
environment on every client build and is never baked into the image (B6).

**Not tested — the whole point of the phase:**

- [ ] The same two tool implementations have executed **inside the hosted runtime**.
- [ ] A normal ADK tool-call trace (model-selected) captured in addition to the
      deterministic diagnostic route, with the difference stated explicitly in the report.

**Exit criteria — checkable:** `tests/unit` green (met) **and** one hosted diagnostic
invocation returning two independent tool results, with one tool's failure demonstrably not
suppressing the other's result. The second half is blocked on Phase 4.

---

## Phase 3 — Instrumentation and evidence model

**Status: partial.**

**Tested result:** our own span attributes and the `demo.tool_result` span event are
verified from source and documented in `docs/telemetry-map.md` §1.1–1.2. Content-recording
environment variables are set to `false` as a fail-closed safety floor. App Insights
`humble-phoenix-46689-ai` is workspace-based (`IngestionMode: LogAnalytics`), so workspace
scope uses the `App*` tables and the classic `traces`/`customDimensions` names only resolve
at resource scope. Both are correct; the scope decides, and which one worked must be
recorded on every query.

**Tested result — the blocking finding that was found and fixed in code:** the Foundry
project had **no connections at all** on 2026-10-08, so platform egress evidence had
nowhere to land and every run would have been inconclusive by construction. The App
Insights project connection is now written in `infra/cloud/project-connections.tf` with a
schema read out of installed SDK source (`category: AppInsights`, `authType: ApiKey`,
`credentials.key` = the **connection string**, not an instrumentation key; at most one such
connection; an `AAD`/`ManagedIdentity` connection applies cleanly and then silently does
nothing).

- [ ] **Open:** confirm by re-reading the project `connections` endpoint and seeing a
      non-empty `value` with `authType == ApiKey`. Terraform authoring is not evidence.

**NOT VERIFIED and marked as such in code:** what `target` should hold for an `AppInsights`
connection. The read path never touches it, so a wrong value cannot silence evidence.

**Blocked — needs one hosted run:**

- [ ] Which table our spans land in (`AppTraces` / `AppDependencies` / `AppEvents`). Q3a is
      the discovery query and must run before any query that names a table.
- [ ] Whether dotted attribute keys survive verbatim (`demo.run_id`) or are flattened.
- [ ] `docs/telemetry-map.md` §2.1 — the platform field table — is **deliberately blank**.
      Nothing about egress decision record fields is verified. Do not pre-populate it from
      portal UI labels; those are labels, not column names.

**Exit criteria — checkable:** §1.3 and §2.1 of `docs/telemetry-map.md` each contain real
keys with an observation date, or an explicit record of the query that returned nothing.
An authorized viewer can locate a tool attempt and its outcome. No prompt, payload or
authorization header appears anywhere in exported telemetry.

---

## Phase 4 — Infrastructure, policy, and deployment

**Status: blocked. This is the critical path to everything.**

**Tested result:** Terraform for the account, both RAI policies, the two controlled
endpoints on distinct HTTPS hostnames, and the AKS deploy harness exists and validates.
Required-but-undocumented RAI policy properties were found by failed applies and are
recorded in `docs/compatibility.md` Blocker 1: `basePolicyName` is mandatory,
`properties.contentFilters` is mandatory (a custom policy does **not** inherit the base's
filters), `properties.type = UserManaged`, and content filters are held identical across
both policies through one shared local so that `egressPolicy.mode` is the only difference.

**Tested result — two corrections the original plan did not know:**

1. **`az cognitiveservices agent` cannot attach an RAI policy.** No subcommand exposes it
   and `_create_agent_definition` never emits `rai_config` (B9, verified by reading the
   installed CLI source). Since the policy is the only experimental variable, **the CLI
   cannot deploy either agent.** Deployment goes through `azure-ai-projects` 2.8.0.
2. **The data plane is unreachable from outside the VNet** (`publicNetworkAccess: Disabled`
   → `403 Public access is disabled`). Deployment must originate inside the VNet. That is
   the whole reason the AKS init container exists.

**Tested result — the SDK shape, which differs from the CLI shape in B9** (B9a, read from
installed `azure-ai-projects` 2.8.0 source on 2026-10-08):

- The image is nested at `definition.container_configuration.image`, **not** a flat
  `definition.image`.
- Protocols are `definition.protocol_versions`, **not** `container_protocol_versions`.
- **There is no container start operation at all.** No `containers/default:start`
  equivalent exists on `AgentsOperations`. Readiness is observed by polling
  `get_version(...).status` until `active`.
- `AIProjectClientConfiguration.api_version` defaults to `"v1"` with a separate
  `allow_preview` flag — **not** an explicit preview date string.
- `RaiConfig(rai_policy_name=<full ARM id>)` hangs off `HostedAgentDefinition`, wire name
  snake_case. Setting a policy through the SDK is possible; through the CLI it is not.

`src/containment_demo/deploy.py` implements exactly this shape.

**Blocked — specific blockers, each with what unblocks it:**

- [ ] **Init-container interpreter mismatch.** `infra/k8s/harness.tf` runs
      `["python", "-m", var.agent_deploy_module]`. The Dockerfile installs `.[deploy]`
      (and therefore `azure-ai-projects`) **only** into `/opt/deploy-venv`, and
      `.squad/decisions.md` records the agreed command as
      `["/opt/deploy-venv/bin/python", "-m", "containment_demo.deploy"]`. As written the
      init container will fail with a missing `azure.ai.projects`.
      **Unblocked by:** Parker correcting the command in `harness.tf`.
      **Reviewer note:** this is Parker's to fix, not Brett's.
- [ ] **Server-side digest acceptance is unverified.** `ContainerConfiguration.image` is an
      unvalidated `str`, so `repo@sha256:…` passes client-side; whether the service accepts
      it cannot be known without a call from inside the VNet. `deploy.py` raises
      `DigestRejectedError` and stops rather than falling back to a tag — correct, because a
      tag fallback would let the control variable drift.
      **Unblocked by:** the first in-VNet deploy attempt. Record the exact error in
      `docs/compatibility.md` B9a either way.
- [ ] **RBAC on `agents/versions` write is unverified.** No primary source names the
      required role; `Cognitive Services User`'s wildcard is *presumed* to cover it.
      **Unblocked by:** the first deploy attempt. A 403 here means RBAC, not the federated
      credential — check that first.
- [ ] **Attribution under a managed VNet.** Blocker 1 stage 2. If the demo runs with a
      managed VNet, the report must show a denial is attributable to the egress policy and
      not to managed-network routing. Stage 1 cannot supply this.
      **Unblocked by:** a real agent making real calls under each policy, plus §D resolution.

**Terminology correction:** these are **two separately named agents**
(`containment-demo-audit`, `containment-demo-enforced`), not two versions of one agent
(`.squad/decisions.md`). Wherever the old plan said "both agent versions", read "both
agents". `assert_single_variable` enforces that nothing but the policy differs.

**Exit criteria — checkable:**

- [ ] Both agents report `status == active` from `get_version`.
- [ ] Each agent's `definition.rai_config.rai_policy_name` read back and matching the
      intended policy ARM id.
- [ ] Both agents carry byte-identical `container_configuration.image` digests.
- [ ] `assert_single_variable` passes against the read-back definitions, not against
      intent.
- [ ] Both policies read back from ARM showing `egressPolicy.mode` Audit / Enforced, the
      same `defaultAction: Deny`, the same content filters, and the receiver hostname
      **absent** from the allowlist.
- [ ] Image digest, agent name, policy ARM id, mode and timestamp recorded in evidence
      metadata.

**Authoring success is not enforcement proof.** A policy that applies cleanly and does
nothing looks identical to one that works, right up until the negative call succeeds.

---

## Phase 5 — Verification harness

**Status: partial. Section A done; Sections B and C are stubs.**

### A. Independent baseline — **done**

**Tested result:** `scripts/verify_demo.py` Section A runs from a control client, reaches
both endpoints, reads receipts back out of Log Analytics with the telemetry map's own
queries (Q1, Q2a, Q8), and classifies receipt absence into four distinct outcomes
(arrived-for-this-run → fail; arrived-unattributed → inconclusive; no-rows with
retrievability proven in the same window → pass for the receipt leg only; query
unavailable → inconclusive). It confirms the negative endpoint is not rejecting requests
through its own authorization. Exit codes: 0 pass, 1 fail, 2 inconclusive.

**Standing constraint:** the test receiver must stay unauthenticated. If auth is ever
added, a 403 from inside the sandbox becomes unattributable to the egress policy and the
demo design changes. Parker notifies Dallas and Ripley before any auth layer.

**Standing constraint:** every probe carries `X-Demo-Run-Id`. An unmarked probe plants an
unattributable receipt and manufactures exactly the ambiguity Q2a exists to detect.

### B. Hosted Audit run — **not implemented**

Currently a stub returning `not_implemented`, which can never return a pass. Correct
behaviour; do not change it until there is something to invoke.

**Proposed behaviour, pending GATE 0 and Phase 4:**

- [ ] Both tools invoked from inside the deployed hosted runtime.
- [ ] Both requests observed arriving at their endpoints (Q1).
- [ ] A platform **would-deny** record retrieved for the unapproved destination.
- [ ] The permitted destination still allowed.

### C. Hosted Enforced run — **not implemented**

**Proposed behaviour, pending GATE 0 and Phase 4:**

- [ ] Permitted tool succeeds and its receipt appears (Q1).
- [ ] Unapproved tool **attempted** the request and failed, classified by kind.
- [ ] A matching platform decision record retrieved.
- [ ] Q2 **and** Q2a both zero over an explicitly bounded `(start, end)` window — never a
      relative "last N minutes", which reaches back before the run and contaminates the
      result. Use the in-payload `received_at`, not `TimeGenerated`; measured ingestion lag
      was ≈1.5 s on 2026-10-08 and the Foundry-side lag is unmeasured.
- [ ] Receipt-logging health proven in the same window (Q8) before any absence is read as
      containment.

**The three-signal rule:** attempt trace + platform decision record + no receipt. Any two
of three is **inconclusive**. Zero receipts alone is not a result.

### D. Observability checks — **not implemented**

- [ ] ADK tool spans distinguishable from protocol-only invocation traces.
- [ ] Run/trace correlation stated at its real strength — see GATE 0.
- [ ] No sensitive content present.
- [ ] Optional OTLP delivery verified separately, and **never** described as carrying
      platform egress decisions (C4).

**Exit criteria:** an Audit run and an Enforced run each produce corroborating evidence
across all three layers, and no verdict is inferred from a model answer or an HTTP status
alone.

---

## Phase 6 — Tests and failure scenarios

**Status: partial.**

**Tested result:** `tests/unit` covers unconditional tool registration, fixed and distinct
destination configuration, timeouts and redirect settings, TLS verification never disabled,
sanitized and classified errors with no invented policy decision, one tool's failure not
suppressing the other, log hygiene, absence of mode-specific denial, and the dependency
override.

**Not started:** `tests/integration` is **empty**. Every integration item below is
unwritten, not merely unrun.

- [ ] Local baseline reaches both controlled APIs.
- [ ] Hosted Audit and Enforced behaviour matches Phase 5 (blocked on Phase 4).
- [ ] Endpoint-side 403, DNS failure, TLS failure and an unhealthy API are each **not**
      classified as successful policy enforcement.
- [ ] Missing, sampled or delayed telemetry is inconclusive, not proof of allow or deny.
- [ ] Wrong agent or wrong policy attachment is detected from read-back, not from intent.
- [ ] Model-provider and telemetry connectivity remain functional under the configured
      policy — i.e. the policy did not accidentally break the agent's own dependencies.
- [ ] **Blocker 3 test:** remove the explicit allow rule and confirm the permitted
      destination is then denied too. If it still succeeds, an undocumented implicit allow
      is carrying the positive result and the positive leg proves nothing.

**Optional narrative test:** a synthetic instruction requesting the external-processor
tool, showing that even an actual attempted call cannot cross the boundary. This is one
test. It is **not** a prompt-injection defence claim.

---

## Phase 7 — Demo runbook and handoff

**Status: not started.** `docs/demo-runbook.md` and `docs/evidence-template.md` do not
exist.

Preconditions before this phase is worth starting: GATE 0 answered, Phase 4 exited.

- [ ] Preflight checklist, which is `docs/telemetry-map.md` §7 items 1–8 verbatim plus
      preview access and policy read-back.
- [ ] Explicit statement of the strictly-serial run rule **as a procedural control
      substituting for a missing technical join**, with start/end timestamps recorded per
      run. If GATE 0 returned `joined == true`, this paragraph gets replaced, not softened.
- [ ] Runbook steps 1–7 as originally drafted: show the tools and destination policy,
      execute Audit, execute Enforced, correlate at the strength the evidence supports,
      explain operator access and optional export, close with preview limitations.
- [ ] Tested installation and run commands. Reviewed deployment commands with verified
      flags, not guessed syntax.
- [ ] Evidence template and a captured synthetic report.
- [ ] Resource/cost inventory and bounded teardown that deletes only approved demo
      resources.
- [ ] Known limitations and troubleshooting for startup, adapter, certificate, policy,
      trace and receipt-log failures.

**If live execution fails, show only previously captured, clearly dated evidence, labelled
as such.** Never relabel it as a live result.

---

## Phase 8 — Dapr Workflow on AKS

**Status: not started. Gated on the base containment criteria passing.**

Do not begin before Phase 5 §C produces a result. A durability story wrapped around an
unproven containment claim is a more elaborate version of the same mistake.

**Tested result (2026-10-08):** PostgreSQL Flexible Server is restricted in East US 2 on
this subscription and Flexible Server uses VNet injection, which is why the target region
moved to Canada Central (A2b). A workflow state store must back **actors**; PostgreSQL
qualifies, Table and Blob storage do not (A2c).

**Preview capability / proposed behaviour — everything else in this phase.** Azure Durable
Task Scheduler and its SDK are explicitly **not** dependencies.

- [ ] Pin and record Dapr runtime, Python Workflow SDK, AKS version, install method and
      state component in `docs/compatibility.md` with a documentation date.
- [ ] One installation method only — AKS extension **or** Helm. Do not double-install the
      control plane.
- [ ] Add `src/workflow_app/`, `src/workflow_api/`, `tests/workflow/`, `infra/aks/`,
      `infra/dapr/`, and an independent workflow-app image.
- [ ] Validate required state operations, transactions, concurrency, connection limits,
      TLS and credential handling for the pinned PostgreSQL version.
- [ ] Inventory required Dapr services including placement and reminder scheduling.
      Distinguish any Dapr Scheduler from Azure Durable Task Scheduler.
- [ ] Workflow shape: first agent activity → approval event with durable deadline →
      follow-up agent activity → completion. Model, HTTP and broker calls live in
      activities; workflow decisions stay replay-deterministic.
- [ ] Handle approval denial and timeout explicitly. **Approval cannot change a Foundry
      egress policy** and must never be presented as if it could.
- [ ] Stable instance IDs and activity idempotency keys. Handle duplicate events,
      ambiguous completion and retries.
- [ ] Treat a corroborated platform denial as an expected non-retry result; bounded retries
      only for classified transient failures.
- [ ] Pod-restart test with storage intact; verify the same instance completes and
      checkpointed work is not needlessly repeated.
- [ ] Distinguish pod-restart recovery from database-loss recovery. A pod test is not a
      data-loss claim.

**Exit criteria:** a reproducible AKS workflow survives workflow-pod replacement during a
durable wait, invokes the **unchanged** Foundry agent, and retains inspectable evidence
that stays distinguishable from the containment evidence.

---

## Phase 9 — Agentic harness on AKS (standing in for on-premises)

**Status: not started. One hard blocker already identified.**

The harness is a full agentic runtime with its own loop, model and local tools. It is not a
request script, and **the Foundry egress policy does not govern it**. It runs on AKS inside
the VNet standing in for on-premises; it is not on-premises and must never be described as
if it were.

**Blocked — Blocker 5:** incoming A2A is confirmed for **prompt agents** only. Ours is a
hosted **container** agent that happens to use the required Responses protocol. No primary
source confirms or denies our case.
**Unblocked by:** a spike that enables A2A on a hosted container agent.
**Fallback, cheap and pre-agreed:** call the agent over Responses directly and record the
substitution. Containment is unaffected — how the harness *reaches* the agent has no
bearing on what the agent's tools can *reach*.
**Do not write A2A-on-hosted-container-agents into any report as tested until the spike
proves it.**

**Tested result:** none in this phase yet.

**Preview capability / documented facts (accessed 2026-10-08), not yet exercised by us:**
A2A v1.0 is GA and JSONRPC-only; **unversioned requests are served preview v0.3**, so pin
via `A2A-Version: 1.0`, `?a2a-version=1.0`, or by resolving the v1.0 card — and never send
two selectors with different values (HTTP 400 `version-ambiguous`). Entra ID only; keys and
anonymous access unsupported **including for the agent card**. Caller role **Foundry Agent
Consumer** `eed3b665-ab3a-47b6-8f48-c9382fb1dad6`, scoped to a single agent where possible;
token scope `https://ai.azure.com/.default`. The card lives at
`…/endpoint/protocols/a2a/agentCard/v1.0`, **not** `.well-known/agent-card.json`. A2A tasks
and contexts are retained 60 days from last write.

- [ ] Narrow application-owned API: start case, query status, submit authorized event.
- [ ] `samples/onprem_harness/` — standalone agent runtime, no Dapr install, no sidecar.
- [ ] Confirm the harness resolves Foundry through the private DNS zones
      (`cognitiveservices`, `openai`, `services.ai`), not a public IP.
- [ ] **Never present the private endpoint as outbound containment.** It governs inbound
      reach only. An agent behind a private endpoint can still call any host on the
      internet. Conflating the two is the precise error this repository exists to disprove.
- [ ] **Do not introduce MCP into the containment path.** Foundry agents are MCP *clients*;
      the supported direction would have the agent calling out to an on-premises MCP server
      — which is the egress path under test, would require allowlisting an on-premises
      host, and would destroy attribution of a denial to the policy alone.
- [ ] Keep raw sidecar HTTP/gRPC and admin APIs private.
- [ ] Authenticate callers; enforce case ownership, event authority, allowed workflow
      types, schema/body limits, rate limits and replay handling. A sophisticated caller is
      not a trusted caller, and an agent may not self-authorize human approval.
- [ ] Keep the two halves distinguishable in every artifact: what ran in the ungoverned
      harness versus what ran inside the contained Foundry container. A report that blurs
      them is a failure, not a pass.
- [ ] Keep the direct path (harness → agent) and the workflow path (harness → API → Dapr)
      separate, so a denied call has exactly one sufficient cause.

---

## Phase 10 — Deferred

Messaging bridge and on-premises/OpenShift portability. **Deferred by decision.** Separate
approval required before any work starts. Nothing in Phases 0–9 may depend on it.

---

## Definition of done

The owner can reproduce one ADK agent with two unchanged business tools in a real Foundry
hosted runtime, show permitted versus denied outbound destinations, and inspect
corroborating evidence across all three layers — **at the correlation strength GATE 0
established, stated in those words.** The repository separates tested result from proposed
behaviour and preview capability from production guarantee, everywhere, without exception.

### Extended definition of done

A Python Dapr Workflow app on AKS resumes the same case after workflow-pod restart during
an approval wait with storage intact. A separate agentic harness on AKS, standing in for
on-premises, invokes the unchanged hosted agent across the private endpoint —
Entra-authenticated, protocol version pinned — and independently drives a case through a
secured API. If incoming A2A proves unsupported on hosted container agents, the harness
uses Responses and the substitution is recorded rather than hidden. MCP is excluded from
the containment path by design. The Foundry account stays inbound-private and the harness
ingress is the only public surface, with the private endpoint never presented as outbound
containment. Azure Durable Task Scheduler is not required.

---

## Re-gate changelog (2026-10-08)

What this plan previously got wrong or left stale, and what replaced it:

1. **No correlation gate existed.** The single biggest risk — that `demo_run_id` does not
   reach Layer 2 — appeared nowhere in the plan. Added as **GATE 0**, ahead of every phase,
   with an explicit branch for `joined == false`.
2. **Phase 4 assumed the CLI could deploy the agents.** It cannot attach an RAI policy at
   all (B9), so it cannot deploy either side of a single-variable experiment.
3. **The deployment payload shape was the CLI's, not the SDK's.** Image is nested at
   `definition.container_configuration.image`; protocols are `protocol_versions`; there is
   **no container start operation** and readiness is polled via `get_version(...).status`;
   `api_version` defaults to `"v1"` with a separate `allow_preview` flag (B9a).
4. **"Both agent versions" was wrong.** They are two separately named agents.
5. **"Zero receipts" was treated as sufficient.** A live receipt with an empty
   `demo_run_id` was observed, so Q2 now requires Q2a as a mandatory companion.
6. **Platform field names were implicitly assumed to exist.** Telemetry §2.1 is blank and
   stays blank until a real row is read. No KQL may name a platform property key.
7. **Phase 3's "enable Application Insights" was one line.** It was in fact a blocking
   finding — the project had no connections at all — with a non-obvious schema where the
   "API key" is the connection string and an `AAD` connection applies cleanly then silently
   does nothing. Terraform now exists; the read-back is still open.
8. **Phase 5 §B and §C were written as if implementable.** They are stubs that report
   `not_implemented` and cannot return a pass. Marked as such.
9. **Phase 6's integration tests were listed as if partially done.** `tests/integration` is
   empty.
10. **Blocker 3 had no test.** The allow-rule-removal control is now an explicit Phase 6
    item: without it, an undocumented implicit allow could be carrying the positive result.
11. **Strictly-serial runs were presented as a mitigation.** They are a *procedural*
    control standing in for a missing technical join. Labelled.
12. **A live defect blocks Phase 4:** `infra/k8s/harness.tf` runs the init container with
    `python`, but `azure-ai-projects` is installed only into `/opt/deploy-venv`. Parker's
    to fix.
13. **Phase 8/9 preconditions were implicit.** Both are now explicitly gated on the base
    containment criteria producing a result first.
