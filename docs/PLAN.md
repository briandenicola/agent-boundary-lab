# Implementation plan: ADK agent containment and observability

## Implementation contract

Build the demo specified in README.md. This is a proposed engineering plan, not proof that a deployment already works.

**Non-negotiable:** Google ADK, exactly two business tools, Foundry hosted-agent execution, externally configured network egress enforcement, synthetic data, and inspectable evidence. No application-only denial presented as a platform boundary.

**Approval gate:** Generate code, tests, and deployment artifacts first. Obtain owner approval before creating billable resources, changing Azure policies, publishing images, or sending telemetry to a new destination. Never modify an existing production or mixed-purpose RAI policy for this demo.

## Phase 0 — Compatibility and availability spike

Complete this before investing in the full build.

- [ ] Verify hosted-agent support and network-egress preview availability in the target project/region.
- [ ] Read the primary references in README.md and their linked current setup guides. Record access date and actual supported API/package versions.
- [ ] Create a minimal Python ADK agent and validate a model adapter against a Foundry model deployment. Do not assume Google ADK requires a Google-hosted model, and do not assert adapter support without a working smoke test.
- [ ] Implement the smallest supported Foundry Responses or Invocations adapter around the ADK runner. Prefer Responses if a working integration is available; otherwise use supported Invocations and explicitly document session handling.
- [ ] Validate health endpoints, request/response contract, startup configuration, and ADK session mapping against the chosen hosted protocol.
- [ ] Verify the policy attachment method and runtime CA handling from current documentation.
- [ ] Confirm where real platform egress decisions appear and what fields they contain.
- [ ] Test how the Foundry protocol runtime and ADK share or bridge OpenTelemetry context/providers without duplicate export.

**Output:** `docs/compatibility.md` with validated dependency versions, chosen protocol/model adapter, preview prerequisites, sample non-sensitive evidence, and unresolved blockers.

**Stop condition:** If native hosted egress is unavailable, mark the hosted enforcement work blocked. Continue only local scaffolding that remains useful. Do not silently substitute a tool wrapper, API gateway, firewall, or simulated denial as proof of Foundry-native enforcement. Any alternative is a separately labeled design requiring owner agreement.

## Phase 1 — Repository and local scaffold

- [ ] Create the proposed repository structure from README.md.
- [ ] Add `pyproject.toml`, dependency locking, lint/test configuration, `.gitignore`, Dockerfile, and `.env.example`.
- [ ] Validate configuration at startup; fail clearly for missing destinations, malformed URLs, identical destination hosts, or unsupported modes.
- [ ] Provide placeholders for project endpoint, model deployment, two tool URLs, registry/image, and optional OTLP endpoint. Do not commit secrets or actual connection credentials.
- [ ] Implement two controlled API services:
  - Policy API: returns a fixed synthetic servicing-policy response.
  - Test receiver: accepts a harmless synthetic record and logs its correlation marker without storing request content.
- [ ] Provide a local compose workflow if useful. Local networking proves only functionality, not Foundry containment.

**Exit:** Both services are healthy; their request receipt evidence is queryable; the container builds reproducibly.

## Phase 2 — ADK agent and deterministic execution

Implement exactly two business tools:

### `get_servicing_policy`

- No arbitrary URL argument; destination comes from validated configuration.
- GET the configured policy endpoint, passing a synthetic `demo_run_id` marker.
- Return a bounded, structured synthetic policy result or a sanitized error.

### `send_to_external_processor`

- No arbitrary URL argument; destination comes from validated configuration.
- POST a fixed, harmless synthetic record to the configured test receiver.
- Return a bounded, structured receipt result or a sanitized error.

Shared HTTP requirements:

- [ ] TLS verification enabled; documented runtime CA bundle used where required.
- [ ] Explicit timeout; redirects disabled; no fallback to another destination.
- [ ] No embedded hostname denial or mode-specific behavior in the tool implementation.
- [ ] No secrets, payloads, or authorization headers in logs.
- [ ] Catch HTTP, TLS, DNS, and timeout failures separately; do not classify generic failure as policy denial.

Agent requirements:

