# Framework-neutral agent containment demo

## Purpose

Build a small Python agent using Google Agent Development Kit (ADK), deploy it as a Microsoft Foundry hosted agent, and demonstrate platform-managed HTTP/HTTPS egress enforcement plus operational evidence.

The message: **Keep your agent framework; manage the outbound boundary independently and inspect the evidence.** This is a complementary platform pattern, not a replacement for an existing enterprise agent platform.

This repository is a proposed build specification, not a tested deployment. Follow `PLAN.md` to implement and validate it.

> **Preview warning:** The Microsoft Foundry egress walkthrough dated September 24, 2026 describes network egress controls as preview, without a preview SLA, and not intended for production. Recheck availability and restrictions before building. Do not present this demo as a production assurance or compliance certification.

## Demo scope

Exactly two business tools remain registered and callable in ADK in every mode:

| Tool | Behavior | Destination policy |
| --- | --- | --- |
| `get_servicing_policy` | Retrieves a synthetic servicing policy from a controlled HTTPS API | Explicitly allowed hostname |
| `send_to_external_processor` | Sends a harmless synthetic test record to a second controlled HTTPS API | Hostname omitted from the allowlist; default deny applies |

“Approved” means **the destination is permitted by the hosted agent's egress policy**. It does not mean Foundry has semantically approved the tool or granted API authorization. Use different hostnames; this is not a path-based allowlist demo.

## Proposed architecture

```text
Demo client
    |
    v
Foundry hosted-agent endpoint
    |
    v
Python container: protocol adapter -> ADK runner -> two HTTP tools
    |
    v
Foundry-managed egress policy
    |-- permitted hostname -> synthetic policy API
    |-- unapproved hostname -> controlled test receiver

Evidence: ADK/tool traces + platform egress decisions + endpoint receipt logs
Telemetry destination: Application Insights; optional approved OTLP collector
```

Both APIs are reachable and healthy independently of the agent. Neither API deliberately denies the negative test. Therefore, an API authorization error cannot masquerade as successful network containment.

Use a Foundry-hosted model where feasible so framework choice is separated from model-provider choice. Validate the ADK model adapter rather than assuming a native integration. Do not enable Google telemetry export by default.

## Demonstration sequence

1. Show both ADK tool definitions and the external destination policy.
2. Invoke both tools through the **deployed hosted-agent runtime** using a deterministic test path.
3. Under **Audit**, expect both controlled APIs to receive their requests. Inspect would-deny evidence for the unapproved destination.
4. Under **Enforced**, expect the permitted call to succeed and the unapproved call to be denied by the platform. Confirm that the second API received no matching request.
5. Show the correlated tool attempt, egress decision, and API receipt evidence.
6. Explain how an authorized operations team can inspect Application Insights and optionally receive telemetry through an approved OpenTelemetry destination.

Use separate Audit and Enforced policy resources and immutable agent versions. Run each test against an explicitly identified version, not an assumed latest deployment. Both versions must use the same image digest and tool configuration; the egress policy is the experimental variable.

### Expected results—not captured evidence

| Mode | Permitted tool | Unapproved tool |
| --- | --- | --- |
| Local baseline | API succeeds; receipt logged | API succeeds; receipt logged |
| Hosted Audit | API succeeds; receipt logged | API succeeds; receipt logged; would-deny evidence |
| Hosted Enforced | API succeeds; receipt logged | Platform denial; matching decision evidence; no API receipt |

The documented walkthrough describes proxy HTTP 403 for the enforced negative test. A bare 403, DNS error, timeout, model refusal, or missing log is **not** proof of containment. Treat missing evidence as inconclusive.

## Observability requirements

Implement three distinguishable evidence layers:

- **Agent/application:** agent run, ADK tool invocation, duration, destination hostname, HTTP outcome, and error category.
- **Platform:** available Foundry egress decision evidence, with the real field names discovered during validation.
- **Destination:** receipt events at each controlled API, using a synthetic correlation marker.

Proposed application fields: `demo_run_id`, `trace_id`, `agent_name`, `agent_version`, `policy_mode`, `tool_name`, `destination_host`, `duration_ms`, `http_status`, and `error_category`. These are our application schema, not guaranteed platform fields. Do not synthesize a platform policy decision in application logs.

ADK has OpenTelemetry instrumentation; Foundry protocol libraries provide runtime telemetry. Verify their provider/exporter integration and trace correlation rather than assuming all ADK internal spans automatically appear in Foundry. Avoid duplicate tracer providers and duplicate export.

Enable project monitoring for Application Insights. Optional OTLP export must target an approved collector. Test whether the egress configuration permits telemetry delivery. Do not assume platform egress decision records are included in every application OTLP export; verify their actual source and export path separately.

Use full trace sampling for synthetic demo runs where supported. Disable prompt, response, payload, credential, and authorization-header capture. Give viewers least-privilege read access to the chosen monitoring resources.

## Build prerequisites

