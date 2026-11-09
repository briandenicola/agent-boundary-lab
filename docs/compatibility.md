# Compatibility and verified contracts

Consolidated 2026-11-09. Runtime pins are in `pyproject.toml`, `uv.lock` and
`Dockerfile.governed`; use those instead of an old spike's installed versions.
Superseded deployment experiments remain in Git history, not in the current runbook.

## Runtime

| Component | Contract / pin |
| --- | --- |
| Python | Repository target 3.12 |
| Google ADK | Lock resolves 2.12.0; supported async `before_tool_callback` |
| Foundry Responses server/core | 2.2.0; hosted protocol **2.0.0**, not `v1` |
| Azure AI Projects | 2.8.0 lifecycle contract |
| ACS Python | `agent-control-specification==0.3.1b1` |
| ACS manifest | `0.3.1-beta`, using `$snap` paths |
| OPA | 1.9.0, static Linux x86_64 |
| uv in governed image | 0.9.7; `uv sync --locked` |
| OpenTelemetry | Deliberate `>=1.43,<2` dependency override |
| A2A facade | a2a-sdk 1.0.2 with protobuf below 7 |
| Policy identity | PyJWT 2.15.1, cryptography 50.0.2, httpx 0.28.1 |

ADK and the Foundry server originally had incompatible OpenTelemetry constraints.
The repository override is intentional and import/runtime regressions guard it;
do not remove it just to make resolver metadata appear cleaner.
LiteLLM imports MCP types even for ordinary function tools, so MCP is a runtime
library dependency, not an additional business tool or MCP endpoint.

The governed image has separate `/opt/agent-venv` and `/opt/deploy-venv` profiles.
This keeps deployment SDK dependencies out of the agent interpreter.

## Issue #10 -- published ACS contract (2026-11-06)

The published release differs from AGT's newer `main` examples.
Use `AgentControl.from_path` and async
`evaluate_intervention_point(point, snapshot, mode)`, with `pre_tool_call` and
`enforce`. The host implements Audit and Disabled behavior explicitly.

The native wheel is CPython 3.11 ABI3, Linux x86_64, glibc >=2.28.
The release metadata did not publish ARM, macOS or Windows wheels; preparation
refuses source builds instead of assuming they work.

| Verdict | Host behavior |
| --- | --- |
| allow / warn | Continue |
| deny | Block in Enforced, record and continue in Audit |
| escalate | Approval-required; blocked in Enforced, never automatic approval |
| transform | Only a validated empty-argument replacement fits the fixed tool contract |
| Runtime/evaluation error | Explicit evaluation error; fail closed in Enforced |

`runtime_error:` reasons remain evaluation errors, not ordinary policy denial.
The SDK captures `ACS_OPA_PATH` / `ACS_OPA_TIMEOUT_MS` when constructing its
dispatcher. The host bounds the async wait and the OPA subprocess. Cancellation
does not kill a native executor worker, but a late result cannot resume a blocked
business call. Restart after changing startup policy artifacts.

OPA binary SHA-256:
`66fa66f3b730b2fb086003863428b382b2898d343adb4b5dfab5598b4d739eed`.
ACS wheel SHA-256:
`a0eea57016fc4cf3c620d92b81ad8c7b1376aa2865991a561ea6a427cb1451be`.

ADK awaits the callback before its tool runner. A non-None callback result prevents
tool execution. `ToolContext.session`, `invocation_id` and `function_call_id`
supply correlation. Diagnostics require explicit mediation because they do not
go through ADK's callback.

The SDK's `guard_foundry_agent` targets a manual `requires_action` client loop,
not this hosted Responses/ADK boundary, and is not used.
No remote policy bundles, annotators, post-tool hooks or approval resolver are enabled.

Offline checks with real ACS/Rego and mock HTTP passed 2026-11-06, including five
tamper checks. Commands: `governance:prepare`, `governance:check`,
`governance:tamper`. These are functional/governance checks, not containment proof.

Primary sources, accessed 2026-11-06:

- [Published ACS release](https://pypi.org/pypi/agent-control-specification/0.3.1b1/json),
  including wheel/sdist client, manifest and native OPA dispatcher source.
- [ADK 2.12 execution boundary](https://github.com/google/adk-python/blob/v2.12.0/src/google/adk/flows/llm_flows/tools/_caller.py).
- [ADK context](https://github.com/google/adk-python/blob/v2.12.0/src/google/adk/agents/readonly_context.py).
- [OPA checksum](https://github.com/open-policy-agent/opa/releases/download/v1.9.0/opa_linux_amd64_static.sha256).

## Foundry deployment contract

Observed in the October baseline and reused by the November deployment:

- Agent versions are data-plane resources, accessed privately using API `v1`.
- Hosted protocol version is `2.0.0`. A container protocol value of `v1` was
  accepted at creation but rejected at invocation.
- Digest references `repo@sha256:<64 hex>` were accepted.
- `definition.rai_config.rai_policy_name` contains the policy's full ARM ID.
- The agent's own identity needs model access; publisher access is not sufficient.
- Native inbound A2A send to a hosted target returned `HOSTED_AGENT_NOT_SUPPORTED`.
  The baseline uses its own A2A facade over Responses.
- `APPLICATIONINSIGHTS_CONNECTION_STRING` is reserved: the platform injects it
  from the project connection. Do not put it in hosted scenario environment settings.
- Lifecycle calls use bounded 60-second requests with automatic SDK retries disabled.
  An uncertain creation requires readback before any deliberate retry.
- `get_openai_client` supports a named agent endpoint. Do not invent a
  version-specific invocation URL; verify the served version in application evidence.
- Go Task's embedded shell does not implement `umask`; private journals use
  mode-600 `mktemp` files and atomic replacement.

SDK sources, rechecked 2026-11-06:
[AgentsOperations](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.8.0/sdk/ai/azure-ai-projects/azure/ai/projects/operations/_operations.py),
[get_openai_client](https://github.com/Azure/azure-sdk-for-python/blob/azure-ai-projects_2.8.0/sdk/ai/azure-ai-projects/azure/ai/projects/_patch.py).
Reserved setting reference, accessed 2026-11-09:
[hosted-agent deployment](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent).

## Microsoft 365 publication contract

The owner selected **Shared / Just you**, with the blocked external-processing
action as the first release. `task copilot:*` implements native REST publication
for the owned governance-denial agent. It preserves Responses and existing
authorization, adds authenticated Activity access, and pins the reviewed version.
It does not change account PNA, egress policy or policy API authentication.

Publishing uses the owner's Azure CLI user token for `https://ai.azure.com`,
not the helper's workload identity. A private journal records the approved
configuration before any write. Uncertain publish requests are never retried
automatically; restoring endpoint settings does not delete the catalog entry.

The updated Responses handler generates a fresh `chat-<uuid>` per headerless turn,
isolates its runner and appends the marker to the reply. Explicit direct-client
markers and diagnostic responses retain their existing contract.

Native channel delivery and hosted ACS evidence still require owner validation.
Microsoft 365 sign-in is not a delegated policy API token. The documented managed
delegation/toolbox flows do not establish token forwarding into this agent's
existing direct-HTTP tool; lookup and combined-prompt acceptance are deferred.
No app-only or operator-token fallback is introduced.

Primary references, accessed 2026-11-09:

- [Native private-network publication](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).
- [Publication and version selection](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot).
- [Hosted runtime contract](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-contract).
- [User delegation configuration](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-user-delegation).
- [Application-managed forwarding](https://learn.microsoft.com/azure/foundry/agents/how-to/use-on-behalf-of-flow).

## Network and monitoring

Current deployment defaults: Sweden Central, `Standard_D4as_v7`, single configured
tenant/subscription. Do not reuse an old Canada Central URL or identity-probe config.
Feature availability and capacity must still be checked in a fresh subscription.

The account has PNA disabled and managed isolation `AllowOnlyApprovedOutbound`.
Both business API hosts are allowed by the managed network. RAI egress policies
separately control the receiver in the network comparison.

RAI resource API: `Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview`.
`properties.mode` is content safety; `properties.egressPolicy.mode` is network
Audit/Enforced. Required base-policy/content-filter configuration is not inherited
implicitly. Preserve existing externally managed baseline content-filter properties.

The managed-network ACR private endpoint is separate from the AKS VNet endpoint.
Its account identity needs registry-scoped Network Connection Approver and
resource-group Reader, as verified in the 2026-10-15 recovery and declared in
`infra/cloud/managed-network.tf`. See [rebuild recovery](rebuild-runbook.md).

Platform egress rows were observed in `AppDependencies`, not `AppTraces`.
The run marker in `Data` / `Properties.path` joins decisions to receipts;
`OperationId` did not join the application/platform layers.
See [telemetry map](telemetry-map.md) for field names and dated results.
Custom OTLP carriage of platform decisions is not established.
Underlying managed-firewall traffic logging is distinct from RAI decisions and
has not been exposed by the documented managed-network service.

Foundry resource diagnostics omit `logAnalyticsDestinationType`: Azure returned
null for the requested `Dedicated` setting. Resource diagnostics and Application
Insights application tables are separate routes. AKS collection excludes
`ContainerInventory` because its environment column can capture sensitive settings.

Network egress remains preview, without a preview SLA or production assurance.
The implicit runtime allowlist is not enumerated; this demo does not prove that
every possible destination/protocol is contained.

Primary references, accessed 2026-10-07 through 2026-10-19 unless noted:

- [Hosted agents](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents).
- [Guardrails and egress](https://learn.microsoft.com/azure/foundry/agents/how-to/add-hosted-agent-guardrails).
- [RAI ARM schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies).
- [Managed network](https://learn.microsoft.com/azure/foundry/how-to/managed-virtual-network).
- [Private endpoint approval](https://aka.ms/azureaipeapproval).
- [Hosted telemetry](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-hosted-agent-telemetry).
- [Resource diagnostic categories](https://learn.microsoft.com/azure/azure-monitor/reference/supported-logs/microsoft-cognitiveservices-accounts-logs), accessed 2026-11-06.

## Deployment record (2026-11-09)

Both real controlled APIs were deployed with tag `6da553c-dirty-20261109162459`.
The guarded plan applied exactly two Container App updates, no additions/deletions.
Both revisions were healthy, received all traffic and answered their expected health
identity. Original policy properties were unchanged before/after.

| Image | Observed digest |
| --- | --- |
| Policy API | `sha256:52f5a60c10b2c74a5cd9f5c7821fae178ce7957768b317eebb4c3e5e87f921af` |
| Receiver | `sha256:0b7e23eadc9de5c4d21d2b1665dece8dc1b4a3bcb18b0b3769aab17e5fc2df53` |
| Seven governed agents, active v1 | `sha256:52a8e31808c575c674f0a4e1cb4ba2617807d9b49903c80b8b142a9a47cf1e53` |

Three isolated policies and seven model grants were verified by readback.
AKS was resumed for the private publisher. No hosted governance comparisons were
invoked. Health, active versions and model grants are configuration evidence only.

## Microsoft 365 Copilot

Primary publication references accessed 2026-11-09:
[native publication](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot),
[REST/private networking](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).
The implementation must verify Activity delivery, downstream delegation and
correlation for the actual hosted agent; direct Responses headers are not proof.