- [ ] Register both tools unconditionally in Audit and Enforced deployments.
- [ ] Use a concise banking-servicing prompt, but never rely on it for containment.
- [ ] Provide normal conversational interaction for the narrative.
- [ ] Provide an authenticated deterministic diagnostic route through the hosted protocol that executes both existing tool implementations independently. It is not a third business tool and cannot accept arbitrary destinations.
- [ ] Preserve separate result records even if one call fails.

**Exit:** Local tests prove both calls succeed and produce receipt evidence. A hosted-runtime diagnostic proves that the same two tool implementations actually execute there. Be explicit if a deterministic diagnostic bypasses model tool selection; also capture a normal ADK tool-call trace to demonstrate framework integration.

## Phase 3 — Instrumentation and evidence model

- [ ] Configure ADK instrumentation and Foundry protocol telemetry using the validated integration from Phase 0.
- [ ] Enable Application Insights through project monitoring.
- [ ] Emit structured application metadata with trace correlation and a unique synthetic run marker.
- [ ] Use full sampling for synthetic tests where supported; do not assume log export and span sampling behave identically.
- [ ] Disable message/body capture and redact errors before export.
- [ ] Test context propagation to controlled APIs; keep `demo_run_id` as a fallback correlation key.
- [ ] Record platform egress decision fields separately from application fields.
- [ ] Identify least-privilege monitoring roles for customer/operator viewers.
- [ ] If optional OTLP export is required, configure an approved collector and secure authentication using supported connections. Verify telemetry reachability under the policy.
- [ ] Verify which evidence streams reach the collector. Do not claim that application OTLP automatically includes platform egress decisions.

Create `docs/telemetry-map.md` mapping:

| Evidence | Actual source | Actual fields | Correlation method | Viewing/export path |
| --- | --- | --- | --- | --- |
| Agent invocation | Discover during spike | Discover | Trace/run marker | Verify |
| ADK tool execution | ADK instrumentation/application | Discover | Trace/run marker | Verify |
| Egress decision | Foundry platform | Discover; never invent | Verify available linkage | Verify |
| API receipt | Controlled service | Synthetic run marker, timestamp | Run marker | Verify |

Create runnable monitoring queries only after observing the real tables and properties. If correlation is incomplete, document that limitation rather than fabricating a joined trace.

**Exit:** An authorized viewer can locate tool attempts and outcomes; sensitive content is absent; platform decisions have a documented evidence path.

## Phase 4 — Infrastructure and policy definitions

- [ ] Generate reviewable infrastructure/deployment artifacts with configurable resource names and region.
- [ ] Use separate test resources or a clearly bounded approved test project.
- [ ] Provision the two endpoints on distinct HTTPS hostnames with valid certificates.
- [ ] Configure runtime/model access, registry access, and monitoring using least privilege.
- [ ] Create separate account-level RAI policy definitions for Audit and Enforced.
- [ ] Set the **network** mode explicitly; do not confuse it with the surrounding content-safety mode.
- [ ] Set default deny and an exact-host allow rule for the policy API.
- [ ] Omit the test-receiver hostname from the allowlist. Inventory any model, telemetry, and runtime dependencies; add explicit rules only where required by documented behavior.
- [ ] Read back the policy configuration after deployment and verify the attached policy reference on each agent version.
- [ ] Build and deploy the same image digest with both policy configurations. Record image digest, agent version, policy resource reference, mode, and timestamp in evidence metadata.
- [ ] Ensure each invocation selects or unambiguously reaches the intended version. If the endpoint serves only one version, switch deliberately or deploy separate named Audit/Enforced agents and document the choice.

**Exit:** Owner-approved deployment is healthy and both versions have verified policy references. Authoring success alone does not count as enforcement proof.

## Phase 5 — Verification harness

Implement `scripts/verify_demo.py` with clear pass/fail/inconclusive reporting. Local and hosted runs must be labeled separately.

### A. Independent baseline

- Confirm both endpoints respond successfully from an appropriate control client.
- Confirm receipt markers are observable at both endpoints.
- Confirm the negative endpoint is not rejecting requests through its own authorization or application logic.

### B. Hosted Audit run

- Invoke both tools from inside the deployed hosted-agent runtime.
- Confirm both requests reached their endpoints.
- Retrieve actual would-deny evidence for the unapproved destination.
- Confirm the permitted destination remains allowed.

