# Runtime and platform contracts

Use `pyproject.toml`, `uv.lock`, and the Dockerfiles for dependency versions.
This page records the less obvious contracts the demo relies on.
[Deployment steps](rebuild-runbook.md) · [Run evidence](telemetry-map.md)

## Runtime

| Component | Pin or requirement |
| --- | --- |
| Python | 3.12 |
| Google ADK | 2.12.0; async `before_tool_callback` |
| Model clients | LiteLLM 1.83.0, OpenAI 3.31.0 |
| Foundry Responses server/core | 2.2.0; hosted protocol **2.0.0**, not `v1` |
| Azure AI Projects | 2.8.0 |
| ACS | `agent-control-specification==0.3.1b1`; manifest `0.3.1-beta` |
| OPA | 1.9.0, static Linux x86_64 |
| Governed-image uv | 0.9.7; locked sync |
| OpenTelemetry | Deliberate `>=1.43,<2` dependency override |
| A2A | a2a-sdk 1.0.2; protobuf below 7 |
| Policy identity | PyJWT 2.15.1, cryptography 50.0.2, httpx 0.28.1 |

ADK and the Foundry server need the OpenTelemetry override to coexist.
The image separates agent and deployment dependencies into `/opt/agent-venv`
and `/opt/deploy-venv`. LiteLLM also imports MCP types for ordinary function tools.

## Model authentication

For Azure OpenAI v1, LiteLLM drops `azure_ad_token_provider` in its standard-client
branch. The application supplies an explicit async OpenAI client with an async
bearer-token provider passed as `api_key`. This is Entra authentication, not an
API key. Dated APIs use the Azure client and `azure_ad_token_provider`.

Both use `DefaultAzureCredential`, refreshing tokens for the Cognitive Services
audience. Requests have a 60-second timeout and no retries. The v1 fix was exercised
by successful hosted Copilot turns on **2026-11-09/10**.

## ACS

The published release uses `AgentControl.from_path` and async
`evaluate_intervention_point(point, snapshot, mode)`, with `pre_tool_call` and
`enforce`. The host implements Audit and Disabled behavior.

| Verdict | Host behavior |
| --- | --- |
| allow / warn | Continue |
| deny | Block in Enforced; record and continue in Audit |
| escalate | Block as approval-required in Enforced |
| transform | Accept only a validated empty-argument replacement |
| Evaluation error | Record separately; fail closed in Enforced |

ADK awaits the callback; a non-None result prevents execution.
Diagnostics call the same mediator explicitly. `runtime_error:` reasons remain
evaluation errors, not ordinary policy denial.

The SDK captures `ACS_OPA_PATH` and `ACS_OPA_TIMEOUT_MS` at construction.
The host bounds both its async wait and the OPA subprocess. A late evaluation
cannot restart a blocked tool call. Restart after changing policy artifacts.

The wheel requires Linux x86_64, CPython 3.11 ABI3, and glibc >=2.28.
Preparation refuses unsupported source builds.

| Artifact | SHA-256 |
| --- | --- |
| OPA binary | `66fa66f3b730b2fb086003863428b382b2898d343adb4b5dfab5598b4d739eed` |
| ACS wheel | `a0eea57016fc4cf3c620d92b81ad8c7b1376aa2865991a561ea6a427cb1451be` |

The manual `requires_action` helper `guard_foundry_agent` is not used.
There is no approval resolver, remote policy bundle, or post-tool hook.

## Foundry deployment

| Contract | Requirement |
| --- | --- |
| Agent lifecycle | Project data-plane API `v1`; private helper for restricted access |
| Hosted protocol | `2.0.0`; `v1` fails at invocation |
| Image | `repo@sha256:<64 hex>`; accepted in live deployment |
| Policy binding | Full ARM ID in `definition.rai_config.rai_policy_name` |
| Model access | Grant the agent's identity, not only the publisher |
| Telemetry setting | Platform injects reserved `APPLICATIONINSIGHTS_CONNECTION_STRING` |
| Invocation | Named agent endpoint; check the served version in evidence |
| Lifecycle writes | Bounded requests; read back uncertain writes before retrying |
| Native inbound A2A | Returned `HOSTED_AGENT_NOT_SUPPORTED`; use the application bridge |

Go Task's embedded shell does not implement `umask`. Private-journal commands
run in `/bin/sh`, using mode-600 temporary files and atomic replacement.

## Publication

Both entries use **Shared / Just you**. Publishing preserves Responses/Entra,
adds scoped Activity/BotServiceRbac access, and pins the reviewed hosted version.
An upgrade changes the pin without creating another catalog entry.

Publication uses an Azure CLI user token for `https://ai.azure.com`, not the
helper's workload identity. A private journal records the original endpoint
and pending writes. Uncertain requests stop instead of automatically repeating.
Disabling restores the endpoint; catalog removal is separate.

Headerless chat turns receive a fresh `chat-<uuid>` marker in the reply.
Direct-client markers retain their existing contract.

## Network and monitoring

The default region is **Sweden Central**, with `Standard_D4as_v7` AKS nodes.
Quota and preview availability must be checked for each subscription.

Terraform defaults public access to Disabled. The recorded Copilot environment
uses Enabled with selected-IP/default-Deny ACLs. Managed isolation is
`AllowOnlyApprovedOutbound`; both business hosts are allowed there.

RAI policies use `2026-05-15-preview`. `properties.mode` is content safety;
`properties.egressPolicy.mode` is network enforcement. Custom policies require
`basePolicyName`, `contentFilters`, and `type: UserManaged`; filters are not
inherited. Preserve externally managed settings when updating an environment.

