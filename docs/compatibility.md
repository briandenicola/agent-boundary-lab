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

1. Whether `DEMO_AZURE_OPENAI_API_VERSION` (was `2024-10-21`; see E2a), serves the gpt-5
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
    "container_protocol_versions": [{ "protocol": "RESPONSES", "version": "v1" }],  // v1: accepted at create, REJECTED at invoke - see B9d
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

### B5b. Run id in the URL path (GATE 0 experiment, PROPOSED / UNVERIFIED, 2026-10-09)

Observed (docs/telemetry-map.md §0.11): `NetworkEgressDecision` rows carry the destination URL path but not the query string and no run id, so the `?demo_run_id=` marker does not join.

Proposed: both tools append the run id as the final path segment (`/policy/{run_id}`, `/ingest/{run_id}`; `tools._endpoint`), identical for both agents. The run id must match `[A-Za-z0-9_-]{1,64}` or the tool fails locally before any request. The services accept the new routes, keep the old ones, and log the path run id. UNVERIFIED until a real decision row shows the run id in its path; if it does not, this stays INCONCLUSIVE and nothing here counts as a join.

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
response. The vocabulary is settled on that basis — see B9b, which also records the
case-insensitivity hint and why `deploy.py` already handles it.

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

#### Version status vocabulary — ~~RESOLVED from the SDK enum~~ **WRONG. SUPERSEDED BY B9c.**

> **This subsection was wrong and is kept only as the record of how.** It called the
> vocabulary "settled" on the strength of a client-library enum, and that conclusion cost
> 45 minutes of wall clock on 2026-10-08. The enum is **incomplete** relative to the running
> service. Read **B9c** instead. Everything below the line is retained verbatim so the
> reasoning error is legible, not to be relied on.

`AgentVersionStatus` (`azure/ai/projects/models/_enums.py`) declares exactly five values:

| Value | SDK comment |
| --- | --- |
| `creating` | The agent version is being provisioned. |
| `active` | The agent version is active and ready to serve requests. |
| `failed` | The agent version provisioning failed. |
| `deleting` | The agent version is being deleted. |
| `deleted` | The agent version has been deleted. |

The enum is declared `class AgentVersionStatus(str, Enum, metaclass=CaseInsensitiveEnumMeta)`.

~~**`src/containment_demo/deploy.py` is already correct and needs no change.**~~
**It was not correct.** This paragraph is the specific error. See B9c.

`_TERMINAL_OK = "active"` (line 78) matches the enum exactly; `_TERMINAL_BAD =
{"failed", "deleting", "deleted"}` (line 79) matches exactly; and `_status_of()` (lines
297–299) already calls `.lower()`, which is precisely what `CaseInsensitiveEnumMeta`
implies is necessary — the metaclass exists because the service may return different
casing. `creating` is the only non-terminal value, so that is what the service must be
returning while the init container polls.

**Mind the class of fact.** This is read from the **client library's declared enum**, which
is the SDK's claim about the service. It is strong evidence and it is sufficient to call
the vocabulary settled. It is **not** the same class of fact as the live 200s, URL and
headers above: no status string has yet been observed coming back from the service in a
response body. Do not describe it as observed.

Read on 2026-10-08 from `azure-ai-projects` **2.4.0** at
`/home/brian/.local/lib/python3.10/site-packages/azure/ai/projects/models/_enums.py`. The
container that ran the live deployment uses **2.8.0** (B9b, above). The enum was not read
from the version that actually ran, and that difference is recorded rather than glossed:
if 2.8.0 widened the vocabulary, this table would be incomplete.

#### ~~OPEN — is a 900-second timeout long enough for provisioning?~~ **CLOSED, and the question was wrong**

> Provisioning took **under a minute**, not ten. The version was healthy the whole time;
> the poller could not recognise it. 900s was never too short — it was 7.5x too long, and
> it is now 120s. See B9c. Retained below as written.

This is the real open question left by the live run, and it replaces the vocabulary
question.

The version was still provisioning after roughly ten minutes.
`DeploySettings.deploy_timeout_seconds` defaults to **900.0** (deploy.py line 162), with a
`le=3600` bound, polled every 10 seconds. We do not yet know a typical or worst-case
provisioning time for a Foundry hosted agent, and no primary source states one.

**If 900s proves too short, the fix is a longer timeout.** It is not a change to the
success condition, and it is under no circumstances a decision to treat a timeout as a
pass. `deploy.py` already states this in its own words — a hung provision is a failure,
not a pending success — and that stays true. A timeout is an **inconclusive** result at
best; it tells you nothing about whether the version would have become active.

- SDK enum read 2026-10-08 from the installed 2.4.0 package; no primary source documents
  the wire-level status values or a provisioning-time expectation.

#### ~~OBSERVED 2026-10-08 — a version stuck in `creating`~~ **The premise was false. See B9c.**