### C. Hosted Enforced run

- Confirm the permitted tool succeeds and its API receives the marker.
- Confirm the unapproved tool attempted the request and received the documented platform-denial outcome.
- Retrieve matching platform decision evidence.
- Confirm no matching receipt appears at the test receiver over a documented bounded observation window, after checking its logging health.
- Record inconclusive if receipt logging or platform evidence is unavailable. Absence alone is not a pass.

### D. Observability checks

- Confirm ADK tool spans are distinguishable from protocol-only invocation traces.
- Confirm run/trace correlation and absence of sensitive content.
- Confirm authorized operators can inspect the evidence.
- Verify optional OTLP delivery separately, if enabled.

**Output:** Machine-readable evidence summary plus a human-readable report with real timestamps, deployment metadata, expected/actual outcomes, and evidence pointers. Include no credentials or customer content.

**Exit:** Audit and Enforced runs pass with corroborating evidence; no result is inferred solely from the model's answer or an HTTP status.

## Phase 6 — Tests and failure scenarios

Unit tests:

- [ ] Both business tools are always registered.
- [ ] URL configuration is fixed and validates distinct hosts.
- [ ] Timeouts and redirect settings are enforced; TLS verification is never disabled.
- [ ] Errors are sanitized and classified without inventing policy decisions.
- [ ] A failure in either tool does not prevent the other result.
- [ ] Logs exclude payloads, messages, secrets, and authorization headers.
- [ ] No mode-specific application denial exists.

Integration tests:

- [ ] Local baseline reaches both controlled APIs.
- [ ] Hosted Audit and Enforced behavior matches Phase 5.
- [ ] Unhealthy API, endpoint-side 403, DNS failure, and TLS failure are not classified as successful policy enforcement.
- [ ] Missing/sampled/delayed telemetry is inconclusive, not proof of allow or deny.
- [ ] Wrong agent version or wrong policy attachment is detected.
- [ ] Model-provider and telemetry connectivity remain functional under the configured policy.

Optional narrative test: use a synthetic instruction requesting the external-processor tool. Show that even an actual attempted call cannot cross the configured boundary. Do not claim comprehensive prompt-injection protection from this one test.

## Phase 7 — Demo runbook and handoff

Create `docs/demo-runbook.md` with:

1. Preflight: preview access, endpoint health, correct versions/policies, monitoring visibility, no synthetic-data capture violations.
2. Show the two ADK tools and destination policy.
3. Execute Audit; inspect successes and would-deny evidence.
4. Execute Enforced; inspect allowed success and denied attempt.
5. Correlate tool/platform/API evidence and explain operator access.
6. Explain optional export to an approved existing observability backend.
7. Close with preview limitations and the complementary-platform message.

Also deliver:

- [ ] Tested installation and local-run commands.
- [ ] Reviewed deployment/test commands with actual verified flags, not guessed syntax.
- [ ] `.env.example` containing placeholders only.
- [ ] Evidence template and captured synthetic test report.
- [ ] Resource/cost inventory and bounded teardown instructions that delete only approved demo resources.
- [ ] Known limitations and troubleshooting for startup, adapter, certificate, policy, trace, and receipt-log failures.

If live execution fails, show only previously captured, clearly dated evidence; never relabel it as a live result.

## Phase 8 — Dapr Workflow on AKS

Begin after the base containment criteria pass. Keep the ADK agent and exactly two business tools in Foundry. Replace the prior Durable Task SDK/Azure Scheduler design; do not generate either as a dependency.

### Compatibility and infrastructure gate