- A test Azure subscription, Foundry project, and supported hosted-agent region.
- Confirmed access to the egress preview in that environment.
- Permission to create an account-level RAI policy and deploy hosted-agent versions.
- Azure Container Registry and a container-build workflow.
- A Foundry model deployment compatible with the validated ADK adapter.
- Two distinct HTTPS hostnames under our control, with valid certificates and observable receipt logs.
- Application Insights/project monitoring; optional approved OTLP collector.
- Local Python, container tooling, and Azure deployment tooling. Pin versions after the compatibility spike.

Keep real resource values in local configuration. Commit `.env.example` with placeholders only. Use managed identity and supported project connections for credentials; do not put secrets in source, images, or committed deployment files.

## Suggested repository structure

```text
README.md
PLAN.md
pyproject.toml
.env.example
.gitignore
Dockerfile
src/containment_demo/
  agent.py
  tools.py
  protocol_adapter.py
  diagnostics.py
  telemetry.py
  settings.py
services/
  policy_api/
  test_receiver/
infra/
  policies/
  deployment/
scripts/
  preflight.py
  deploy.py
  verify_demo.py
tests/
  unit/
  integration/
docs/
  demo-runbook.md
  telemetry-map.md
  evidence-template.md
# Dapr extension adds:
src/workflow_app/
src/workflow_api/
samples/onprem_client/
infra/aks/
infra/dapr/
tests/workflow/
docs/workflow-runbook.md
```

## Security and testing rules

- Synthetic data only. No customer records, bank credentials, or confidential platform details.
- Register both tools in every mode; no conditional removal, code allowlist, or prompt-only block.
- Use bounded timeouts and disabled redirects; keep TLS verification enabled and use the documented runtime CA handling.
- Do not expose a public arbitrary-URL probe. Diagnostic execution is authenticated and restricted to the two configured destinations.
- Tool failures are captured independently so the blocked call does not suppress the permitted test.
- Keep network destination permission, API authorization, and data-validation responsibilities distinct.
- This proves the configured hosted-runtime HTTP/HTTPS path only—not arbitrary protocols, every exfiltration route, or production compliance.

## Acceptance criteria

- [ ] ADK executes inside a real Foundry hosted-agent container through a supported protocol adapter.
- [ ] Exactly two business tools remain registered in Audit and Enforced modes.
- [ ] Both endpoints pass independent baseline health/receipt checks.
- [ ] Audit produces successful calls and identifiable would-deny evidence.
- [ ] Enforced preserves the permitted call and blocks the unapproved destination with corroborating evidence.
- [ ] The negative test is not an application check, prompt refusal, or endpoint-side authorization failure.
- [ ] Application/tool traces and platform decision evidence can be inspected by authorized viewers.
- [ ] Trace correlation and any OTLP export claims have been tested and documented.
- [ ] Setup, test, teardown, and demo instructions are reproducible; unsupported features are disclosed.

## Extension: Dapr Workflow on AKS

### Recommended next build

Keep Google ADK and both business tools in Foundry hosted agents. Add a Python Dapr Workflow application on AKS, with a Dapr sidecar and a persistent, workflow-compatible state store. **Azure Durable Task Scheduler and its SDK are not dependencies of this design.** Dapr's own runtime infrastructure is distinct from the Azure managed Scheduler service.

```text
On-premises agent / demo client
           |
Authenticated, case-authorized workflow API
           |
AKS: Python workflow application + Dapr sidecar
           |-- Persistent workflow state store
           |-- Activity -> Foundry-hosted ADK agent
           |                 `-- Existing two-tool egress demonstration
           `-- Approval event / deadline -> follow-up activity -> completion
```

Use PostgreSQL as the candidate state store. Validate compatibility with the selected Dapr runtime/SDK, actor-state requirements, transactions, concurrency, and durability configuration before adoption. Demo storage must survive pod restart; an ephemeral database is not a recovery proof. Pin a mutually compatible runtime, Python Workflow SDK, AKS extension or Helm release, and state-store component. Pick one installation method; do not install overlapping Dapr control planes.

Proposed case flow:

1. Start a synthetic servicing case with a stable workflow instance ID.
2. An activity invokes the unchanged hosted ADK agent, retrieving policy and attempting the unapproved tool.
3. Record a verified network denial as an expected result, not a retryable transient fault.
4. Wait for an authenticated approval event with a durable deadline.
5. Restart the workflow application pod while the case waits; leave persistent storage intact.
6. Submit approval, resume the same instance, invoke a follow-up agent activity, and complete with evidence references.

Approval changes workflow status, never network permission. Durability is at workflow/activity boundaries, not automatic checkpointing of all internal ADK reasoning or tools. Keep workflow logic deterministic and agent/HTTP calls in activities. Design for retried activities and idempotent side effects. Persist ADK context explicitly or make each activity self-contained.

### On-premises participation without A2A

**Initial scope: authenticated API client.** An on-premises agent or companion service starts cases, queries status, and submits authorized events through an application-owned API in front of Dapr. The agent need not adopt Dapr or hand off to another agent. This API must enforce instance ownership, allowed operations, schema limits, and approval authority. Never expose raw Dapr sidecar or administrative ports publicly.