> **CORRECTED 2026-10-09 — read B9e before trusting the paragraph below.** An earlier
> revision of this block went further than the evidence: it implied a pull permission was
> not needed. That overreached. Precisely:
>
> * **Disproven:** that a version stuck in `creating` indicates a missing pull permission.
>   The `creating` was never observed (B9c), and the 45-minute hang was the `str(enum)`
>   poller bug.
> * **NOT disproven:** that a pull permission is required. `active` was reported at
>   acceptance, before any pull. The pull happens afterwards and its failure surfaces later
>   as `failed` (B9e).
> * **Disproven in particular:** that the ACCOUNT identity's grant fixed anything — it was
>   applied after the version was `active` and the version later failed with ImageError.

> **The version was never stuck.** The Azure portal showed
> `containment-demo-audit | Version: 1 | Status: Running` at **18:39:26Z**, under a minute
> after creation. The init container was not observing a hung provision; it was failing to
> recognise a finished one, and logging nothing about it (B9c).
>
> **The `creating` in this entry was never observed.** It was *inferred* from the enum
> subsection above — `creating` was the only non-terminal value the enum declared, so it was
> assumed to be what the service was returning. The poller logged no status, so there was no
> observation to check the inference against. An inference from an incomplete enum was
> written down as an observation.
>
> **`azurerm_role_assignment.foundry_acr_pull` is retained** — the argument that no pull can
> succeed without `AcrPull` on the pulling principal stands on its own — but the evidence
> that motivated it has evaporated, and it must not be cited as a fix for anything. The
> symptom it was built to explain did not exist.

A version created successfully at 18:41 (HTTP 200, `Created version`) was still `creating`
15+ minutes later, with the init container still polling.

**The hypothesis, stated as a hypothesis.** The Foundry account carries a `SystemAssigned`
identity (`infra/cloud/foundry.tf`), and that principal had **no role on the container
registry**. `infra/cloud/acr.tf` granted `AcrPull` to the AKS kubelet identity and to the
Container Apps user-assigned identity, and `AcrPush` to the operator — but not to Foundry.
The hosted-agent runtime pulls the digest-pinned agent image **itself**, as a different
principal from the kubelet identity that pulls the harness image onto our own nodes. With
no `AcrPull`, that pull cannot authenticate.

This fits the symptom precisely: an unauthorised pull is **retryable, not fatal**, so the
version never transitions to `failed` and sits in `creating` instead. The control plane
accepted the version, so every signal we can see says success. It is a failure mode that
looks exactly like slow provisioning.

**It is not proven, and cannot be proven from outside.** The data plane is
private-endpoint-only, so the backend's actual pull error is not readable by the operator.
Nothing observed in this run names the registry or an authorisation failure. What is
recorded here is a hypothesis that fits the evidence, not a diagnosis.

**The role assignment is necessary regardless of whether it is sufficient.** No pull can
succeed without `AcrPull` on the pulling principal, so granting it is correct even if
something else is also wrong. Added as `azurerm_role_assignment.foundry_acr_pull`
(`infra/cloud/acr.tf`): `AcrPull` only, scoped to the registry, principal
`azapi_resource.foundry.output.identity.principalId`. `task cloud:plan` renders it as
`1 to add, 0 to change, 0 to destroy`.

**Confirmation is simply whether a version reaches `active` after the grant.** Nothing
subtler is available to us. If a version still hangs in `creating` with the role in place,
this entry is wrong or incomplete and must be corrected here rather than quietly
forgotten.

**Two things deliberately NOT done.**

1. The **project** (`azapi_resource.project`) also has its own `SystemAssigned` identity,
   and its `principalId` is not currently exported. If the account-level grant turns out to
   be the wrong principal, that is the next candidate — but no primary source states which
   identity Foundry uses to pull, so it is not being granted speculatively.
2. Foundry may additionally require an explicit **ACR connection resource** on the project,
   in the same family as the `AppInsights` connection in C5 — `ContainerConfiguration`
   carries a `registry_connection_id` field (B9a) which we leave unset. **No authoritative
   evidence was found either way.** This repository does not invent resource shapes; if a
   primary source turns up, record it here before implementing it.

- Observed 2026-10-08. Hypothesis, not a verified cause.

### B9c. The SDK status enum is INCOMPLETE — do not treat it as the contract

**Access date 2026-10-08.** This is the correction to the status subsections in B9b, and it
is the most generalisable finding in this document so far.

#### What happened

A hosted agent version was created at 18:39:26Z and the Azure portal showed it
`Status: Running` in under a minute — a healthy, fully deployed agent.
`wait_until_active` polled that same version for **45+ minutes** and never terminated.
Two independent defects, both traceable to trusting a type definition over a running
service:

1. **`_TERMINAL_OK = "active"` was derived from `AgentVersionStatus`.** The enum does not
   contain `running`. The service returns it.
2. **The poll loop logged nothing.** ~270 successful HTTP 200s produced not one line
   saying what status came back, so a healthy deployment and a hung one emitted
   byte-identical output: silence. Meanwhile azure-core's `http_logging_policy` filled the
   log with request/response headers, so the container *looked* busy while saying nothing
   that mattered.