- [ ] Validate a compatible Dapr runtime, Python Workflow SDK, AKS version, extension/Helm version, and state-store component. Record exact versions and documentation date in `docs/compatibility.md`.
- [ ] Choose a single Dapr installation method: AKS extension or supported Helm deployment. Do not double-install the control plane.
- [ ] Add `src/workflow_app/`, `src/workflow_api/`, `tests/workflow/`, `infra/aks/`, and `infra/dapr/`, plus an independent workflow-app image.
- [ ] Evaluate PostgreSQL as the candidate actor/workflow state store. Validate required state operations, transactions, concurrency semantics, connection limits, TLS, and credential handling for the pinned version.
- [ ] Inventory required Dapr services, including placement/reminder scheduling for that version; distinguish any Dapr Scheduler from Azure Durable Task Scheduler. Validate persistence and recovery of each required stateful dependency.
- [ ] Use durable storage that survives workload pod replacement. Document database availability, backup/restore, retention, and demo versus production limitations.
- [ ] Begin with local functional tests, then deploy AKS only after owner approval. Local success does not prove AKS recovery or hybrid access.
- [ ] Configure workload identity or another validated credential for Foundry access; validate separate access to storage/telemetry. Keep credentials out of images and manifests.
- [ ] Apply namespace isolation, resource limits, private sidecar access, secrets controls, and reviewed network rules. Dapr is not an egress firewall.

### Workflow implementation

- [ ] Implement a Python servicing workflow: first agent activity -> approval event/deadline -> follow-up agent activity -> completion.
- [ ] Put model, agent, HTTP, and broker operations in activities; workflow decisions remain replay-deterministic using supported workflow time/timer primitives.
- [ ] Return bounded structured results and evidence references. Never record complete prompts, customer records, or secrets in workflow history.
- [ ] Handle approval denial/timeout explicitly; approval cannot change a Foundry egress policy.
- [ ] Persist ADK context/session references independently or use self-contained inputs. Validate continuity across the approval wait.
- [ ] Use stable workflow instance IDs and activity operation/idempotency keys. Handle duplicate events, ambiguous activity completion, and retries safely.
- [ ] Treat corroborated platform denial as an expected non-retry result; apply bounded retries only to classified transient failures.
- [ ] Ensure replicas of an app register compatible workflow/activity definitions; validate rollout/versioning behavior before changing in-flight workflow code.

### Observability and recovery test

- [ ] Enable Dapr workflow traces and application instrumentation, exporting to an approved backend. Validate activity trace context for the selected version; use case/operation IDs when native linkage is missing.
- [ ] Correlate instance, operation, attempt, ADK invocation/session, tool traces, Foundry decision evidence, and API receipt markers. Do not fabricate missing parent-child traces.
- [ ] Start a case, finish the first activity, observe approval wait, restart the workflow application pod, and leave storage intact. Submit approval and verify completion of the same instance.
- [ ] Verify checkpointed work is not unnecessarily repeated. Separately interrupt an activity before recorded completion and validate side-effect idempotency rather than claiming exactly-once execution.
- [ ] Test duplicate approval, unauthorized approval, rejected approval, expired deadline, delayed telemetry, and unavailable storage.
- [ ] Distinguish pod-restart recovery from database-loss recovery. Document storage backup/restore checks separately; do not claim protection from data loss based on a pod test.

**Exit:** A reproducible AKS workflow survives application pod replacement during a durable wait, invokes the unchanged Foundry agent, and retains inspectable evidence. Storage/operations responsibilities and known gaps are documented.

## Phase 9 — On-premises-style client through an authenticated API

Initial hybrid scope is client participation, not remote activity execution.

- [ ] Implement a narrow application-owned API: start case, query status, submit authorized event. It invokes the local Dapr Workflow client/runtime using verified APIs.
- [ ] Add `samples/onprem_client/` for a separately running agent companion/client. No Dapr install or A2A protocol is required on that client.
- [ ] Keep raw Dapr sidecar HTTP/gRPC and administrative APIs private. Do not copy a sample that publicly exposes sidecar management endpoints.
- [ ] Authenticate callers and enforce case ownership, event authority, allowed workflow types, schema/body limits, rate limits, and duplicate/replay handling. An agent may not self-authorize human approval.
- [ ] Validate approved on-premises-to-AKS routing/DNS, API TLS, identity/token renewal, ingress authorization, and reconnect behavior. Private routing alone does not provide authorization.
- [ ] Use only synthetic metadata and opaque references; document where API payloads, history, agent context, and telemetry are stored.
- [ ] Demonstrate client start/query/event against the same workflow instance. The Foundry agent remains the runtime for the two-tool containment proof.
- [ ] Extend `docs/workflow-runbook.md` with cluster/sidecar/state preflight, pod-restart test, API examples, monitoring queries using real fields, and safe cleanup.

