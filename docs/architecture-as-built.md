# Architecture

Updated 2026-11-10. The existing identity/egress baseline is tested
(owner-confirmed 2026-11-06). The original ACS publication remains pinned v4.
The separate OAuth publication is pinned v1; authorized lookup and ACS-blocked
sending through Copilot have [dated evidence](telemetry-map.md#isolated-copilot-acceptance).
Negative identity acceptance is deferred; original AKS/UI runtime regression is pending.

![Copilot OAuth and ACS flow](diagrams/copilot-oauth-flow.svg)

[Editable Excalidraw source](diagrams/copilot-oauth-flow.excalidraw) and
[diagram legend](diagrams/README.md). This is a dated architecture map, not evidence.

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

Microsoft 365 publication and the ACS-first chat path were observed working on
2026-11-09 with version 3. The reply's run marker matched an ACS `deny` / `blocked`
event for external processing; see the [dated observation](telemetry-map.md#microsoft-365-copilot-blocked-action-observation).
This path does not replace ADK or move the business tools outside Foundry.

The baseline agent versions share an immutable image digest. The attached RAI
network policy is the experimental variable; `DEMO_POLICY_MODE` is an evidence
label, never a tool implementation branch.

Exactly two business tools are registered in every mode. Both use fixed startup
destinations, verified TLS, bounded timeouts and disabled redirects. The
authenticated diagnostic route reuses those implementations.

## Microsoft 365 Copilot runtime path

```text
End user: Microsoft 365 Copilot -> Your agents
  -> ACS OAuth Servicing Demo (separate project/publication, pinned v1)
  -> Microsoft's channel infrastructure
  -> Foundry's authenticated Activity endpoint
  -> stable agent endpoint, pinned to the reviewed hosted version
  -> Responses adapter in the Foundry-hosted Python container
  -> Google ADK runner
       -> Azure-hosted model, authenticated as the agent using Entra
       -> model proposes a registered business tool
       -> ACS pre-tool callback evaluates the Rego policy through OPA
            allow lookup -> managed-identity toolbox caller + trusted user context
              -> immutable toolbox v2 -> custom OAuth connection
              -> delegated token -> protected MCP on Azure Container Apps
            deny  -> structured blocked result; no business HTTP call
       -> model explains the actual tool result
  -> Responses text -> Foundry channel -> reply in Microsoft 365 Copilot
```

**No AKS endpoint is in this chat request path.** The AKS web UI, A2A facade and
optional local model are separate baseline clients. The private AKS helper runs
operator deployment/publication commands because it can reach Foundry's private
management endpoint; it does not relay Copilot messages. No AKS ingress or
port-forward is needed to chat with the published agent.

The Activity exception permits authenticated Microsoft channel traffic through
Foundry's service-source-IP filter. Operator Responses/management operations use
the private helper path. The current account retains the owner's separately
approved **public access Enabled, selected-IP ACL/default Deny** configuration;
do not describe it as account-wide public access Disabled. Inbound reachability,
outbound managed networking and RAI egress are independent controls.

Copilot sign-in authorizes channel access, not the agent's model call or a protected
downstream API call. The hosted agent uses its own Entra credential for the model.
Successful lookup in **ACS OAuth Servicing Demo** uses the real connection's
interactive browser consent and delegated scope. The MCP validates the token and
explicitly authorized user; consent alone does not grant service access.
The toolbox caller uses managed identity and platform-authenticated per-request
user/call context, not a fabricated user ID, static user token or operator fallback.
Exactly two business tools remain registered; only the lookup transport is different
in the dedicated image/configuration.

The original **ACS Servicing Demo** remains separate and uses the direct-HTTP
lookup transport without this channel's delegated connection. Its observed 401
must not be treated as an OAuth failure in the isolated publication.

The Responses handler creates a fresh `chat-<uuid>` marker and appends **Demo run:**
to its reply. A missing reply or marker is not an ACS result. Correlate application
exceptions first; only a model-selected tool and recorded ACS decision establish
that governance was exercised. See [Copilot failure diagnosis and recovery](governance-demo.md#copilot-runtime-failure-and-image-updates).

## Components

| Component | Runtime / ownership | Source and operator tasks |
| --- | --- | --- |
| Baseline ADK agents | Foundry hosted containers | `src/containment_demo/`; `build:foundry-agent`, `deploy:foundry-agent` |
| Seven isolated governance agents | Same governed image digest; separate agent names | `governance/hosted.py`; `acs:build`, `acs:deploy`, `acs:status` |
| OAuth Copilot agent/publication | Dedicated project/image; active v1, separate Just you title | `copilot_toolbox.py`; `copilot-toolbox:up`, `publish-plan`, `publish`, `status` |
| Toolbox / OAuth connection / protected MCP | Immutable toolbox v2, delegated consent, separate authorized-user list | `toolbox.py`, `copilot_toolbox_setup.py`, `services/policy_api/`; `copilot-toolbox:infra-up` |
| Isolated infrastructure/policy | Separate Terraform state; existing telemetry destination | `infra/copilot-toolbox/`; `copilot-toolbox:plan`, `infra-up`, `down` |
| ACS / Rego / OPA | Inside the hosted container; application governance | `governance/`, `policies/acs/` |
| Baseline RAI policies | Foundry account; existing Terraform declarations | `infra/cloud/rai-policies.tf`; preserve externally managed live settings |
| Three governance policies | Separate Terraform state; live baseline content filters copied | `infra/governance/`; `acs:up` |
| Policy API and receiver | Azure Container Apps | `services/`; `build:tool-apis`, `deploy:tool-apis` |
| Governance publisher | Private AKS helper, workload identity | `scripts/governance_manifest.py`; `acs:deploy`, optional `acs:copilot` |
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
The separate Copilot toolbox path supplies downstream delegation without copying
the baseline UI/OBO registration or sending its bearer tokens to the agent.

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
Prompt/response/payload/token capture stays disabled. The version 3 governance
logger mapping was observed in `AppTraces`; other event mappings and the full
hosted comparison remain separate validation gates. The isolated v1 lookup and
blocked-send observations include actual ACS/tool events, MCP receipts and a
mature receiver-absence window; see the telemetry map. ACS denial is not a
platform egress-denial result.

## Operations and deferred components

Use [rebuild-runbook.md](rebuild-runbook.md) for Task ordering and guarded cleanup.
The AKS harness and local model are optional clients, not prerequisites for the
Microsoft 365 experience. They are outside Foundry's egress boundary.

Dapr Workflow, its persistent state store, human approval resolution, APIM,
messaging bridges and true on-premises/OpenShift portability are deferred.
The current [Copilot diagram](diagrams/README.md) covers delegated lookup, ACS,
evidence and operator deployment. Older environment pictures describe the October
baseline only, not current Copilot rollout status.