An entire ACR role-assignment theory was built and applied to explain a problem that did
not exist.

#### The status vocabulary that is actually true

From **Brian's working production implementation**,
`briandenicola/banking-agent-foundry-orchestrator`, `src/agents/deployer/deploy.py` lines
20–21, read 2026-10-08:

```python
READY_STATUSES   = {"active", "running"}
PENDING_STATUSES = {"creating", "starting", "updating"}
```

`running`, `starting` and `updating` are **absent from `AgentVersionStatus`**. The portal
independently showed `Running`, matching this set. This is observed production behaviour
across two independent sources, not a portal label.

| Status | In SDK enum? | Source |
| --- | --- | --- |
| `active` | yes | `models/_enums.py:380` + reference `READY_STATUSES` |
| `running` | **no** | reference `READY_STATUSES`; portal, 2026-10-08 |
| `creating` | yes | enum + reference `PENDING_STATUSES` |
| `starting` | **no** | reference `PENDING_STATUSES` |
| `updating` | **no** | reference `PENDING_STATUSES` |
| `failed` | yes | enum; reference fails fast on it |
| `deleting` / `deleted` | yes | `models/_enums.py:380` |

#### The second bug: `str()` on an SDK enum member never matched anything

Verified 2026-10-08 by deserialising each case against **azure-ai-projects 2.8.0**:

| Wire value | Deserialises to | `str(...)` returns |
| --- | --- | --- |
| `"active"` | `AgentVersionStatus.ACTIVE` | `'AgentVersionStatus.ACTIVE'` |
| `"running"` | plain `str` | `'running'` |
| `"Running"` | plain `str` | `'Running'` |
| `"creating"` | `AgentVersionStatus.CREATING` | `'AgentVersionStatus.CREATING'` |
| `"weird-new-status"` | plain `str` | `'weird-new-status'` |
| `AgentVersionStatus("Running")` | — | raises `ValueError` |

`AgentVersionStatus` is a `(str, Enum)` mixin, so `str(member)` yields the **qualified name**,
not the value. The old `str(status).lower()` therefore produced
`'agentversionstatus.active'`, which can never equal `'active'`. **The poller could not have
terminated on success even if the service had said `active`.** Values outside the enum pass
through as plain `str`, unmangled — so reading `.value` with the raw object as fallback is
correct for both cases. That is what `_normalise_status()` now does.

#### The rule this establishes

**A client library's enum is the SDK's claim about the service, not the service's contract.**
It can be stale, partial, or generated from a different API version than the one answering
the call. Where a value drives a success condition, verify it against a running service or a
known-working implementation. Where neither is available, the code must handle an
unrecognised value **loudly and boundedly** — never silently as success, never as pending
forever.

`briandenicola/banking-agent-foundry-orchestrator` is a **primary reference for Foundry
hosted-agent behaviour** and should be consulted *before* deriving behaviour from SDK type
definitions.

#### What `deploy.py` does now

* Ready / pending / failed **sets**, cited inline to the reference and the portal observation.
* **Bounded** `for attempt in range(1, attempts + 1)` — a bounded loop cannot fail to
  terminate, which the previous `while True` plus monotonic deadline demonstrably did.
  `attempts = ceil(timeout / poll)`, so the iteration bound and the time budget cannot
  disagree.
* Status logged on **every** poll with agent, version, verbatim status, attempt and elapsed.
* Fail-fast on `failed`, including the service error payload.
* An unrecognised status logs a **WARNING every time it is seen** with the verbatim string,
  and raises `UnrecognisedStatusError` at the bound.
* Timeout is a **failure**, never an optimistic pass. Unchanged, and it stays.
* `deploy_timeout_seconds` **900 → 120** (`le` 3600 → 600); `deploy_poll_seconds` 10 → 3;
  `deploy_request_timeout_seconds` 60 → 15; new `deploy_retry_total=2` so SDK retries
  cannot consume the budget inside a single call.
* `azure.core.pipeline.policies.http_logging_policy` turned down to WARNING so it stops
  burying our own lines.

#### RESOLVED — observed 2026-10-08 19:35Z

**The service returns `active`.** Observed directly, on our own account, with the fixed
poller logging every poll:

```
containment-demo-audit:    created version 2 (status='active')  ready after 0.0s
containment-demo-enforced: created version 1 (status='active')  ready after 0.0s
```

Both versions matched on **attempt 1 of 40, at elapsed 0.0s**. Total wall clock for both
agents: ~4 seconds.

Consequences, stated plainly because the earlier entries in this section guessed wrong:

* `active` — the SDK enum value — was correct all along. The enum is **not** incomplete for
  the ready state, contrary to what B9b asserted above. Those paragraphs are superseded by
  this measurement; they were written from the reference implementation and a portal label,
  neither of which is this service's wire value.