**Exit:** A separate client participates without A2A, without a local Dapr dependency, and without public sidecar access.

## Phase 10 — Deferred outbound bridge and on-premises portability

Neither is required for the initial Dapr extension. Obtain separate approval before implementing.

### Optional request/result bridge

- [ ] If AKS cannot call on-premises, select an approved broker/transport and build an explicit request/result adapter.
- [ ] Publish work requests with workflow instance and stable operation IDs. A local consumer executes local ADK work and returns a bounded result; an AKS adapter validates it and raises the matching event.
- [ ] Authenticate producers/consumers; enforce operation allowlists, replay/deduplication, deadline/late-result rules, poison-message handling, and idempotency.
- [ ] Choose durability and retry ownership deliberately; successful publication is not proof of local execution. Do not assume Dapr pub/sub automatically maps messages into workflow events.
- [ ] Document data crossing each boundary. Keep this integration separate from the Foundry containment experiment and its two registered tools.

### On-premises Dapr/ADK comparison

- [ ] Validate Dapr deployment and workflow-compatible state storage on the actual Kubernetes/OpenShift platform.
- [ ] Validate identity, local state/context, runtime services, certificates, networking, operations, backup, and telemetry separately.
- [ ] Do not assume a shared workflow app spans disconnected clusters or supports site-targeted activity scheduling. Validate any multi-app/cross-cluster feature for the pinned runtime before using it.
- [ ] Replace the containment proof with independently tested local controls if ADK moves outside Foundry.
- [ ] Distinguish local execution, local history, and cloud dependencies. AKS success is not OpenShift certification, data-residency assurance, or an air-gapped claim.

**Exit:** Separately labeled and tested integration/portability evidence, without asserting automatic security or recovery equivalence.

## Definition of done

The owner can reproduce one ADK agent with two unchanged business tools in a real Foundry hosted runtime, show permitted versus denied outbound destinations, and inspect corroborating evidence. The repository clearly separates tested results from proposed behavior and preview capability from production guarantees.

### Extended definition of done

In addition to the original containment criteria, a Python Dapr Workflow application on AKS resumes the same case after pod restart during approval wait, using intact persistent storage. A separate on-premises-style client starts/queries/signals the case through a secured API without A2A. State-store operations, idempotency, access control, and trace linkage are verified. Azure Durable Task Scheduler is not required. Messaging bridge and local Dapr/ADK deployment remain deferred.

## First GitHub Copilot task

```text
Read README.md and PLAN.md. Begin with Phase 0 and create docs/compatibility.md.
Then implement the local scaffold, the two Google ADK business tools, controlled
API services, unit tests, and the authenticated diagnostic execution path.
Validate current Foundry protocol/model adapters and package versions. Do not
invent SDK methods or monitoring fields. Keep both tools registered; do not
implement application-only denial. Do not provision Azure resources or export
data to a new service without approval. Mark unavailable preview features as
blocked, and label local tests as functional tests, not network containment proof.
Summarize what is implemented, what is tested, and the next approval-gated step.
```

## GitHub Copilot task for the Dapr extension

```text
Read README.md and Phases 8–10 of PLAN.md. Implement Phase 8 first using a
Python Dapr Workflow app on AKS with a persistent compatible state store; evaluate
PostgreSQL. Do not use Azure Durable Task Scheduler or its SDK. Validate and pin
compatible Dapr runtime, Python SDK, installation method, and state component.
Keep our existing Foundry-hosted Google ADK agent and its two business tools.
Invoke it from activities, wait for authenticated approval with a durable deadline,
and test replacement of the workflow pod while storage stays intact. Verify
idempotency of retried activities and distinguish expected platform denial from
transient failure. Instrument real workflow and agent evidence; do not invent
SDK APIs, state-store compatibility, or trace propagation.
Then implement Phase 9: a secured start/status/event API and separate client
sample that needs neither Dapr locally nor A2A. Keep sidecar management ports
private and enforce case/event authorization. Do not deploy resources or change
access policies without approval. Keep Phase 10 messaging and OpenShift/local
runtime options deferred. Report implemented, tested, blocked, and unverified work.
```
