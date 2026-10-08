# Phase 0 — Compatibility and availability spike

**Research date: 2026-10-07.** Every claim below carries a primary source. Items marked
**NOT FOUND** were searched for and not found in any primary source; they are listed again
under [Unverified — must be tested empirically](#unverified--must-be-tested-empirically).
Nothing in this document was inferred from a plausible-sounding guess.

Target region: **Canada Central**, chosen so that the containment environment and the
Phase 8 workflow state store can share one region. East US 2 hosted the containment
environment through Phase 0 and is verified there, but it cannot host PostgreSQL Flexible
Server on this subscription, and Flexible Server uses VNet injection, so the database
cannot simply live elsewhere (A2b). Canada Central permits both, and its egress spike
passed on 2026-10-08 (A2a). Sweden Central passed the same check and remains a proven
fallback. Target
subscription: from the ambient `az login` context (matching the `online-banking-demo`
convention).

> **Preview status.** Network egress controls are preview, carry **no preview SLA**, and are
> **not intended for production use**. This repository is a demonstration, not a compliance
> assurance.

---

## Decision summary

| Decision | Choice | Why |
| --- | --- | --- |
| Hosted-agent protocol | **Responses** (`POST /responses`) | Documented as the recommended starting point; platform manages conversation history. Invocations remains available as a fallback. |
| Server package | `azure-ai-agentserver-responses` **2.2.0** (on `azure-ai-agentserver-core` 2.2.0) | Named in the Learn hosted-agent contract; version resolved empirically on 2026-10-07. |
| Python | **3.12** | `google-adk` README requires 3.11+; 3.12 sits safely inside every stated constraint. |
| OpenTelemetry | **Pinned override to `>=1.43,<2`** | ADK and the agent server have mutually exclusive pins. See [Blocker 0](#blocker-0-resolved-opentelemetry-dependency-conflict-between-adk-and-the-agent-server). |
| Model access | Google ADK `LiteLlm` wrapper → Azure model deployment, authenticated with `azure_ad_token_provider` | Only documented non-Gemini path for ADK; the token-provider callback preserves refresh under managed identity. |
| Egress policy resource | `Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview` | Confirmed in the ARM template reference. Not a new resource type — egress is a nested property on the existing RAI policy. |
| Evidence source | Application Insights `traces`, `message == "Network egress decision"` | The only documented location. |
| Account networking | **Stage 1 PASSED 2026-10-07 — see [Blocker 1](#blocker-1-managed-vnet--egress-policy-composability-is-undocumented)** | Managed VNet + egress policies coexist and store intact. Enforcement attribution still unproven. |

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

### A2a. Region — spike status per region

The caveat in A2 applies to every region: there is no published table scoped to hosted
agents or to the egress preview. East US 2 was only ever trusted because the Phase 0 spike
confirmed it empirically, so every candidate is held to the same standard rather than
accepted from the general Agents table.

| Region | Egress spike | Postgres (A2b) |
| --- | --- | --- |
| East US 2 | **Passed** 2026-10-07 | Restricted |
| Sweden Central | **Passed** 2026-10-08 | Unrestricted |
| Canada Central | **Passed** 2026-10-08 | Unrestricted |
| Canada East | Not run | **Restricted** — not viable |

Canada Central is the selected target: it clears Postgres, keeps the containment
environment and the state store in one region, and its spike passed. Three regions have now
returned an identical result, which is consistent with the egress preview being broadly
available — but that is a pattern across three samples, not a published statement, so a
fourth region still gets spiked rather than assumed.

Each spike created a Foundry account in the region and read the configuration back from
ARM. Canada Central (`viable-kid-4249-spike-rg`) and Sweden Central both returned:

| Checked | Result |
| --- | --- |
| `networkInjections` retained | Yes — `scenario: agent`, `useMicrosoftManagedNetwork: true` |
| `publicNetworkAccess` | `Disabled` |
| `egress-audit` policy stored | Yes — `defaultAction: Deny`, `mode: Audit`, one Fqdn allow rule |
| `egress-enforced` policy stored | Yes — identical but `mode: Enforced` |

Provisioning took roughly 10 minutes, nearly all of it in the Microsoft-managed agent
network. A long `Creating` state is expected here and is not a failure signal.

**This is control-plane acceptance only.** It establishes that ARM stores the managed VNet
and both egress policies in Sweden Central. It establishes nothing about enforcement,
about which layer takes precedence, or about attribution of a denied request — the same
limits recorded for East US 2 in D1–D3.

From the general region table (re-accessed 2026-10-08), Sweden Central also reports Yes for
Responses API, Agents and Private VNet, and the deployed model is available there with the
`GlobalStandard` SKU the module uses (A2d).

### A2b. Region — PostgreSQL Flexible Server restrictions

**The subscription is restricted from provisioning Flexible Server in East US 2.** The
capabilities API returns `restricted: Enabled` with every supported version list empty,
which the server reports as the misleading `The value of the 'Version' should be in: []`.
The version is not the problem; the region is.

Checked 2026-10-08 against
`/providers/Microsoft.DBforPostgreSQL/locations/{region}/capabilities?api-version=2024-08-01`:

| Unrestricted | Restricted |
| --- | --- |
| `swedencentral`, `centralus`, `westus3`, `northcentralus`, `canadacentral` | `eastus`, `eastus2`, `westus2`, `southcentralus`, `canadaeast` |

Both `swedencentral` and `canadacentral` report supported major versions 11–18, covering
the module default of 16, and both have the deployed model available on the
`GlobalStandard` SKU the module uses (A2d).

`canadaeast` was checked on request and is **restricted**, returning *"Provisioning is
restricted in this region. Please choose a different region."* Regions within a geography
do not share this restriction, so each must be checked individually.

Flexible Server uses **VNet injection rather than a private endpoint**, so the server is
pinned to its subnet's region. This is why the restriction forces a region decision instead
of a configuration change, and why `enable_state_store` defaults to `false`: nothing before
Phase 8 reads from the store, and creating it unconditionally would drag the containment
environment out of a region where it is already working.

Note: `az postgres flexible-server list-supported-versions` does not exist, and `list-skus`
returns a shape that does not surface the restriction. The REST capabilities endpoint is
the reliable check.

### A2d. Model selection — the GPT-4 family is retiring

**Deployed model: `gpt-5.4-mini`, version `2026-03-17`, SKU `GlobalStandard`.** Verified
against the live catalogue in canadacentral on 2026-10-08.

**`gpt-5.5-mini` does not exist.** It was requested by name and was not present in the
catalogue for canadacentral, eastus2, swedencentral, westus3 or eastus. `gpt-5.5` has no
mini variant, so the smallest current model is one minor version behind the newest full
one.

**Check the SKU, not just the name.** In canadacentral, `gpt-5-mini` and `gpt-5` are offered
as `GlobalProvisionedManaged` only. The module deploys `GlobalStandard`, so either would
fail despite appearing in the catalogue. Availability of a model name is not availability
of the deployment shape.

| Model | Version | GlobalStandard in canadacentral |
| --- | --- | --- |
| `gpt-5.4-mini` | 2026-03-17 | Yes — selected |
| `gpt-5.4-nano` | 2026-03-17 | Yes |
| `gpt-5.5` | 2026-04-24 | Yes |
| `gpt-5-mini`, `gpt-5` | 2025-08-07 | **No** — provisioned only |

**NOT VERIFIED — three things, all on the model path rather than the containment path:**

1. Whether `DEMO_AZURE_OPENAI_API_VERSION`, currently `2024-10-21`, serves the gpt-5
   family. It was chosen for a GPT-4 model and has not been re-checked. Left unchanged
   rather than raised to a guessed value; confirm against the Azure OpenAI reference and
   record the result here before blaming a failure on anything else.
2. Whether the gpt-5 family accepts the same request shape through LiteLLM. Reasoning
   models in this family are documented to differ on parameters such as
   `max_completion_tokens` versus `max_tokens`, and on `temperature` support.
3. Whether tool calling behaves identically. gpt-4o-mini exercised this path; gpt-5.4-mini
   has not.

**A failure on any of these is a model-path failure, not a containment result.** The demo
classifies HTTP, TLS, DNS and timeout failures separately for exactly this reason: an
agent that never reaches the point of calling a tool has produced no evidence about
egress at all. Record it as inconclusive.

The version stays pinned. A floating version would let Azure change the model between the
Audit run and the Enforced run, introducing a second variable into an experiment whose
validity rests on there being exactly one.

### A2c. State store capability constraint

**Dapr Workflow is built on actors, and that is the binding constraint on store choice** —
not durability, which is what it looks like at first. Dapr's rule: *"State stores can be
used for actors if it supports both transactional operations and ETag."*

| Candidate | Backs Dapr actors |
| --- | --- |
| PostgreSQL | Yes |
| Azure Cosmos DB | Yes |
| Redis | Yes |
| Azure Table Storage | **No** — no transactional support |
| Azure Blob Storage | **No** — no transactional support |

PostgreSQL satisfies the constraint, so the regional restriction in A2b was resolved by
choosing a region rather than by swapping the component. Confirm the specific Dapr
component version during Phase 8; this table is a capability check, not a version pin.

- https://docs.dapr.io/reference/components-reference/supported-state-stores/

### A3. Container contract

Concrete and confirmed (reference page updated 2026-09-28):

| Requirement | Value |
| --- | --- |
| Listen port | **8088**, HTTP/1.1 **plain HTTP** — the platform terminates TLS |
| Health probe | `GET /readiness` → `200 OK` — **provided by the server package**, we do not implement it |
| Protocol endpoint | at least one of `POST /responses` or `POST /invocations` |
| Shutdown | graceful on `SIGTERM` |

**Verified empirically 2026-10-07.** Constructing `ResponsesAgentServerHost()` registers these
routes automatically:

```
POST        /responses
GET, HEAD   /responses/{response_id}
DELETE      /responses/{response_id}
POST        /responses/{response_id}/cancel
GET, HEAD   /responses/{response_id}/input_items
GET, HEAD   /readiness
```

Construction also emits `Tracing configured successfully via microsoft-opentelemetry distro`
— the host sets up OpenTelemetry itself. This is the key ordering fact for E3 below.

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
on `azure-ai-agentserver-core`. The docs publish no version — `pip install` is unversioned.
**Resolved empirically on 2026-10-07: 2.2.0** for both `-responses` and `-core`. Pinned
exactly in `pyproject.toml`, because a preview package resolving to a different version later
would silently change the contract this demo depends on.

Verified API surface (2.2.0):

```python
from azure.ai.agentserver.responses import ResponsesAgentServerHost

app = ResponsesAgentServerHost()

@app.response_handler                      # handler MUST be async
async def handle(request, context, cancellation_signal): ...

app.run(port=None)                         # defaults to $PORT, else 8088
app.add_route(path, route, methods=[...])  # used for our diagnostic route
```

`response_handler` rejects sync handlers and 2-argument signatures at decoration time with
`TypeError`. Cancellation (`cancellation_signal`) and shutdown (`context.shutdown`) are
**distinct** signals and must be inspected independently.

- https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents
- https://pypi.org/project/azure-ai-agentserver-responses/

---

## B. Network egress controls

> This section is the terse evidence record. For the explanatory treatment — enforcement
> point, evaluation semantics, denial classification, TLS consequences, and what the
> control does *not* cover — see **[`egress-control.md`](egress-control.md)**.

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

### B9. Deploying an agent version — the CLI cannot attach a policy

Verified 2026-10-08 by reading the installed `azure-cli` source
(`azure/cli/command_modules/cognitiveservices/custom.py`, az CLI 2.x, module present at
`/opt/az/lib/python3.14/site-packages/`). These are the calls the CLI actually makes, not
documentation prose.

Hosted agents are **not an ARM resource type**. `az provider show -n
Microsoft.CognitiveServices` lists no `accounts/projects/agents`; they live on the project
**data plane**:

| Item | Verified value |
| --- | --- |
| Base URL | `https://{account}.services.ai.azure.com/api/projects/{project}` (`_client_factory.py:71`) |
| Create version | `POST /agents/{name}/versions` (`custom.py:~2204`) |
| API version | `2025-11-15-preview` (`AGENT_API_VERSION_PARAMS`, `custom.py:495`) |
| Version addressing | `/agents/{name}/versions/{version}`, container ops append `/containers/default` |

Request body built by `_create_agent_definition` (`custom.py:1414`):

```json
{
  "definition": {
    "kind": "hosted",
    "container_protocol_versions": [{ "protocol": "RESPONSES", "version": "v1" }],
    "cpu": 1,
    "memory": "2Gi",
    "image": "<registry>/<repo>:<tag>",
    "environment_variables": { "KEY": "value" }
  },
  "description": "optional"
}
```

**`az cognitiveservices agent` cannot set an RAI policy.** No subcommand in the group
(`create`, `update`, `show`, `status`) exposes a policy argument, and
`_create_agent_definition` never emits `rai_config`. Since the attached policy is the
demo's only experimental variable, **the CLI cannot deploy either of our agent versions**.
The deployment must be a direct data-plane call that adds `rai_config.rai_policy_name`
(B4) to the same `definition` object.

`--image` is also tag-oriented: `_validate_image_tag` (`custom.py:510`) requires a colon
and treats everything after the last one as "the tag, which becomes the agent version". A
digest reference contains a colon, so it would pass validation, but the resulting version
name would be the raw hex. **Whether the service accepts a digest reference in
`definition.image` at all was NOT VERIFIED here — it is now CONFIRMED, see B9b**, on the
SDK path rather than the CLI path.

**The data plane is unreachable from outside the VNet.** With
`publicNetworkAccess: Disabled`, `az cognitiveservices agent list` returns:

```
(403) Public access is disabled. Please configure private endpoint.
```

So agent deployment has to originate inside the VNet, or the account's inbound posture has
to change for the duration of the deployment. This is an inbound/control-plane concern and
is independent of egress enforcement, but it is a real operational constraint on Phase 4.

- Verified by source inspection; no Learn page documents this payload.
- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

### B9a. The Python SDK surface we actually deploy with

Verified 2026-10-08 by reading **azure-ai-projects 2.8.0** source (the newest copy on this
machine, at
`/home/brian/code/foundry-infrastructure-design/src/hosted_agents/simple/.venv/lib/python3.14/site-packages/azure/ai/projects/`).
The package is **not** in this repo's default environment; it is the optional `deploy`
extra, because it requires `openai>=3` and the agent image must not gain a dependency it
does not use. Since the agent image digest is the experiment's control, the deployer and
the agent are deliberately different images.

| Thing | Verified symbol | Source |
| --- | --- | --- |
| Client | `AIProjectClient(endpoint, credential, allow_preview=True)` | `_client.py:40`, `_patch.py:157` |
| Endpoint form | `https://{account}.services.ai.azure.com/api/projects/{project}` | `_configuration.py:26` |
| Token scope | `https://ai.azure.com/.default` (client default) | `_configuration.py:57` |
| Create | `client.agents.create_version(agent_name, definition=, description=, metadata=)` → `AgentVersionDetails` | `operations/_operations.py:5441` |
| Read back | `client.agents.get_version(agent_name, agent_version)` | `operations/_operations.py:5891` |
| Enumerate | `client.agents.list_versions(agent_name)` | `operations/_operations.py:6042` |
| Definition | `HostedAgentDefinition(cpu=, memory=, rai_config=, environment_variables=, container_configuration=, protocol_versions=)` | `models/_models.py:12344` |
| Policy | `RaiConfig(rai_policy_name=<full ARM id>)` | `models/_models.py:16765` |
| Image | `ContainerConfiguration(image=, registry_connection_id=)` | `models/_models.py:7230` |
| Protocol | `ProtocolVersionRecord(protocol=, version=)`; protocols include `responses`, `invocations` | `models/_models.py:16657` |
| Readiness | `AgentVersionDetails.status` ∈ creating / active / failed / deleting / deleted | `models/_enums.py:380` |

These status values come from the **client library's enum**, not from an observed
response. What the service actually returns on the wire is still unverified — see B9b.

**B4 confirmed in code.** `RaiConfig.rai_policy_name` is a plain `rest_field` with no
`name=` override, so the wire name is snake_case `rai_policy_name`, and it hangs off
`HostedAgentDefinition`. Setting a policy through the SDK is therefore possible, which the
CLI cannot do.

**Three corrections to B9, which describes the az CLI's `2025-11-15-preview` shape.** The
SDK 2.8.0 shape differs and the SDK is what ships:

1. The image is nested: `definition.container_configuration.image`, not a flat
   `definition.image`.
2. Protocols are `definition.protocol_versions`, not `container_protocol_versions`.
3. There is **no container start operation** on `AgentsOperations` — no
   `containers/default:start` equivalent. Provisioning is observed by polling
   `get_version(...).status` until `active`. The group exposes `enable` / `disable` on the
   agent, and session operations, but nothing that starts a container.
   `AIProjectClientConfiguration.api_version` defaults to `"v1"` with a separate
   `allow_preview` flag rather than an explicit preview date string.

**Digest question — RESOLVED, see B9b.** `ContainerConfiguration.image` is an unvalidated
`str`; the SDK applies none of the az CLI's `_validate_image_tag` logic, so a
`repo@sha256:<64 hex>` reference is accepted client-side and the version name is assigned
by the service rather than derived from the tag. The CLI's "the tag becomes the version
name" problem does not exist on this path. **Server-side acceptance was CONFIRMED by the
live run on 2026-10-08 (B9b).** `containment_demo.deploy` requires a digest, has no tag
fallback, and raises `DigestRejectedError` telling the operator to stop and record the
exact error here if the service ever refuses one.

- Verified by reading installed package source on 2026-10-08; line numbers are for 2.8.0.
- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails

### B9b. The first live deployment — VERIFIED FROM INSIDE THE VNet 2026-10-08

Everything in B9 and B9a was read out of installed source. This section is the first
**observed** deployment. Evidence: the `agent-deploy` init container's log, pod
`agent-harness-6ffc656cd5-jbct7`, namespace `agent-boundary-lab`, AKS, 2026-10-08.

Read this section as narrow. It records what one successful call did, with one role
assignment, against one account. It is not a general capability claim about the service.

#### Verified

| Item | Observed value |
| --- | --- |
| Data-plane URL, verbatim | `https://<account>.services.ai.azure.com/api/projects/<project>/agents/<agent-name>/versions/<n>?api-version=v1` |
| `api-version` query value | **`v1` was accepted — HTTP 200.** Not a preview date string. Confirms the SDK default described in B9a correction 3 is what the service honours. |
| SDK that worked | `azure-ai-projects` **2.8.0**, `azure-identity` **1.26.0** (from the request User-Agent) |
| Runtime that worked | Python **3.12.15** on Azure Linux 3 (`Linux-6.6.150.1-1.azl3-x86_64-with-glibc2.41`) |
| Credential path | Workload identity. Observed: `ManagedIdentityCredential will use workload identity with client_id: a66ae277-860b-4a07-9735-354933e40146` |

**Agent-version WRITE is permitted — open question CLOSED, narrowly.** The log emitted
`Created version` and the subsequent `get_version` returned HTTP 200. The deployer identity
holds **`Cognitive Services User`** scoped to the Foundry account
(`infra/cloud/identity.tf:104`). This was previously an assumption: `agents/versions` is
not separately registered as a provider operation, so version writes were *assumed* to
authorise under `accounts/AIServices/agents/write` and the role's
`Microsoft.CognitiveServices/*` dataAction wildcard. That assumption now has one
confirming observation.

What it proves: **create and read** on `agents/versions`, for this identity, with this
role, at this scope. What it does **not** prove: update, delete, list, or any operation on
any other agent resource; nor that a narrower role would fail; nor that the wildcard is
the reason it succeeded.

**Server-side digest acceptance — CONFIRMED.** An image reference of the form
`<acr>/containment-demo-agent@sha256:<64 hex>` in
`definition.container_configuration.image` was accepted by the service. This closes the
`NOT VERIFIED` digest question carried in both B9 (where the az CLI's `_validate_image_tag`
raised it) and B9a (where it was marked unresolvable without a call from inside the VNet).
`DigestRejectedError` in `containment_demo.deploy` has not fired and, on this path, is now
expected never to.

Digests of record:

| Image | Digest | Size (bytes) |
| --- | --- | --- |
| Previous | `sha256:0e4b5019…` | 145,547,315 |
| Current | `sha256:0acce8b8ec1064710f462f330d1b22645ffe0485b459d57d34d4235dc8667de0` | 196,110,685 |

#### Observation, not a contract

Response headers carried `Server: istio-envoy` and `azureml-served-by-cluster`. Foundry
hosted agents are therefore served on AzureML infrastructure behind an Istio ingress.

This is an **implementation detail that may change without notice**. It is recorded
because it is useful when reading a failure — an Envoy-shaped error is not necessarily a
Foundry error — and for no other reason. **Nothing in this demo may depend on it.** In
particular, do not treat an `istio-envoy` response as evidence about egress enforcement:
this header is on the *inbound* control path to the data plane and has nothing to do with
the agent's outbound traffic, which is the thing under test.

#### OPEN — the version status vocabulary is still unknown

`src/containment_demo/deploy.py` `wait_until_active` accepts exactly one terminal-good
value, the literal lowercase string `"active"` (`_TERMINAL_OK`, line 78), and treats
`{"failed", "deleting", "deleted"}` as terminal-bad (`_TERMINAL_BAD`, line 79). Those
strings come from the SDK enum in B9a (`models/_enums.py:380`) — from the client library,
**not** from an observed response.

At the time of writing the init container had been polling for roughly six minutes and had
**not** terminated. So:

- We do not know what status string the service actually returns on the wire.
- We do not know whether `"active"` is ever reached, or how long provisioning takes.
- We do not know whether the service's casing matches the SDK enum's.

Do not record provisioning as working until a terminal status has been observed. **The
900-second timeout is the intended mechanism for learning the vocabulary:** its error
message prints the last observed status verbatim. That is deliberate. The data plane is
private-endpoint-only, so an operator outside the VNet cannot query the version directly,
and the timeout message is the only channel that carries the real string back out.

- Observed in a live run on 2026-10-08; no primary source documents the wire-level status
  values.



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

### C5. Linking Application Insights to the project — VERIFIED SCHEMA

Accessed **2026-10-08**. Read from installed SDK source under
`/opt/az/lib/python3.14/site-packages`, and cross-checked against a live project
connection read back from ARM on a sibling Foundry account in the same subscription. No
Learn page documents this payload.

C1 and C4 establish that a project connection to Application Insights is the only path
platform egress decision records take. Without it the platform layer is **silent**, which
is indistinguishable from "the policy did nothing" and makes every run inconclusive by
construction.

| Item | Verified value | Source |
| --- | --- | --- |
| Resource type | `Microsoft.CognitiveServices/accounts/projects/connections` | `azure/mgmt/cognitiveservices/operations/_operations.py:2510` |
| API version | `2026-05-15-preview` | `azure/mgmt/cognitiveservices/_configuration.py:51` |
| Scope | child of the **project**, not the account | same URL template |
| `properties.category` | `"AppInsights"` | `models/_enums.py:481` (`ConnectionCategory.APP_INSIGHTS`) |
| `properties.authType` | `"ApiKey"` | discriminator on `ApiKeyAuthConnectionProperties`, `models/_models.py:1563` |
| `properties.credentials` | `{ "key": "<connection string>" }` | `ConnectionApiKey`, `models/_models.py:3207` |

```json
{
  "properties": {
    "category": "AppInsights",
    "authType": "ApiKey",
    "target": "<Application Insights ARM resource id>",
    "isSharedToAll": false,
    "credentials": { "key": "<Application Insights connection string>" }
  }
}
```

**The "API key" is the Application Insights connection string.** Not an instrumentation
key, not a resource id. This is settled by the consumer, not by the ARM schema:
`azure/ai/projects/operations/_patch_telemetry.py:44-66` — the SDK call that resolves a
project's Application Insights — lists connections of type `AppInsights`, takes the first,
and then

```python
if isinstance(connection.credentials, ApiKeyCredentials): ...
else: raise ValueError("... does not use API Key credentials.")
self._connection_string = connection.credentials.api_key
```

with `api_key` serialised as the wire field `key`
(`azure/ai/projects/models/_models.py:66`).

**Two traps.**

1. **An `AAD` or `ManagedIdentity` connection applies cleanly and then does nothing.** ARM
   accepts it; the consumer above raises `ValueError` and no connection string is ever
   resolved. The category being right is not sufficient.
2. **There can be at most one.** The same file: *"Note: there can't be more than one
   AppInsights connection."* One resource, no `count`.

**NOT VERIFIED:** what `target` should hold for this category. The SDK docstring gives
`target` examples for `AzureOpenAI`, `CognitiveService` and `CognitiveSearch` only, and no
`AppInsights` connection existed anywhere in the subscription to read back. We set the
Application Insights ARM resource id, mirroring how a live `AzureOpenAI` connection
carries its resource id in `metadata.ResourceId`. The telemetry read path never touches
`target`, so a wrong value here cannot silence the evidence.

Implemented in `infra/cloud/project-connections.tf`. Confirm after applying with
`task cloud:app-insights-connection` — which also fails if the auth type is not `ApiKey`,
for trap 1 above.

### C6. A clean plan is the drift control — no `timestamp()` in tags — FIXED 2026-10-08

The experimental claim is that the RAI policy is the **only** difference between the
Audit run and the Enforced run. The mechanical way to demonstrate that is to run
`task cloud:plan` between the two runs and get
`No changes. Your infrastructure matches the configuration.` Anything that makes the plan
permanently dirty removes that check, and there is no substitute for it.

`infra/cloud/locals.tf` and `infra/spike/locals.tf` both set `DeployedOn = timestamp()`
in their tag maps. `timestamp()` re-evaluates on every plan, so the tag map became unknown
and every tagged resource was marked for in-place update on every run. Observed against
the live subscription on 2026-10-08: `Plan: 0 to add, 24 to change, 0 to destroy`, of
which 22 were tag-only churn, rendered as the whole map being removed and replaced by
`(known after apply)`. The `Application` tag was never actually dropped — that is just how
Terraform renders an unknown map — but `tasks/Taskfile.arm.yml` looks the Foundry account
up by that tag, so its stability matters.

Two specific costs beyond the noise:

1. **Preview-resource risk for nothing.** It forced an in-place update of
   `azapi_resource.foundry` on every apply purely to rewrite a string. Section B and
   Blocker 1 record that this preview resource accepts and silently drops configuration;
   re-PUTting it with no intended change is gratuitous exposure. Its `output` and the
   `foundry_endpoint` output both went to `(known after apply)` as a result.
2. **The control could never pass.** An auditor asking "what else changed between your
   two runs?" got "24 resources, unknown."

**Fixed by removing the `DeployedOn` tag from both modules** rather than stabilising it.
Nothing consumes it — not `tasks/`, not `scripts/`, not any KQL in `docs/telemetry-map.md`
— and the deploy time is already in the resource's own ARM metadata and in git history. A
timestamp that lies on every plan is worth less than no timestamp. If a deploy marker is
ever wanted back it must come from a variable the operator sets deliberately, or be
`lifecycle`-ignored; never from a function that re-evaluates at plan time.

**General rule:** no plan-time-varying function (`timestamp()`, `uuid()`,
`bcrypt()`) belongs in any attribute of a persistent resource in this repo. Treat a
non-empty plan on an unchanged configuration as a defect, not as background noise.

### C7. Cluster workloads are kubectl + kustomize, not terraform — CHANGED 2026-10-08

The harness pod, its ServiceAccount, its Secret and its namespace used to be an
`infra/k8s` terraform root module. That module is deleted.

**What happened.** `hashicorp/kubernetes` 2.38.0 on terraform 1.16.4 wrote
`kubernetes_deployment_v1.harness` into state **tainted**, with
`identity = {api_version: null, kind: null, name: null, namespace: null}`, after the first
apply failed on the rollout wait. The namespace, Secret and ServiceAccount in the same
apply all persisted populated identities; only the resource that errored did not. Every
refresh afterwards read back the real `apps/v1 / Deployment / agent-harness /
<namespace>` and terraform core rejected the delta with `Unexpected Identity Change`. The
module could not be planned or applied again without editing the state file by hand.

This was not a configuration error, and nothing in the module would have prevented it. The
general shape — a provider that must talk to a data plane which may be slow, holding state
that must stay consistent with that data plane — is the same shape as the Foundry data
plane problem in §B9. Where a resource is a long-lived cluster object rather than an Azure
resource, manifests have no state to corrupt and are the cheaper failure mode.

**The replacement.** `deploy/kustomize/base/` holds the four manifests with committed
`REPLACE_WITH_*` placeholders. `task cloud:harness-up` streams
`kustomize build | sed | kubectl apply --server-side --force-conflicts -f -`, substituting
from `terraform output -raw` against `infra/cloud`. The files on disk are never mutated,
so a half-finished apply cannot leave a credential in the working tree. `lint:manifests`
fails if any placeholder in the manifests has no substitution in the task.

**Adoption, and why `--server-side --force-conflicts`.** The four objects already running
in the cluster were created by terraform's field manager (`Terraform`) and carry no
`kubectl.kubernetes.io/last-applied-configuration` annotation. A client-side
`kubectl apply` three-way-merges against that annotation; with no annotation there is no
prior state to merge against, and the result on fields terraform set is not reliably
predictable. Server-side apply reads the real `managedFields` instead, and
`--force-conflicts` transfers ownership of every field in the stream from `Terraform` to
`kubectl`. **The objects keep running — adoption changes ownership metadata, not the
workload.** Expect the first apply to report `configured` rather than `created`, and
expect a pod restart only if a substituted value genuinely differs from what terraform
applied. After the first run `--force-conflicts` is a no-op for this stream; the flag is
left in so the first run and every later run use identical flags.

`terraform destroy` was NOT run against the old module, deliberately — that would have
deleted the live objects. Deleting `infra/k8s/terraform.tfstate` along with the module is
the adoption mechanism.


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

`google-adk` **2.11.0** on PyPI (installed and verified 2026-10-07). PyPI metadata says `requires_python = ">=3.10"`; the GitHub
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

**NOT FOUND in documentation**, but **resolved empirically on 2026-10-07**: LiteLLM 1.104.0
*does* support a rotating token-provider callback. `azure_ad_token_provider` is present in
`litellm.types.utils.all_litellm_params` and is consumed by
`litellm.llms.azure.common_utils.BaseAzureLLM`, whose own source comments that
"`azure_ad_token_provider` directly preserves Azure AD token refresh".

**Consequence:** we use `get_bearer_token_provider(DefaultAzureCredential(), scope)` and pass
the callable, not a static `AZURE_AD_TOKEN`. A static token would expire during a long-running
hosted agent session. No API key is used anywhere.

- https://google.github.io/adk-docs/agents/models/litellm/
- https://docs.litellm.ai/docs/providers/azure
- `litellm/llms/azure/common_utils.py` (installed 1.104.0, read locally)

### E3. Avoiding duplicate tracer providers

Code-verified in `google/adk-python:src/google/adk/telemetry/setup.py`. The
`maybe_set_otel_providers()` docstring: *"If a provider for a specific telemetry type was
already globally set - this function will not override it or register more exporters."*

**Therefore:** the Foundry host configures OpenTelemetry for us when
`ResponsesAgentServerHost()` is constructed — observed directly, see A3. As long as the host is
constructed **before** ADK initialises, ADK detects the existing global provider and no-ops, so
there is no duplicate export and we do not configure a `TracerProvider` ourselves in the hosted
path. Import/construction order is a correctness requirement here, not a style preference.

### E4. Google telemetry export is off by default

Exporters are only constructed when the relevant OTLP env vars are set, or when Cloud Trace is
explicitly opted into (`adk web --otel_to_cloud`, or
`get_gcp_exporters(enable_cloud_tracing=True)`). Opt-in by omission; there is no separate
disable flag to set. We simply never opt in.

- https://google.github.io/adk-docs/observability/traces/

---

## Blockers

### Blocker 0 (RESOLVED) — OpenTelemetry dependency conflict between ADK and the agent server

Discovered on first install, not from documentation. The two packages this entire repository
depends on **cannot be co-installed under their declared constraints**:

```
google-adk 2.11.0                 requires opentelemetry-api >=1.39, <=1.42.1
azure-ai-agentserver-core 2.2.0   requires opentelemetry-api >=1.43.0, <2.0.0
```

This is not a stale-version problem. Checked across releases on 2026-10-07: **every**
`google-adk` version from 2.8.0 through the latest 2.11.0 caps at `<=1.42.1`, and **every**
`azure-ai-agentserver-core` release including `2.0.0b9`, `2.1.0` and `2.2.0` requires
`>=1.43.0`. There is no compatible pair.

**Resolution, tested:** ADK's upper bound is conservative rather than load-bearing. With a
dependency override to `opentelemetry-api/sdk >=1.43,<2`, both packages install and function
on **1.44.0**. Verified by smoke test: `ResponsesAgentServerHost` constructs, `LlmAgent` builds
with a `LiteLlm` model and a registered `FunctionTool`, and `google.adk.telemetry.tracer`
resolves.

**Why this is recorded rather than quietly worked around:** the override is a deliberate,
tested decision to run ADK outside its declared support window. If ADK begins using an
OpenTelemetry API removed after 1.42.1, this breaks at runtime rather than at install time.
The override lives in `pyproject.toml` under `[tool.uv]` with a pointer to this section, and
the unit suite asserts that both libraries import and that the tracer provider is not
double-registered. Revisit when ADK relaxes its pin.

### Blocker 1 — managed VNet + egress policy composability is undocumented

**Status: stage 1 PASSED on 2026-10-07. The architecture decision is unblocked. The
enforcement question remains open and is stage 2's job.**

#### Stage 1 result — what was actually observed

A probe (`infra/spike`) applied a Foundry account carrying
`properties.networkInjections` with `useMicrosoftManagedNetwork = true`, alongside two
`raiPolicies` carrying `egressPolicy`. Verified by reading the configuration **back from
ARM**, not from Terraform state, so what is recorded here is what the platform kept
rather than what Terraform believed it wrote.

| Observation | Result |
| --- | --- |
| Foundry account with `networkInjections` + `publicNetworkAccess: Disabled` | **Created, and stored verbatim** |
| `raiPolicies` with `egressPolicy`, Audit and Enforced | **Created, and stored verbatim** |
| Any property silently dropped or defaulted | **None** |

Read back from ARM (`eastus2`, account API `2025-10-01-preview`, policy API
`2026-05-15-preview`):

```jsonc
// account
"networkInjections": [
  { "scenario": "agent", "subnetArmId": "", "useMicrosoftManagedNetwork": true }
],
"publicNetworkAccess": "Disabled"

// both policies, differing only in egressPolicy.mode
"egressPolicy": {
  "defaultAction": "Deny",
  "mode": "Audit",           // and "Enforced" on the sibling policy
  "rules": [
    { "name": "allow-policy-api", "ruleType": "Fqdn",
      "match": { "host": "..." }, "action": { "actionType": "Allow" } }
  ]
}
```

So: **a managed VNet and network egress policies can coexist on one Foundry account.**
The undocumented combination is accepted and persisted intact. Option 2 below is viable
and option 1 is no longer forced.

#### What stage 1 does NOT establish

This is control-plane acceptance. It says nothing about:

* whether the egress policy is actually enforced at the data plane;
* which layer wins when both the managed network and the egress policy apply;
* whether a denied request is attributable to the egress policy rather than to the
  managed network's own routing.

That last point is the one that matters for the demo's central claim, and it is exactly
what a passing stage 1 cannot answer. **Stage 2 — a real agent making real calls under
each policy — is the test.** Until then, no document may describe containment as proven.

#### API requirements discovered empirically

None of these are in the egress-controls documentation. All were found by failed applies.

1. `basePolicyName` is mandatory on a custom RAI policy; omitting it returns
   `400 Resource has invalid base policy`. Valid values are account- and
   API-version-specific, so read them from the account (`task spike:base-policies`).

   **Confirmed by listing, 2026-10-07**, on an `AIServices` account in `eastus2` at API
   version `2026-05-15-preview`:

   | Name | `properties.type` | `properties.mode` | `egressPolicy` |
   | --- | --- | --- | --- |
   | `Microsoft.Default` | `SystemManaged` | `Blocking` | `null` |
   | `Microsoft.DefaultV2` | `SystemManaged` | `Blocking` | `null` |
   | `Microsoft.MAIDefault` | `SystemManaged` | `Blocking` | `null` |

   No system policy carries an `egressPolicy`, so egress is something a custom policy
   **adds**, never something it overrides.
2. `properties.type` is set to `UserManaged` on both policies. Added at the same time as
   `basePolicyName`; **not independently confirmed as required.**
3. `properties.contentFilters` is also mandatory — the create fails with
   `Content filters cannot be null` even when a base policy is named. A custom policy
   does **not** inherit the base's filters implicitly.

   The probe supplies the 19 filters read verbatim from `Microsoft.DefaultV2`, shared by
   both policies through one Terraform local. Content filtering is not the variable under
   test, so holding it identical by construction keeps any difference in outcome
   attributable to `egressPolicy.mode` alone.
4. `properties.mode` (content safety) is set to `Blocking` in both policies, matching the
   value the system policies report. `Default` appears in the documented enum but was not
   exercised; `Blocking` is known-good here.
5. A direct `GET` on a system-managed policy returns **404**, even though the same policy
   is present in the `raiPolicies` collection. The collection is the only way to read a
   base policy's contents.
6. `azapi` v2 exposes `output` as a decoded object, not a JSON string. `jsondecode()` on
   it errors, and a wrapping `try()` will swallow that into a silently missing output.

#### Options, in order of preference

1. **No managed VNet on the Foundry account for this demo.** Private endpoints still protect
   the backing resources (ACR, Key Vault, Log Analytics, storage). The experiment stays clean.
2. **Managed VNet, but prove composability empirically first.**
   *Stage 1 passed: the configuration is accepted and stored intact. Composability at the
   control plane is established; enforcement attribution is not.*
3. Build both and compare. Most expensive; most complete evidence.

**Still true regardless:** if the demo runs with a managed VNet, the report must show that
a denial is attributable to the egress policy and not to managed-network routing. A
single-variable claim needs single-variable evidence, and stage 1 does not supply it.


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

### Blocker 5 — incoming A2A is unconfirmed for hosted *container* agents

**Status: UNVERIFIED. Must be spiked before Phase 9 builds the direct path.**

The on-premises side of this demo is a full agentic harness that invokes the Foundry
hosted agent over A2A. The protocol itself is well documented and **v1.0 is GA**, but the
documentation's supported-agent story does not clearly cover our case.

What the primary source says (accessed **2026-10-08**,
https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint,
`ms.date: 2026-09-11`):

- "Incoming A2A requires the responses protocol." **Our agent uses exactly that** — it is
  hosted on `ResponsesAgentServerHost` — so it plausibly qualifies.
- **But the only agent type explicitly blessed is the prompt agent:** "Prompt agents
  support the responses protocol by default, and you can expose them as A2A endpoints."
  The prerequisites likewise name "a deployed **prompt agent**".
- Nothing found in any primary source confirms *or* denies that a custom hosted container
  agent can be exposed over incoming A2A.

**Do not write A2A-on-hosted-agents into any report as tested until a spike proves it.**

**Fallback, and why it is cheap.** If the spike fails, the harness calls the agent over the
Responses protocol directly. Containment is unaffected: the protocol the harness uses to
*reach* the agent has no bearing on what the agent's tools can *reach*. Record the
substitution rather than hiding it.

#### Verified A2A facts (same source and access date)

| Item | Value |
| --- | --- |
| Versions | **1.0 GA**, 0.3 preview, same base path |
| Transport | v1.0 is **JSONRPC only**; v0.3 also allows HTTP+JSON; gRPC on neither |
| Auth | **Microsoft Entra ID only.** Key-based and anonymous unsupported, *including for the agent card* |
| Caller role | **Foundry Agent Consumer**, `eed3b665-ab3a-47b6-8f48-c9382fb1dad6`, assignable at project or single-agent scope |
| Token scope | `https://ai.azure.com/.default` |
| Enablement | `PATCH $BASE_URL/agents/$AGENT_NAME?api-version=v1` setting `agent_card` + `agent_endpoint.protocol_configuration.{responses,a2a}`. **Not available in the portal** |
| Python SDK | `azure-ai-projects>=2.5.0`, `project.agents.update_details(...)` |
| Endpoint | `…/agents/{agent}/endpoint/protocols/a2a` |
| Agent card | `…/a2a/agentCard/v1.0` and `…/agentCard/v0.3` — **not** `.well-known/agent-card.json` |
| Client libs | `a2a-sdk==1.0.2`, `azure-identity==1.25.3`, `httpx==0.28.1` |
| Retention | A2A tasks and contexts kept **60 days** from most recent write |

**Two traps worth their own lines.**

1. **Unversioned requests get PREVIEW v0.3, not GA v1.0.** Pin explicitly via
   `A2A-Version: 1.0`, `?a2a-version=1.0`, or by resolving the v1.0 card — otherwise the
   demo silently runs on a preview protocol while the report claims GA. Supplying the
   header and query string with *different* values returns HTTP 400 `version-ambiguous`.
2. **The agent card lives at a non-standard path.** Generic A2A SDK resolvers default to
   `.well-known/agent-card.json` and will miss it; pass an explicit `agent_card_path`.

#### MCP is excluded from the containment path — by design, not oversight

Accessed **2026-10-08**,
https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol
(`ms.date: 2026-08-26`).

Foundry agents are MCP **clients**: they connect out to remote MCP servers to gain tools.
No primary source documents exposing a Foundry agent *as* an MCP server, so "harness
reaches Foundry over MCP" is not a supported topology.

The supported direction would actively break this demo. An on-premises MCP server consumed
by the agent means the agent makes an **outbound call to an on-premises host** — precisely
the egress path under test. That host would need to be in the allowlist, the on-premises
boundary would become a third variable, and a denial would no longer be attributable to
the egress policy alone. Keep MCP out of the containment path.



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
8. Hosted-agent- and egress-specific region support in general: still no published table
   (A2, B1). East US 2, Sweden Central and Canada Central are each backed by a spike rather
   than by documentation (A2a); any further region needs its own spike.
9. Whether ADK remains functional against `opentelemetry-api` 1.43+ at **runtime** under real
   load, not just at import (Blocker 0). The smoke test covers import and agent construction
   only.
10. The agent-version **status vocabulary on the wire** (B9b). `deploy.py` waits for the
    literal `"active"`, taken from the SDK enum; no live response has yet been observed
    carrying a terminal status. The 900s timeout's error message is the mechanism for
    learning it, because the data plane is private-endpoint-only.

### Resolved since first draft

| Item | Result | How |
| --- | --- | --- |
| `azure-ai-agentserver-*` version (A4) | **2.2.0** | Installed 2026-10-07 |
| `google-adk` version (E1) | **2.11.0** | Installed 2026-10-07 |
| Built-in `/readiness` route (A3) | Confirmed, provided by the package | Route table inspected |
| Who configures OpenTelemetry (E3) | The Foundry host, on construction | Observed log line |
| LiteLLM rotating Entra token (E2) | **Supported** via `azure_ad_token_provider` | Source of installed 1.104.0 |
| ADK + agent server co-install (Blocker 0) | Conflict confirmed; override tested working on otel 1.44.0 | Install + smoke test |
| Sweden Central viability (A2a) | **Passed** — managed VNet and both egress policies stored | Spike + ARM read-back, 2026-10-08 |
| Canada Central viability (A2a) | **Passed** — identical result; selected target | Spike + ARM read-back, 2026-10-08 |
| Canada East viability (A2b) | **Not viable** — Postgres restricted | Capabilities API, 2026-10-08 |
| Postgres region restriction (A2b) | East US 2 restricted; Sweden Central clear | Capabilities API, 2026-10-08 |
| State store must back actors (A2c) | PostgreSQL qualifies; Table/Blob do not | Dapr component reference, 2026-10-08 |
| Server-side digest acceptance (B9, B9a) | **Accepted** — `repo@sha256:<64 hex>` took HTTP 200 | Live deploy from inside the VNet, 2026-10-08 (B9b) |
| `agents/versions` write permission (B9b) | **Sufficient** — `Cognitive Services User` at account scope created and read a version | Live deploy, 2026-10-08 |
| Data-plane `api-version` value (B9a) | **`v1`** accepted; not a preview date string | Observed request URL, 2026-10-08 |
| Workload identity on the deploy path (B9b) | **Works** — `ManagedIdentityCredential` used the projected token | Init container log, 2026-10-08 |

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
| [Enable an agent-to-agent (A2A) endpoint](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint) | 2026-10-08 |
| [Connect agents to MCP server endpoints](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol) | 2026-10-08 |
| [Limits, quotas and regions](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions) (re-accessed for Sweden Central) | 2026-10-08 |
| [Dapr supported state stores](https://docs.dapr.io/reference/components-reference/supported-state-stores/) | 2026-10-08 |