* The portal's `Running` is a **display label**, not an API status. A portal string is not
  an API contract — that caution was right even though the conclusion drawn from it was not.
* `running` remains in `_READY_STATUSES`. It has never been observed by us and is retained
  only because the reference implementation accepts it in production. It is defensive, not
  evidence-backed. Do not cite it as observed behaviour.
* The 45-minute hang was **entirely** the `str(enum)` defect — `'agentversionstatus.active'`
  never equals `'active'`, so the poller could not terminate on success under any status
  vocabulary. Widening the accepted set would not have fixed it. The status vocabulary was a
  red herring we spent a day on.

**The generalisable lesson.** Three separate theories — ACR pull permissions, an incomplete
status enum, a broken timeout — were each constructed to explain a *silence*. All three were
wrong. One log line of the observed value would have ended it in seconds. This repository's
own evidence rule says missing evidence is **inconclusive, never a signal**; that rule
applies to debugging this demo, not only to the demo's findings.

Sources: `briandenicola/banking-agent-foundry-orchestrator`
`src/agents/deployer/deploy.py` lines 15–21 and 417–433, fetched 2026-10-08; Azure portal
agent blade, 2026-10-08; `azure-ai-projects` 2.8.0 `models/_enums.py:380` and a live
deserialisation test, 2026-10-08.

### B9d. Protocol version `v1` — accepted at create, rejected at invoke

**Access date 2026-10-09.** First live invocation returned HTTP 400:

> `Unsupported responses protocol version '' for agent 'containment-demo-audit:3'. Please use version '2.0.0'.`

Auth and routing worked (workload identity token; request reached
`/agents/<name>/endpoint/protocols/openai/responses?api-version=v1`). `v1` was **accepted**
by `create_version` and **rejected** at invoke; the service reports the registered version
as `''`. Brian's reference deployer registers `{"protocol": "invocations", "version": "2.0.0"}`
(`banking-agent-foundry-orchestrator` `src/agents/deployer/deploy.py:171`).
`DEMO_AGENT_PROTOCOL_VERSION` now defaults to `2.0.0`.

**2.0.0 is UNVERIFIED until a live invoke succeeds.** The empty `''` is a hypothesis-grade
reading, not an explained cause. Create-time acceptance proves nothing about invoke-time validity.

Invoke client (read from azure-ai-projects 2.8.0 `_patch.py:55-86`): `get_openai_client(agent_name=...)`
sends only the `api-version` query and the `Foundry-Features` header. It sends no protocol-version
header or parameter, so the registered version is the only input; `invoke.py` needs no change.

### B9e. ImageError on a registry the account identity can pull from — OBSERVED 2026-10-09

**Observed by read-only platform queries, 2026-10-09.** Agent version
`containment-demo-audit:4`, via `get_version`:

```
status: failed
error:  {code: 'ImageError',
         message: 'Container registry authentication failed. Verify the workspace managed
                   identity has AcrPull permissions on the target registry.'}
```

#### Verified

* The version FAILED on registry authentication, after having been accepted. The platform
  itself names the cause and the remedy (AcrPull for "the workspace managed identity").
* `AcrPull` on `humblephoenix46689acr` was held by **three** principals, including the
  Foundry **account** identity `ca6f9297-24b0-495e-ace9-d08612b126f1` (our
  `foundry_acr_pull`) and **not** the Foundry **project** identity
  `7b9ae858-ac04-4374-ab45-224f89b4451b`.
* The working reference (`banking-agent-foundry-orchestrator` `apps/roles.tf`, fetched
  2026-10-08) grants `AcrPull` to the **project** identity
  (`data.azapi_resource.foundry_project.identity[0].principal_id`).

#### What this changes about B9b and B9c

* **`active` means accepted, not pulled.** A version reports `active` when the control
  plane accepts it; the image pull happens afterwards. Readiness must therefore be judged
  by a state reached after the pull, not by the first `active`. Open: which state that is.
* **Both defects were real.** The `str(enum)` poller bug (B9c) was real and is fixed. A
  pull permission is *also* required. The earlier "DISPROVEN" wording conflated them.
* **The earlier 19:35Z "healthy" observation did not demonstrate a successful pull**, only
  acceptance — so it cannot be cited as evidence the pull worked without a role.

#### STRONGLY INDICATED, UNVERIFIED — the PROJECT identity is the one that needs it

Three things point at the project: the error text says "workspace" (AzureML's word for the
project), the project identity is the one without the grant, and the working reference
grants it. That is strong circumstantial evidence, **not a verification.** It is verified
only when a version reaches a pulled/running state after the grant. Until then the account
grant is neither shown required nor shown unnecessary; it is kept (`acr.tf`) and can be
pruned once a version pulls with only the project grant.

Proposed, not applied: `azurerm_role_assignment.foundry_project_acr_pull`
(`infra/cloud/acr.tf`), principal `azapi_resource.project.output.identity.principalId`.
`task cloud:plan` renders `1 to add, 1 to change, 0 to destroy`; the change is the
project's `response_export_values` gaining `identity.principalId` (a read-back, no
property change).