**Optional outbound-only bridge:** If AKS cannot call on-premises, publish a request to an approved broker. A local consumer executes the local agent and publishes a result. An AKS adapter validates the result and raises a workflow event. Implement correlation, deduplication, deadlines, late-result handling, and poison-message handling. This is an application messaging pattern, not automatic cross-cluster workflow routing; select the broker and transport only after approval.

The bridge is a separate integration sample. Keep the Foundry ADK agent's exactly two business tools unchanged; do not replace the containment proof with a local tool execution.

### State, security, and observability responsibilities

Dapr runs workflow execution through its runtime and persists progress in a configured state store. We operate AKS, Dapr infrastructure, storage, credentials, backup/recovery, upgrades, and retention. AKS-hosted workflows do not imply on-premises state residency. Minimize history inputs/results to synthetic metadata and opaque references; separately document where agent memory and workflow history reside.

Dapr provides workflow tracing. Validate SDK/version-specific activity context propagation; do not assume one continuous trace crosses every approval wait or remote agent call. Correlate workflow instance ID, activity operation/attempt, ADK invocation/session, tool trace, platform decision, and endpoint receipt marker. Export only to approved destinations, with payload capture disabled.

Dapr service invocation security is not a general network egress firewall. Keep Foundry hosted-agent egress for the original two-tool proof and separately configure/test AKS application outbound controls, identity, secrets, and private connectivity. Account for Foundry/model, state store, telemetry, and approved broker dependencies.

### Deferred portability comparison

Running Dapr Workflow and/or ADK on on-premises Kubernetes/OpenShift is a later deployment validation, not demonstrated by AKS success. Validate runtime/control-plane compatibility, storage, identity, networking, and operations separately. Do not assume a single Dapr app spans disconnected clusters or can route activities to a chosen site automatically. Foundry containment does not follow an agent moved to local compute. A fully local design requires locally validated state/runtime dependencies and is not an air-gapped promise.

### Additional prerequisites and acceptance criteria

- AKS test environment, approved Dapr installation, persistent compatible state store, and an authenticated workflow API.
- Permissions for cluster deployments, approved runtime identities, storage access, private routing/DNS, and monitoring.
- [ ] Workflow activities invoke the unchanged Foundry ADK agent and preserve its containment evidence.
- [ ] The same case survives workflow pod restart during approval wait, with the state store intact.
- [ ] Denial, duplicate approvals, timeout, and activity retries have explicit safe outcomes.
- [ ] Agent context and workflow state have independent tested persistence strategies.
- [ ] A separately running on-premises-style client starts/queries/signals a case without A2A.
- [ ] Raw sidecar management interfaces remain private; case-level authorization is tested.
- [ ] State-store durability/backup, workflow retention, and trace linkage are documented.
- [ ] Optional bridge and OpenShift/full-local deployment remain deferred unless separately approved.

## Start with GitHub Copilot

Open this repository and ask:

> Read README.md and PLAN.md. Implement Phase 0 first, then the local scaffold and tests. Keep Google ADK and both business tools. Do not replace platform egress enforcement with application checks, invent SDK APIs, or deploy Azure resources without my approval. Record validated package versions, protocol/model integration, preview availability, and telemetry fields. If a required platform feature is unavailable, stop that portion and report the blocker; never label local simulation as Foundry enforcement.

After the base containment acceptance criteria pass, implement Phases 8–9 in PLAN.md using Dapr Workflow on AKS. Keep the messaging bridge and on-premises runtime comparison in Phase 10 deferred.

## References

Recheck these primary sources at implementation time; this specification was prepared October 7, 2026.

- Microsoft Learn, **Hosted agents in Foundry Agent Service**: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents
- Microsoft Foundry Blog, **Control where your hosted agent connects with network egress in Foundry Agent Service**, September 24, 2026: https://devblogs.microsoft.com/foundry/egress-controls-hosted-agent/
- Microsoft Learn, **Export hosted agent telemetry by using OpenTelemetry**: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-hosted-agent-telemetry
- Microsoft Learn, **Deploy and run workflows with the Dapr extension for AKS**: https://learn.microsoft.com/en-us/azure/aks/dapr-workflow
- Microsoft Learn, **Install Dapr Extension for AKS and Arc-enabled Kubernetes**: https://learn.microsoft.com/en-us/azure/aks/dapr
- Dapr Docs, **Workflow overview**: https://docs.dapr.io/developing-applications/building-blocks/workflow/workflow-overview/
- Dapr Docs, **Workflow architecture**: https://docs.dapr.io/developing-applications/building-blocks/workflow/workflow-architecture/
- Google ADK, **Traces**: https://adk.dev/observability/traces/
- Google Cloud, **Instrument ADK applications with OpenTelemetry**: https://docs.cloud.google.com/stackdriver/docs/instrumentation/ai-agent-adk
