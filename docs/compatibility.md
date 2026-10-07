# Phase 0 — Compatibility and availability spike

**Research date: 2026-10-07.** Every claim below carries a primary source. Items marked
**NOT FOUND** were searched for and not found in any primary source; they are listed again
under [Unverified — must be tested empirically](#unverified--must-be-tested-empirically).
Nothing in this document was inferred from a plausible-sounding guess.

Target region: **East US 2**. Target subscription: from the ambient `az login` context
(matching the `online-banking-demo` convention).

> **Preview status.** Network egress controls are preview, carry **no preview SLA**, and are
> **not intended for production use**. This repository is a demonstration, not a compliance
> assurance.

---

## Decision summary

| Decision | Choice | Why |
| --- | --- | --- |
| Hosted-agent protocol | **Responses** (`POST /responses`) | Documented as the recommended starting point; platform manages conversation history. Invocations remains available as a fallback. |
| Server package | `azure-ai-agentserver-responses` (on `azure-ai-agentserver-core`) | Named in the Learn hosted-agent contract. Version to be pinned at install time — no version is published in the docs. |
| Model access | Google ADK `LiteLlm` wrapper → Azure model deployment | Only documented non-Gemini path for ADK. |
| Egress policy resource | `Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview` | Confirmed in the ARM template reference. Not a new resource type — egress is a nested property on the existing RAI policy. |
| Evidence source | Application Insights `traces`, `message == "Network egress decision"` | The only documented location. |
| Account networking | **OPEN — see [Blocker 1](#blocker-1-managed-vnet--egress-policy-composability-is-undocumented)** | Blocking decision; do not write account networking Terraform until resolved. |

---

## A. Hosted agents

### A1. Status

Foundry Agent Service is **GA**, but "some sub-features are in public preview and might have
different constraints." No page applies a single GA/preview label to hosted agents as a whole.
Preview-flagged sub-features include long-running/resilient execution, A2A v0.3, and voice agents.

An **earlier preview hosting backend** (`azure-ai-agentserver-agentframework`,
`azure-ai-agentserver-langgraph`) is being retired: existing deployments on it "are supported
only until **August 20, 2026**" and are not migrated automatically. We must build on the
current protocol-library model, not that backend.

- https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions
- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/migrate-hosted-agent-preview

### A2. Region — is East US 2 supported?

**Yes, with a caveat.** The `limits-quotas-regions` table lists East US 2 as supported for
Responses API, Agents, Voice-based agents (preview), and Private VNet.

Caveat: there is **no region table scoped specifically to hosted agents** (as distinct from
the general Agents table), and **none scoped to the network egress preview**. East US 2
coverage for those two specific sub-features is *inferred from the general table*, not
independently stated. Confirm by attempting a deployment before relying on it.

- https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions

### A3. Container contract

Concrete and confirmed (reference page updated 2026-09-28):

| Requirement | Value |
| --- | --- |
| Listen port | **8088**, HTTP/1.1 **plain HTTP** — the platform terminates TLS |
| Health probe | `GET /readiness` → `200 OK` |
| Protocol endpoint | at least one of `POST /responses` or `POST /invocations` |
| Shutdown | graceful on `SIGTERM` |

Platform-injected environment variables: `FOUNDRY_HOSTING_ENVIRONMENT`, `FOUNDRY_AGENT_NAME`,
`FOUNDRY_AGENT_ID`, `FOUNDRY_AGENT_VERSION`, `FOUNDRY_PROJECT_ENDPOINT`,
`FOUNDRY_AGENT_SESSION_ID`, `FOUNDRY_PROJECT_ARM_ID`, `PORT` (default 8088),
`SSE_KEEPALIVE_INTERVAL`, `APPLICATIONINSIGHTS_CONNECTION_STRING` (platform-reserved, **not**
overridable), `OTEL_EXPORTER_OTLP_ENDPOINT`, `HOME` (default `/home/session`).

The `AGENT_*` and `FOUNDRY_*` prefixes are reserved for platform use — our own settings must
not use them.

- https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract
- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-hosted-agent-env-variables

### A4. Responses vs Invocations

Both exist; a single agent may serve both. **Responses is recommended** and is OpenAI
Responses API-compatible — the platform hydrates conversation history from `conversation.id`.
Invocations takes arbitrary JSON and leaves session management entirely to us.

**Decision: Responses**, with our authenticated deterministic diagnostic path exposed through
it rather than as a third business tool.

Server packages: `azure-ai-agentserver-responses` and `azure-ai-agentserver-invocations`, both
on `azure-ai-agentserver-core`. **NOT FOUND:** any pinned or recommended version — the docs
show an unversioned `pip install`. We pin whatever resolves at first install and record it here.

- https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents
- https://pypi.org/project/azure-ai-agentserver-responses/

---

## B. Network egress controls

### B1. Status and regions

**Preview. No preview SLA. Not intended for production.** Configured using the
`2026-05-15-preview` API version of the RAI policy. **NOT FOUND:** any region list scoped to
the egress preview.

- https://devblogs.microsoft.com/foundry/egress-controls-hosted-agent/
- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

### B2. Resource type and API version

```
Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview
```

Egress is a **nested property on the existing RAI policy resource**, not a separate resource
type. In Terraform this means `azapi_resource`, consistent with how `online-banking-demo`
handles preview Foundry resources.

- https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies

### B3. Schema — and the two different "mode" properties

There are **two distinct `mode` properties**, and conflating them would invalidate the demo:

| Property | Meaning | Values |
| --- | --- | --- |
| `properties.mode` | content-safety mode | `Default`, `Deferred`, `Blocking`, `Asynchronous_filter` |
| `properties.egressPolicy.mode` | **network enforcement mode** | **`Audit`**, **`Enforced`** (defaults to `Enforced` if omitted) |

Default action: `properties.egressPolicy.defaultAction` — `Allow` or `Deny`, **defaults to
`Deny`** (fail-closed). Evaluation itself is fail-closed: if the policy cannot be evaluated,
the request is denied.

Exact-host allow rule:

```json
{
  "name": "allow-policy-api",
  "ruleType": "Fqdn",
  "match": { "host": "policy.example.com" },
  "action": { "actionType": "Allow" }
}
```

`action.actionType` enum: `Allow`, `Deny`, `Rewrite`, `Transform`. Maximum **480 rules** per policy.

- https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies
- https://devblogs.microsoft.com/foundry/egress-controls-hosted-agent/

### B4. Attaching a policy to an agent version

Field: `definition.rai_config.rai_policy_name`, set to the **full ARM resource ID** of the
policy, not a bare name:

```
/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/raiPolicies/<policy>
```

Python SDK: `RaiConfig(rai_policy_name=<arm id>)` passed to `HostedAgentDefinition`.
`azure.yaml` (azd) uses camelCase `raiPolicyName` under a `policies` list with
`type: rai_policy`. The deprecated standalone `agent.yaml` uses snake_case. Same field.

- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

### B5. Denial behavior

The **egress proxy returns HTTP 403** to the agent's network client. The documentation itself
warns against the exact confusion `PLAN.md` forbids: *"A destination can also return 403, and a
DNS or TLS failure is not a successful denial."*

This confirms our design requirement: a bare 403 at the client is **not sufficient**. The pass
condition must be the 403 *plus* a matching platform decision record *plus* absence of a
receipt at the test receiver.

**NOT FOUND:** the 403 response body/header schema, and whether DNS still resolves for a
blocked hostname.

- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

### B6. TLS interception and the CA bundle — affects our HTTP client code

The proxy **MITMs HTTPS**. The runtime injects the proxy's CA into the sandbox trust bundle.
The CA is infrastructure-specific and **rotates roughly every 30 days**; the documentation says
to treat it as runtime configuration and **not to pin, copy, or persist it**.

| Env var | Consumer |
| --- | --- |
| `SSL_CERT_FILE` | OpenSSL-style clients |
| `REQUESTS_CA_BUNDLE` | Python `requests` |
| `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` | gRPC |
| `NODE_EXTRA_CA_CERTS` | Node.js |

**Implementation consequence:** `requests` honours `REQUESTS_CA_BUNDLE` automatically; `httpx`
may not. Our tools must read the CA path from the environment at call time and must **never**
hardcode a path or disable verification. TLS verification stays on in every mode.

- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

### B7. Match scope

Host (FQDN) and optionally path. `match.host` supports DNS wildcard syntax — a leading `*.`
matches any subdomain. `match.path` does URI prefix matching with `*` as a single-segment
wildcard. **No port matching and no IP matching exist in preview**; service tags and IP ranges
are listed as planned future capability.

This supports the `README.md` requirement to use two **distinct hostnames** rather than a
path-based allowlist.

- https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies

### B8. Implicit allowlist

The runtime "automatically allow lists foundational domains it needs to function," and a
`Deny` default action does not block that required platform connectivity — so we do **not**
need rules for the model endpoint or platform telemetry.

**NOT FOUND:** the itemized list of those domains. We must not assume package mirrors, our
own ACR, or a custom OTLP collector are covered. This matters for the demo's causal story: if
the permitted call happens to succeed via an undocumented implicit allow rather than our
explicit rule, the experiment is muddied. Test empirically.

- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

---

## C. Evidence and observability

### C1. Where egress decisions surface

Application Insights **`traces`** table, filtered on a literal message string:

```kusto
traces
| where timestamp > ago(1h)
| where message == "Network egress decision"
```

Each event is documented to include "the destination host, matched rule, decision, and
enforcement mode" — but **the sub-field names are NOT documented**. Do not assume
`customDimensions` key names. The Foundry portal surfaces the same data as a "Network egress
decision" span in the **Trajectories** trace view, with UI labels Decision, Reason, Matched
rule, Rule source, Enforcement, Destination, Default action. Those are UI labels and are
**not confirmed** to be Log Analytics column names.

**NOT FOUND:** any `Microsoft.CognitiveServices` diagnostic-settings resource-log category for
egress decisions distinct from this Application Insights mechanism.

`docs/telemetry-map.md` stays unfilled until we observe real rows.

- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

### C2. Audit-mode evidence

Audit "changes only how Deny actions behave: a request that would be denied is logged instead
of blocked." `Transform` and `Rewrite` apply in both modes. Evidence appears in the same two
places as C1, with the Enforcement field showing audit. Operational guidance from the blog:
*"Do not treat a missing event as proof that a call was allowed."* — which matches our
inconclusive-not-pass rule.

### C3. Correlation to an application trace — NOT FOUND

**No documented correlation key.** The portal nests the egress span in the same invocation
timeline, implying association by construction, and App Insights `traces` rows normally carry
`operation_Id`/`operation_ParentId` — but that is generic App Insights behaviour, not a
documented Foundry guarantee. Our `demo_run_id` fallback correlation key is therefore not
optional; it is the only correlation we control.

### C4. Does OTel export carry egress decisions? Probably not

The telemetry how-to scopes hosted-agent telemetry to "the protocol runtime … and your agent
code" and never mentions egress, RAI, or network decisions. The guardrails doc ties egress
visibility to the project's Application Insights. **It is undocumented and unconfirmed**
whether egress evidence appears at a custom `OTEL_EXPORTER_OTLP_ENDPOINT` at all.

Consequence: we must not claim an OTLP export carries platform decisions. Project-linked
Application Insights must be enabled regardless.

- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-hosted-agent-telemetry

---

## D. Composability with a managed VNet — **blocking gap**

### D1/D2/D3

Both features are independently documented as applicable to hosted agents: the managed-VNet
doc states managed VNet "now supports Prompt and Hosted Agent services with the new Responses
API." But the entire "Network egress controls (preview)" section **never mentions** VNets,
`networkInjections`, `publicNetworkAccess`, or isolation modes. It frames enforcement purely as
happening "inside the agent's sandbox before traffic leaves the runtime." The hosted-agents
concept page has no networking section at all.

**No source states these two features are compatible, incompatible, or layered.** This is a
confirmed documentation gap, not a failed search. Supporting evidence that the documentation
set is still being assembled: the official `foundry-samples` egress sample cross-links to
`azure/ai-services/openai/how-to/egress`, and **that URL 404s** as of 2026-10-07.

Likewise unanswered: with isolation mode `AllowInternetOutbound`, whether outbound traffic is
governed by the egress policy, by managed-VNet outbound rules, or by both; and whether
managed-VNet FQDN rules (which force a managed Azure Firewall, ports 80/443 only) stack with
or conflict with the egress allowlist.

- https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network
- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails
- https://techcommunity.microsoft.com/blog/azurearchitectureblog/your-private-endpoint-does-not-cover-agent-egress-locking-down-azure-ai-foundry-/4547864

---

## E. Google ADK and the Azure model

### E1. Package

`google-adk` **2.11.0** on PyPI. PyPI metadata says `requires_python = ">=3.10"`; the GitHub
README says **Python 3.11+** with constraints files for 3.11–3.14. The two primary sources
disagree. We target **Python 3.12** to sit safely inside both.

- https://pypi.org/pypi/google-adk/json
- https://github.com/google/adk-python

### E2. Pointing ADK at an Azure model

LiteLLM is the only documented non-Gemini path:

```python
from google.adk.models.lite_llm import LiteLlm
agent = LlmAgent(model=LiteLlm(model="azure/<deployment-name>"), ...)
```

ADK's own docs contain **no Azure example** and defer to LiteLLM's provider documentation. Per
LiteLLM's Azure docs: `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`, `AZURE_AD_TOKEN`,
`AZURE_API_TYPE`. A **static** Entra ID token can be supplied as `azure_ad_token=` or via
`AZURE_AD_TOKEN`, meaning we acquire it ourselves with `DefaultAzureCredential` / managed
identity.

**NOT FOUND:** whether LiteLLM accepts a rotating token-*provider* callback rather than a
static token. This matters for a long-running hosted agent — a static token expires. Resolve
before Phase 2, and record the mitigation (token refresh wrapper) if no callback exists.

- https://google.github.io/adk-docs/agents/models/litellm/
- https://docs.litellm.ai/docs/providers/azure

### E3. Avoiding duplicate tracer providers

Code-verified in `google/adk-python:src/google/adk/telemetry/setup.py`. The
`maybe_set_otel_providers()` docstring: *"If a provider for a specific telemetry type was
already globally set - this function will not override it or register more exporters."*

**Therefore:** configure our own `TracerProvider` via `trace.set_tracer_provider(...)` — or let
the Foundry runtime configure it — **before** ADK initialises. ADK then no-ops. This is the
documented way to avoid duplicate export.

### E4. Google telemetry export is off by default

Exporters are only constructed when the relevant OTLP env vars are set, or when Cloud Trace is
explicitly opted into (`adk web --otel_to_cloud`, or
`get_gcp_exporters(enable_cloud_tracing=True)`). Opt-in by omission; there is no separate
disable flag to set. We simply never opt in.

- https://google.github.io/adk-docs/observability/traces/

---

## Blockers

### Blocker 1 — managed VNet + egress policy composability is undocumented

**Status: blocking an architecture decision, not the whole build.**

The demo's entire claim rests on a **single experimental variable**: the same image digest
deployed twice, differing only in `egressPolicy.mode`. If the account also runs a
Microsoft-managed VNet, we cannot show from any primary source whether the egress policy is the
thing enforcing containment, whether the managed VNet is, or whether both are. That is a
two-variable experiment, and `PLAN.md` forbids presenting one control as another.

Options, in order of preference:

1. **No managed VNet on the Foundry account for this demo.** Private endpoints still protect
   the backing resources (ACR, Key Vault, Log Analytics, storage). The experiment stays clean.
2. **Managed VNet, but prove composability empirically first** — confirm ARM even accepts
   `networkInjections` + an attached egress policy, then confirm the Audit/Enforced difference
   is still observable. Costs 30+ minutes per apply and may end in option 1 anyway.
3. Build both and compare. Most expensive; most complete evidence.

### Blocker 2 — preview with no SLA

Hosted agents overall are GA, but network egress controls are preview with an explicit "not
intended for production" disclaimer. Acceptable for a demo; must be stated plainly in the
runbook and never implied to be a compliance control.

### Blocker 3 — implicit allowlist is unenumerated

See B8. Risks muddying the causal story if the permitted call succeeds via an undocumented
implicit allow. Mitigation: test with the explicit allow rule removed and confirm the
permitted destination is then denied too.

### Blocker 4 — no confirmed trace correlation key

See C3. If the narrative promises a single correlated trace spanning tool call → platform
decision, that must be verified empirically. Until then `demo_run_id` is the primary
correlation key and the correlated-trace claim stays out of the docs.

---

## Unverified — must be tested empirically

These cannot be resolved from documentation. Each is a test in `scripts/verify_demo.py` or a
one-off spike, and each must be recorded here with its result before any claim depends on it.

1. Exact field names inside the Application Insights "Network egress decision" event (C1).
2. Whether that event carries an `operation_Id` that joins to our application trace (C3).
3. Whether egress evidence appears at a custom OTLP endpoint (C4).
4. The 403 response body/headers, and whether DNS resolves for a blocked host (B5).
5. The itemized implicit auto-allow list (B8).
6. Whether ARM accepts `networkInjections.useMicrosoftManagedNetwork = true` +
   `publicNetworkAccess = "Disabled"` **and** an attached egress RAI policy at all (D1).
7. Which layer governs when managed-VNet isolation mode and the egress policy are both
   configured (D2, D3).
8. Whether LiteLLM supports a dynamic Entra ID token-provider callback (E2).
9. Hosted-agent- and egress-specific region support for East US 2, as opposed to the general
   Agents region table (A2, B1).
10. Resolved versions of `azure-ai-agentserver-responses` / `-invocations` (A4).

---

## Sources

| Source | Accessed |
| --- | --- |
| [Hosted agents in Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents) | 2026-10-07 |
| [Hosted agent contract](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-contract) | 2026-10-07 |
| [Configure hosted agent environment variables](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-hosted-agent-env-variables) | 2026-10-07 |
| [Add hosted agent guardrails (network egress controls)](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails) | 2026-10-07 |
| [Limits, quotas and regions](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions) | 2026-10-07 |
| [Migrate hosted agent preview](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/migrate-hosted-agent-preview) | 2026-10-07 |
| [raiPolicies ARM reference, 2026-05-15-preview](https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies) | 2026-10-07 |
| [Export hosted agent telemetry with OpenTelemetry](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-hosted-agent-telemetry) | 2026-10-07 |
| [Managed virtual network](https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network) | 2026-10-07 |
| [Control where your hosted agent connects (devblog, 2026-09-24)](https://devblogs.microsoft.com/foundry/egress-controls-hosted-agent/) | 2026-10-07 |
| [Your private endpoint does not cover agent egress (Tech Community)](https://techcommunity.microsoft.com/blog/azurearchitectureblog/your-private-endpoint-does-not-cover-agent-egress-locking-down-azure-ai-foundry-/4547864) | 2026-10-07 |
| [Google ADK — LiteLLM models](https://google.github.io/adk-docs/agents/models/litellm/) | 2026-10-07 |
| [Google ADK — Traces](https://adk.dev/observability/traces/) | 2026-10-07 |
| [google/adk-python `telemetry/setup.py`](https://github.com/google/adk-python) | 2026-10-07 |
| [LiteLLM Azure provider](https://docs.litellm.ai/docs/providers/azure) | 2026-10-07 |