Foundry's managed-network ACR endpoint is separate from AKS's endpoint.
The account identity needs **Azure AI Enterprise Network Connection Approver**
on ACR and **Reader** on its resource group.
[Declared configuration](../infra/cloud/managed-network.tf)

Platform decisions arrive in `AppDependencies` through the project Application
Insights connection. Resource diagnostics and AKS collection are separate.
Diagnostics omit `logAnalyticsDestinationType` because Azure returned null for
`Dedicated`. AKS excludes `ContainerInventory` to avoid environment capture.
Custom OTLP carriage and raw managed-firewall logs are not established evidence.

## Toolbox and OAuth

External tools in an isolated project require a **project-level capability host**.
The account-level host alone is insufficient. Projects still share managed
networking. The workflow requires the existing ready platform-managed account host.

| Resource | API |
| --- | --- |
| Project / managed-network outbound rule | `2025-10-01-preview` |
| Capability host | `2025-06-01` |
| RAI policy / project connection | `2026-05-15-preview` |
| Container App | `2025-01-01` |
| Role assignment | `2022-04-01` |
| Entra application and credentials | Microsoft Graph `v1.0` |

The dedicated OAuth client requests the API's delegated `policy.read` scope and
`offline_access`. ARM uses a scopes array; the portal uses a space-separated string.
The redirect URI comes from the real connection response.

Connection readback can report unsupported-target metadata even when OAuth works.
In the recorded setup, `peRequirement` and `peStatus` were `NotApplicable`.
Readiness requires functional discovery and lookup, not just those metadata fields.

`MCPToolboxTool` uses `server_label`, `server_url`, `require_approval`, and
`project_connection_id`. Call the immutable version endpoint: the recorded v1
points to the retired probe, while **v2 points to the working connection**.
The discovered tool is `policy___get_servicing_policy`, with approval `never`.

Hosted calls use managed identity for `https://ai.azure.com/.default` and trusted
request-scoped `x-agent-foundry-call-id`. No static user ID or operator token
substitutes for that context. Both JSON and SSE responses are bounded.
The service's MCP transport is stateless JSON with a session-manager lifespan.

Consent, transport, and authorization fail independently:
`CONSENT_REQUIRED`, TLS failure inside `HTTP_424`, and service
`user_not_authorized` were distinct observed outcomes.

## Configuration and credentials

`copilot-toolbox:infra-up` handles registration, Terraform, the exact-host MCP
rule, connection credentials/callback, toolbox selection, and discovery.
Configuration lives in private `.task/copilot-toolbox/configuration.json`.
Deployment reads the verified endpoint/tool from that journal.

New OAuth secrets stay in memory and go directly to the connection; journals keep
only ownership, key ID, and expiry. Renewal removes only the recorded predecessor
after replacement binding is verified. Lost credential responses stop recovery.
The recorded 30-day credential expires **2026-12-10 15:46:16 UTC**.

Private publication metadata defaults to `.task/copilot/publish-request.json`
and `.task/copilot-toolbox/publish-request.json`. Existing configuration was reused
live; fresh creation, renewal, and teardown also have offline coverage.

## Recorded deployment

Snapshot: **2026-11-10**, not a substitute for current status.

| Track | Version / image digest |
| --- | --- |
| Original seven ACS agents | v4; `sha256:e077b1b16841e7a3f52469190c06492b700c640f982d3ec34a9902d33f246e58` |
| OAuth Copilot agent | v1; `sha256:8bd63248465d02b0185196b0a12d0c6791e13c2669370dfa99ce599dec46bc11` |
| Original publication | **ACS Servicing Demo**, pinned v4 |
| OAuth publication | **ACS OAuth Servicing Demo**, pinned v1; toolbox v2 |

[Runtime results and outstanding checks](telemetry-map.md#isolated-copilot-acceptance)

## Source layout

Python packages remain `containment_demo.*` and `services.*`, under `src/`.
The wheel includes both. Service images build from the repository root using
`src/services/Dockerfile`.

## Primary references

Access dates below describe the original contract checks, not a fresh review.

| Checked | References |
| --- | --- |
| 2026-10-07–19 | [Hosted agents](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents), [egress](https://learn.microsoft.com/azure/foundry/agents/how-to/add-hosted-agent-guardrails), [RAI schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies), [managed network](https://learn.microsoft.com/azure/foundry/how-to/managed-virtual-network), [endpoint approval](https://aka.ms/azureaipeapproval) |
| 2026-11-06 | [ACS release](https://pypi.org/pypi/agent-control-specification/0.3.1b1/json), [ADK tool boundary](https://github.com/google/adk-python/blob/v2.12.0/src/google/adk/flows/llm_flows/tools/_caller.py), [OPA checksum](https://github.com/open-policy-agent/opa/releases/download/v1.9.0/opa_linux_amd64_static.sha256), [Projects SDK](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.8.0/sdk/ai/azure-ai-projects/azure/ai/projects/_patch.py) |
| 2026-11-09 | [OpenAI v1 auth](https://learn.microsoft.com/azure/foundry/openai/api-version-lifecycle#code-changes), [publication](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot), [private publication](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network), [toolbox network](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox-network-isolation), [hosted toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/use-toolbox-hosted-agent) |
| 2026-11-10 | [Tool authentication](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/tool-authentication), [MCP auth](https://learn.microsoft.com/azure/foundry/agents/how-to/mcp-authentication), [connections](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/projects/connections), [Graph update](https://learn.microsoft.com/graph/api/application-update?view=graph-rest-1.0), [addPassword](https://learn.microsoft.com/graph/api/application-addpassword?view=graph-rest-1.0), [removePassword](https://learn.microsoft.com/graph/api/application-removepassword?view=graph-rest-1.0) |
