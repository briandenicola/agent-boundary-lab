# Architecture

Updated 2026-11-09. The existing identity/egress baseline is tested
(owner-confirmed 2026-11-06). The isolated ACS backend is deployed; new channel and
runtime results must be validated independently.

## Execution and boundaries

```text
Baseline browser harness on AKS
  -> A2A facade on AKS
  -> private Foundry Responses endpoint
  -> hosted Python container: Responses adapter -> Google ADK
       -> ACS pre-tool evaluation and host enforcement (optional)
       -> get_servicing_policy       -> protected servicing API
       -> send_to_external_processor -> unauthenticated test receiver
            ^
            Foundry platform egress policy governs these outbound HTTP calls

Microsoft 365 Copilot integration
  -> Foundry Activity channel -> same hosted ADK runtime
```

The Microsoft 365 path is the current integration work, not a validated deployed
channel. It does not replace ADK or move the business tools outside Foundry.

The baseline agent versions share an immutable image digest. The attached RAI
network policy is the experimental variable; `DEMO_POLICY_MODE` is an evidence
label, never a tool implementation branch.

Exactly two business tools are registered in every mode. Both use fixed startup
destinations, verified TLS, bounded timeouts and disabled redirects. The
authenticated diagnostic route reuses those implementations.

## Components

| Component | Runtime / ownership | Source and operator tasks |
| --- | --- | --- |
| Baseline ADK agents | Foundry hosted containers | `src/containment_demo/`; `build:foundry-agent`, `deploy:foundry-agent` |
| Seven isolated governance agents | Same governed image digest; separate agent names | `governance/hosted.py`; `governance:build`, `governance:up`, `governance:status` |
| ACS / Rego / OPA | Inside the hosted container; application governance | `governance/`, `policies/acs/` |
| Baseline RAI policies | Foundry account; existing Terraform declarations | `infra/cloud/rai-policies.tf`; preserve externally managed live settings |
| Three governance policies | Separate Terraform state; live baseline content filters copied | `infra/governance/` |
| Policy API and receiver | Azure Container Apps | `services/`; `build:tool-apis`, `deploy:tool-apis` |
| Governance publisher | Private AKS helper, workload identity | `scripts/governance_manifest.py`, `tasks/Taskfile.governance.yml` |
| Baseline harness / bridges | AKS, standing in for an on-premises caller | `harness/`, `a2a_facade/`; `deploy:chat-agent`, `deploy:agent-bridge` |
| Optional CPU model / two-button UI | Baseline AKS client components | `deploy:model-server`, `deploy:test-ui` |
| Evidence | Application Insights and Log Analytics | `verify_demo.py`, `verify_governance.py`, [telemetry map](telemetry-map.md) |

Read current resource names, versions and digests from state and deployment readback,
not from old resource URLs. The default region is Sweden Central.

## Identity

The baseline HTTPS harness uses Entra sign-in through oauth2-proxy.
MSAL exchanges the incoming user assertion for the protected policy API scope.
The downstream token travels through the facade and Foundry's `x-client-*` header
forwarding into request-scoped ADK state. The policy API checks the token and the
authorized synthetic-user list. See [token flow](token-flow-documented.md).

Actor aliases are display labels, never authorization inputs. The receiver deliberately
has no authorization gate: its rejection must not masquerade as platform containment.

Microsoft 365 channel authorization and downstream policy API authorization are
separate contracts. The direct-client forwarding headers do not establish channel
token delivery.

## Independent controls

| Control | Enforcement point | What it does not prove |
| --- | --- | --- |
| Entra / API authorization | Ingress and protected policy API | Outbound containment |
| ACS | ADK pre-tool callback and shared diagnostic mediator | A platform network denial |
| RAI egress policy | Foundry hosted sandbox outbound HTTP/HTTPS | Protection of AKS callers or arbitrary protocols |
| Private endpoint / PNA | Foundry inbound reachability | Outbound containment |
| Managed network | Foundry runtime network | That a particular RAI rule caused an observed failure |

Both API hosts are permitted by the managed network. The RAI policy omits the receiver
only in network-denial scenarios. ACS governance-denial uses a policy permitting both
APIs, so its blocked send is attributable to ACS rather than the network.

Native inbound A2A to a hosted target returned `HOSTED_AGENT_NOT_SUPPORTED` in the
2026-10-09 spike. The baseline uses an application-owned A2A facade over Responses;
it must not be described as native hosted-agent A2A.

## Evidence

The observed platform source is `AppDependencies` with
`DependencyType == "NetworkEgressDecision"`. `Data` / `Properties.path` retain the
run marker in `/policy/{run_id}` and `/ingest/{run_id}`. `OperationId` did not join
platform decisions to application spans in the recorded baseline.

Receipts are JSON in `ContainerAppConsoleLogs_CL.Log_s`. A missing receiver receipt
counts only after a mature ingestion window, with a successful servicing receipt and
no unattributed arrivals. `/healthz` is not a receipt positive control.

ACS has its own decision events; it does not emit synthetic platform decisions.
No platform row is expected for a tool ACS prevented from executing. A model's
explanation, HTTP 403, DNS error or timeout alone is not proof of either control.

The platform injects its reserved Application Insights connection setting.
Prompt/response/payload/token capture stays disabled. New hosted ACS event mappings
still need real-row validation.

## Operations and deferred components

Use [rebuild-runbook.md](rebuild-runbook.md) for Task ordering and guarded cleanup.
The AKS harness and local model are optional clients, not prerequisites for the
Microsoft 365 experience. They are outside Foundry's egress boundary.

Dapr Workflow, its persistent state store, human approval resolution, APIM,
messaging bridges and true on-premises/OpenShift portability are deferred.
Older Excalidraw/SVG environment pictures describe the baseline only; this text is
the current control-boundary reference.