#### The version LIST endpoint is not trustworthy for readiness

The same v4 showed **ACTIVE** from the version list endpoint while `get_version` returned
**FAILED**. Do not use list status to decide readiness or failure; use `get_version` (and
even then, see the open question above about what state proves a pull).

### B9f. The agent's model call needs a role for the agent's OWN identity — OBSERVED 2026-10-09

**Access date 2026-10-09.** Evidence: App Insights (Lambert), run `invoke-acad5487adaa`,
agent `containment-demo-audit` version 7. The model call
`POST https://humble-phoenix-46689-foundry.cognitiveservices.azure.com/openai/v1/responses?api-version=v1`
was **allowed by egress** and failed authorisation: *"The principal 842d7e21-e602-4dc1-812e-947fd5833cb3
lacks the required data action Microsoft.CognitiveServices/accounts/OpenAI/responses/write
to perform POST /openai/v1/responses operation."* Read-only `az` showed that principal
held no role assignment.

#### Which principal — VERIFIED against Entra (read-only Graph, 2026-10-09)

* `842d7e21-…` is a Graph `agentIdentity` service principal named
  `<account>-<project>-containment-demo-audit-AgentIdentity`, tagged
  `agentName:containment-demo-audit`, `accountName`, `projectName`, `agentGuid:148cc3f7-…`.
  **It is the principal that needs the role.**
* `9260cba6-…` is the sibling `…-containment-demo-audit-148cc-AgentIdentityBlueprint`. Per
  the docs the blueprint authenticates to Entra via the project's managed identity; it "doesn't
  directly access the downstream resource" and needs no role. It carries the same tags, so a
  tag-only lookup returns BOTH — filter to `-AgentIdentity`.
* **Per agent, not per version.** Exactly one `-AgentIdentity` exists per agent, created at
  the first version create (audit 2026-10-08T18:39:19Z, enforced 19:35:22Z), though audit
  has had ≥7 versions. **Distinct per agent**: audit `842d7e21`, enforced `4c7579f9`. A
  separate project-level shared `-project-AgentIdentity` also exists (`21c0c3e7`).
  Observed, not documented as a contract: recreating an agent can mint a new identity, so
  nothing may hardcode these ids.

#### Which role — dataActions read verbatim from `az role definition list`, 2026-10-09

| Role | dataActions covering the failing action |
| --- | --- |
| **Cognitive Services OpenAI User** (`5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`) | `…/accounts/OpenAI/responses/*`, plus chat/completions, embeddings, `*/read`, assistants/*, etc. NotDataActions: `OpenAI/stored-completions/read` |
| Cognitive Services OpenAI Contributor (`a001fd3d-…`) | `Microsoft.CognitiveServices/accounts/OpenAI/*` |
| Azure AI Developer (`64702f94-…`) | `OpenAI/*` + Speech, ContentSafety, MaaS. Docs say it is **insufficient for hosted agents** |
| Foundry User (`53ca6127-…`) | `Microsoft.CognitiveServices/*` minus three NotDataActions |
| Cognitive Services User (`a97b65f3-…`) | `Microsoft.CognitiveServices/*` minus the same three |
| "Azure AI User" | returned no definition by that name; it is the **old name of Foundry User** (docs: renamed, same id) |

**Least privilege: Cognitive Services OpenAI User.** `responses/*` covers `responses/write`;
Foundry User / Cognitive Services User are far wider. The docs name exactly this as the
account-level answer.

Primary source: `learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agent-permissions`
("Account-level access" and "Agent access beyond defaults"), accessed 2026-10-09: when agent
code **bypasses the project endpoint and calls the account-level OpenAI endpoint directly**
(`https://{account}.cognitiveservices.azure.com`), the agent identity needs Cognitive Services
OpenAI User or Foundry User at account scope. Via the project endpoint, inference is
**implicit** and needs no assignment. Our `agent.py:83` uses the account endpoint with scope
`https://cognitiveservices.azure.com/.default`, which is exactly the documented case.

#### Same page, two statements that bear on B9e (accessed 2026-10-09)

* The **project's** managed identity pulls the image; docs prefer **Container Registry
  Repository Reader** over AcrPull, at registry scope. Consistent with the project grant.
* ACR must have `azureADAuthenticationAsArmPolicy` enabled, and the project has an **ACR
  connection**. We have not verified either on our registry/project. Not implemented.

#### Options and failure modes — PROPOSED / UNVERIFIED

| Option | How | Failure mode |
| --- | --- | --- |
| **A. Use the project endpoint** | Agent code calls `…services.ai.azure.com/api/projects/<p>` — implicit access, **no role at all** (docs) | Changes the model HOST, which is on the egress allowlist, so Brett + Lambert + Ripley own it; unverified that it works under our private networking. Best least-privilege outcome if it does. |
| **B. Task step (recommended)** `task cloud:agent-access-up` | Tag-keyed lookup of each `-AgentIdentity`, grant OpenAI User on the account, idempotent; `…-plan` is read-only | Operator can forget it (symptom: the exact error above); recreating an agent mints a new identity and the grant must be re-run; uses `az`, allowed in `tasks/` only |
| C. Terraform data lookup | `azuread` data source on the identity | Needs a new provider; the identity does not exist at first plan so a fresh environment fails to plan (forces a two-phase apply); drifts when an agent is recreated |
| D. A scope that covers the identities | none | There is no such scope: the identities are principals. Granting the role to the project identity does not help, the token is the agent identity's |

Recommendation: **B now**, same role at the same scope for both agents so audit-vs-enforced
stays the only variable; **A** as a follow-up if Brett can prove it under the egress policy,
which would remove the grant entirely. Nothing applied. `task cloud:agent-access-plan`
reported both identities MISSING the role on 2026-10-09.

### B9g. Hosted agent cannot reach a private-only account — PROPOSED / UNVERIFIED (2026-10-09)

Observed (Lambert, `telemetry-map.md` §0.9): after the OpenAI User grant the model call to
`humble-phoenix-46689-foundry.cognitiveservices.azure.com` is allowed by egress and the
account answers 403 `Public access is disabled. Please configure private endpoint.`

**Read-only state of our account (az rest, API 2025-10-01-preview, 2026-10-09):**
`publicNetworkAccess: Disabled`; `networkAcls: Deny`, no ip/vnet rules; one private endpoint
connection `humble-phoenix-46689-foundry-pe` **Approved** (in OUR vnet); `networkInjections`
= `[{scenario: agent, subnetArmId: "", useMicrosoftManagedNetwork: true}]`; account capability
host `…@aml_aiagentservice` Succeeded on a Microsoft-owned subnet; project capability hosts
none. `managednetworks/default`: `isolationMode: AllowInternetOutbound`, `managedNetworkKind: V2`,
Active, **`outboundRules: {}` (empty)**. The Foundry account identity holds only AcrPull on the
registry; it holds none of the roles named below.

**Documented** (primary: `github.com/microsoft-foundry/foundry-samples`, `infrastructure/infrastructure-setup-bicep/18-managed-virtual-network/README.md`, accessed 2026-10-09 — a Microsoft sample README, not a Learn page):
- Hosted agent containers run in the Microsoft-managed VNet. With `publicNetworkAccess: Disabled`
  they need an **outbound private-endpoint rule from the managed network back to the account**
  (`managednetworks/default/outboundrules/foundry-account-pe`, type `PrivateEndpoint`,
  `subresourceTarget: account`). Without it: "500 wrapping 403: Public access is disabled" —
  exactly our symptom. Your own VNet's private endpoint does not help this path.
- The account's managed identity needs `Azure AI Enterprise Network Connection Approver`
  (`b556d68e-0be0-4f35-a333-ad7ee1ce17ea`; verified by `az role definition list`: it grants
  private-endpoint-connection read/write/approval incl. `Microsoft.CognitiveServices/accounts/privateEndpointConnections/write`)
  and Contributor at resource-group scope for the rule to auto-approve.
- Isolation cannot be disabled once enabled; deleting the account deletes the managed VNet.
- The sample's list of supported regions includes Canada East but **not canadacentral**. Our
  managed network is nevertheless `Active` in canadacentral, so the list may be stale or
  not enforced; unverified either way.

**NOT documented / not established:** whether the Learn `agents-networking-deep-dive` and
`virtual-networks` pages (BYO-VNet only) cover this; whether the rule can be created while
the egress RAI policy is attached; whether the project endpoint (`services.ai.azure.com`)
takes a different route from `cognitiveservices.azure.com` from inside the managed network
(the sample's curl examples use the project endpoint and still say the hosted agent needs the
self-PE, which suggests no); how the sample's `az rest` rule creation maps to azapi.

| Option | What | Failure mode / design effect |
|---|---|---|
| **A. Self-PE outbound rule (recommended)** | azapi `Microsoft.CognitiveServices/accounts/managednetworks/outboundRules` (`foundry-account-pe`, PE → this account, `account`) + Network Connection Approver (+ Contributor at RG per sample) for the account identity | Rule is on the managed network, not the RAI policy, so the model-host allowlist is unchanged and identical for both agents. Risks: Contributor on the RG is broad (try Approver alone first and record); preview API; may incur managed-network cost; region support unconfirmed; may need the private DNS path to resolve inside the managed VNet (platform-managed, unobservable to us) |
| B. Point agent at project endpoint | Brett changes `agent.py` to `services.ai.azure.com` | Sample says hosted agents still need the self-PE; likely still 403. Changes the model host in the allowlist for both agents |
| C. Re-enable public access / networkAcls | Touch `foundry.tf` | Rejected: edits the experimental control surface and defeats the private-only design |
| D. BYO-VNet delegated subnet | Move off `useMicrosoftManagedNetwork` | Full redesign; no upgrade path per sample; subnet CIDR is a hardcoded range |

Note on the egress allowlist: `rai-policies.tf` today allows only the policy API host; the model
host is not listed, yet the call reached the account, consistent with the blog's statement that
required platform connectivity is allowed separately. Not changed. No option needs IPs or CIDRs.

Recommendation: **A**, written as reviewable azapi + role assignment, planned (never applied)
by Parker once approved. Brian must approve: (1) the new outbound rule resource, (2) the
Approver role (and whether Contributor-at-RG is acceptable) for the account identity,
(3) possible managed-network cost. Confirmation is only that the model call then returns 200.
Nothing applied at the time of the proposal.

**OBSERVED after apply (2026-10-09, `task cloud:up`, plan was 2 add / 0 change / 0 destroy;
`infra/cloud/managed-network.tf`):**
- Outbound rule `foundry-account-pe` (`PrivateEndpoint` → this account, `account`): `status: Active`.
- Account private endpoint connections: ours (`…-foundry-pe`) Approved; new
  `foundry-account-pe.74a8ffb3-…` **Approved**, description "Auto-approved by Azure AI managed
  network for workspace: humble-phoenix-46689-foundry@AML".
- Role: `Azure AI Enterprise Network Connection Approver` assigned to the account identity at
  **account scope** only. The sample's RG-scope Contributor was NOT granted and auto-approval
  worked without it, so on this evidence it is not required for the account-scope case.
- RAI policies and agents untouched. NOT yet observed: the model call succeeding. That
  (HTTP 200 from the account on re-invoke) is the only confirmation; the rule being Active
  proves the control plane accepted it, not that the data path works.

### B9h. Demo UI identity (issue #1) — APPLIED 2026-10-09

`infra/cloud/demo-ui-identity.tf`; plan and apply were 3 add / 0 change / 0 destroy.
- Role verified read-only first: **Foundry Agent Consumer** (`eed3b665-ab3a-47b6-8f48-c9382fb1dad6`),
  actions none, dataActions exactly `Microsoft.CognitiveServices/accounts/AIServices/endpoints/interact/action`,
  no notDataActions. Narrower than Cognitive Services User, which the workflow identity holds.
- Observed: user-assigned identity `humble-phoenix-46689-demo-ui-identity`, client id output
  `demo_ui_identity_client_id` (`ec040ec9-ba15-4ccf-a55d-db0651bfd782`); federated credential subject
  `system:serviceaccount:agent-boundary-lab:demo-ui`, audience `api://AzureADTokenExchange`; the only
  role assignment is Foundry Agent Consumer at PROJECT scope.
- NOT observed: an invocation actually succeeding with this identity. Whether `interact/action`
  alone covers every UI call (e.g. a version read-back) is unverified. Agents and RAI policies untouched.

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

### E2a. Model call 404: dated api-version on the Responses route

**Access date 2026-10-09.**

**OBSERVED** (Lambert, AppExceptions, run `invoke-2b418248a499`): the agent dies at its first model
call with `litellm.NotFoundError {"error":{"code":"404","message":"Resource not found"}}` from
`POST https://humble-phoenix-46689-foundry.cognitiveservices.azure.com/openai/responses?api-version=2024-10-21`.
Deployment `gpt-5.4-mini` (version 2026-03-17) exists and is Succeeded, so the deployment is not the
missing resource.

**Read from installed litellm 1.104.0** (`.venv/.../litellm/`):

* `main.py:1060` `responses_api_bridge_check` sets `mode="responses"` for an `azure/` GPT-5.4+ model
  when function tools are present and reasoning is not `"none"` (`chat_rejects_function_tools`, ~`:1140-1170`;
  `OpenAIGPT5Config.is_model_gpt_5_4_plus_model`). Our agent always has two function tools, so every call
  is bridged to `/openai/responses`. The model-cost map also lists `/v1/responses` for it.
* `llms/azure/common_utils.py:781-831` `_get_base_azure_url`: a supplied `api_version` is used verbatim
  (`:806`); only `"preview"`, `"latest"`, `"v1"` (`_is_azure_v1_api_version`, `:859`) rewrite the path to
  `/openai/v1/...`. Reproduced offline: `2024-10-21` -> `.../openai/responses?api-version=2024-10-21`
  (byte-identical to the failing URL); `v1` -> `.../openai/v1/responses?api-version=v1`; litellm's own
  Responses default is `"preview"` (`constants.py:9`).

**Primary docs** (Microsoft Learn, accessed 2026-10-09):
`https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle` — changelog lists the
Responses API as introduced in `2025-03-01-preview`, so `2024-10-21` predates it; the v1 API
(`/openai/v1/`) needs no dated `api-version`, and the page states v1 is required for latest features.
`https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses` — lists `gpt-5.4-mini`
(2026-03-17) as Responses-supported and shows `base_url=.../openai/v1/`.

**Conclusion, hypothesis-grade:** the hypothesis fits all evidence (URL reproduced, route and API
history), but the service's 404 does not name the cause and no live call has confirmed it.

**PROPOSED, UNVERIFIED until a live model call succeeds:** `DEMO_AZURE_OPENAI_API_VERSION` default
`2024-10-21` -> `v1` (settings only, no model-string change). Caveats: litellm still appends
`?api-version=v1` to the v1 path (no primary source says the service tolerates it; the Foundry agent
endpoint accepted `api-version=v1`, B9b); and the `azure_ad_token_provider` path on the Responses
route is not exercised by any test. Fallback if it 404s again: `preview`, litellm's own default.

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

#### B5a — A2A spike plan (PROPOSED, UNVERIFIED; nothing has been run)

Accessed **2026-10-09**. Sources: the Learn page above (`ms.date: 2026-09-11`, re-read in
full), and the installed `azure-ai-projects 2.8.0` source under
`.../site-packages/azure/ai/projects/` (the deploy-venv copy; `models/_models.py:420`
`A2AProtocolConfiguration`, `:633` `AgentCard`, `:671` `AgentCardSkill`, `:1128`
`AgentEndpointConfig`, `:16592` `ProtocolConfiguration`; `operations/_operations.py:6144`
`AgentsOperations.update_details`).

| Question | Answer | Status |
| --- | --- | --- |
| Mechanism | One `PATCH /agents/{name}?api-version=v1` (`application/merge-patch+json`) with `agent_card{version,description,skills[]}` and `agent_endpoint.protocol_configuration{responses:{},a2a:{}}`. SDK: `project.agents.update_details(agent_name=, agent_endpoint=AgentEndpointConfig(protocol_configuration=ProtocolConfiguration(responses=ResponsesProtocolConfiguration(), a2a=A2AProtocolConfiguration())), agent_card=AgentCard(...))` | **Documented** (prompt agents); the SDK surface is **verified present** in source |
| Target | The AGENT (`/agents/{name}`), not an agent VERSION. Re-PATCH is a merge-patch | Read from `update_details` source |
| Does it work for a hosted container agent? | The page says "Incoming A2A requires the responses protocol", names only prompt agents, and lists "a deployed prompt agent" as the prerequisite | **UNKNOWN** |
| Must `protocol_versions` on the hosted definition also list `a2a`? | `AgentEndpointProtocol` and `ProtocolVersionRecord.protocol` accept `"a2a"` (`_enums.py:135`), and `A2AProtocolVersion` has only `1.0` (`_enums.py:60`). Nothing says a container definition needs it | **UNKNOWN**. Not changed: adding it would create a new version and change the digest-pinned experiment |
| Must the container serve anything for A2A? | Not documented. Our container serves only the Responses protocol; the platform fronts A2A | **UNKNOWN** |
| Reference repo | `briandenicola/banking-agent-foundry-orchestrator` `src/agents/deployer/deploy.py:171` registers `invocations` `2.0.0` only; no A2A anywhere in it | Nothing to crib |
| A2A client SDK | `a2a-sdk` is NOT installed in any local venv, so its method names are not verified here. The spike uses the exact calls from the Learn page (`A2ACardResolver`, `ClientConfig`, `create_client`, `SendMessageRequest`, `new_text_message`) behind a lazy import | **UNVERIFIED** |
| JSON-RPC method name | Not hand-written. The `message/send` wording in the task is the v0.3 name; v1.0 names are carried by the SDK. We do not guess | **UNKNOWN** |
| Version pin | `A2A-Version: 1.0` header AND the resolved `agentCard/v1.0` card, which agree (differing values return 400 `version-ambiguous`) | Documented |

Spike code: `src/containment_demo/a2a_spike.py` (tests: `tests/unit/test_a2a_spike.py`). It is
**read-only by default**; `--enable` PATCHes one agent and `--send` sends one message. Its
verdict is always `inconclusive-a2a-unverified`. A failure is attributed to OUR call
(transport, 401/403) or to the PLATFORM; only a platform 400/404/405/415/501 on the enable or
card step is recorded as an `unsupported-signal`, which is a signal and not a conclusion.

The Foundry data plane is private, so this must run inside the VNet, with an identity holding
Foundry Agent Consumer to read the card and send, and a role that may PATCH an agent for
`--enable`. The demo UI identity has only Agent Consumer.

Recorded results: none yet.

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
10. Whether `deploy_timeout_seconds = 900` (deploy.py line 162) is long enough for Foundry
    hosted-agent provisioning (B9b). A version was still `creating` after ~10 minutes. If
    it proves too short the fix is a longer timeout — never a looser success condition,
    and never treating a timeout as a pass.

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
| Agent-version status vocabulary (B9b) | **Settled** — creating / active / failed / deleting / deleted; `deploy.py` already matches | SDK `AgentVersionStatus` enum, 2.4.0, 2026-10-08. Not yet observed on the wire. |

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
