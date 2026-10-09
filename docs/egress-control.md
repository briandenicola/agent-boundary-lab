# Restricting outbound tool calls in Microsoft Foundry

**Audience:** engineers and architects who need to reason about, configure, or audit what a
hosted agent is able to reach on the network.

**Access date for every primary reference: 2026-10-08.** Everything below is either read
from a primary source, read from installed SDK/CLI source, or read back from live Azure
resources in this lab. Anything not established that way is marked **NOT VERIFIED** or
**NOT FOUND** and must not be presented as fact.

**Preview, no SLA.** Network egress control is configured through the
`2026-05-15-preview` API version. Microsoft states it is not intended for production. Treat
field names and behaviour as subject to change and re-verify before relying on any of it.

---

## 1. The question this answers

An agent's tools make outbound HTTP calls. Three mechanisms are routinely — and
incorrectly — offered as the answer to "what stops the agent calling somewhere it
shouldn't":

| Mechanism | What it actually governs | Does it contain outbound tool calls? |
| --- | --- | --- |
| Private endpoint / `publicNetworkAccess: Disabled` | who can reach the account **inbound** | **No** |
| Application-side allowlist in tool code | what the code *chooses* to do | **No** — it is the thing being bypassed |
| Prompt instructions / model refusal | what the model *tends* to do | **No** — non-deterministic, not a control |

The only platform mechanism that governs outbound traffic from a Foundry hosted agent is
the **network egress policy**, carried as a nested property on an RAI policy resource and
bound to an individual agent version. This document describes how that works, what it does
not cover, and how to tell a real platform denial from something that merely looks like
one.

---

## 2. Where the control lives in the resource graph

Egress control is **not its own resource type**. There is no `egressPolicies` resource, no
NSG involvement, no user-managed firewall. It is a property block on the existing
Responsible AI policy resource:

```
Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview
  └── properties
        ├── mode              ← CONTENT SAFETY mode. Not networking.
        ├── contentFilters    ← content safety. Not networking.
        └── egressPolicy      ← NETWORK egress control lives here
              ├── mode          Audit | Enforced
              ├── defaultAction Allow | Deny
              └── rules[]       up to 480
```

Two consequences follow immediately, and both have bitten this lab:

**It is scoped to the account, applied per agent version.** The policy resource is a child
of the `Microsoft.CognitiveServices/accounts` resource. It is inert until some agent
version names it. Creating the policy changes nothing by itself.

**It is not in the Terraform AzureRM provider.** Because the egress block exists only on a
preview API version, it has to be written with `azapi_resource` and
`schema_validation_enabled = false`. See `infra/cloud/rai-policies.tf`.

### 2.1 The two `mode` properties

This is the single most dangerous ambiguity in the schema. There are two unrelated
properties called `mode` at different depths:

| Property | Domain | Values |
| --- | --- | --- |
| `properties.mode` | content safety filtering | `Default`, `Deferred`, `Blocking`, `Asynchronous_filter` |
| `properties.egressPolicy.mode` | **network enforcement** | `Audit`, `Enforced` |

If you are running an A/B experiment where the egress mode is the independent variable,
changing the wrong `mode` produces a result that looks valid and means nothing. In this
lab `properties.mode` is pinned to `Blocking` in *both* policies specifically so it cannot
drift and cannot be mistaken for the variable under test.

---

## 3. The enforcement point

Microsoft's description places enforcement **"inside the agent's sandbox before traffic
leaves the runtime."** The practical shape of that is an egress proxy in the agent's
network path:

```
tool code (httpx / requests)
    │  HTTPS request to https://host/path
    ▼
egress proxy in the agent sandbox   ← policy evaluated HERE
    │  ├─ match rules by host (and optional path)
    │  ├─ no match → defaultAction
    │  └─ cannot evaluate → DENY (fail-closed)
    ▼
internet / destination
```

Three properties of this placement matter:

**It is outside the application's control.** The tool code cannot see the policy, cannot
read the ruleset, and cannot opt out. That is precisely what makes it a platform control
rather than an application convention. A code-level allowlist proves only that the code
behaved; this proves the code *could not* misbehave.

**It terminates TLS.** The proxy MITMs HTTPS — it must, in order to see the request host
and path for a path-scoped rule. See §7 for what that forces on client code.

**It is per-sandbox, not per-logical-agent.** Containment attaches to the runtime the code
executes in. If an agent delegates work to another agent in a different runtime, the
egress policy does **not** follow it across that boundary. In this lab the on-cluster
harness that calls into Foundry over A2A is governed by AKS policy, not by this egress
policy, and no claim about Foundry containment extends to it.

---

## 4. Evaluation semantics

### 4.1 Order of evaluation

1. Evaluate the request against `rules[]`, matching on host and optional path.
2. On a match, apply that rule's `action.actionType`.
3. On no match, apply `defaultAction`.
4. If the policy cannot be evaluated at all, **deny**.

Steps 3 and 4 are the part that makes this a security control rather than a routing hint.
`defaultAction` **defaults to `Deny`** when omitted, and evaluation failure is fail-closed.

Nevertheless, state `defaultAction = "Deny"` explicitly. Relying on an unstated default
for a fail-closed control means a future API-version change can silently convert your
default-deny posture into default-allow, and nothing in your configuration will look
different.

### 4.2 Match scope — and its limits

`match.host` — FQDN. Supports DNS wildcard syntax; a leading `*.` matches any subdomain.

`match.path` — URI **prefix** matching, with `*` as a single-segment wildcard.

**There is no port matching and no IP matching in the preview.** Service tags and IP ranges
are described as planned, not present. The operational consequence: you cannot express an
allowlist more narrowly than a hostname plus path prefix, and you cannot allow a host on
443 while denying it on some other port.

This is why a containment experiment should use **two distinct hostnames** rather than two
paths on one host. Host-level separation is the coarsest unit the control actually
enforces, so testing at that granularity tests the real boundary.

### 4.3 Rule shape

```json
{
  "name": "allow-policy-api",
  "ruleType": "Fqdn",
  "match": { "host": "policy-api.example.com" },
  "action": { "actionType": "Allow" }
}
```

`action.actionType` enum: `Allow`, `Deny`, `Rewrite`, `Transform`. Maximum **480 rules**
per policy.

`Rewrite` and `Transform` are not mere allow/deny — they mutate the request. Note from §8
that they apply in **both** Audit and Enforced mode, which means an "audit-only" policy is
not necessarily non-intrusive.

### 4.4 The implicit allowlist — the biggest caveat in this document

The runtime "automatically allow lists foundational domains it needs to function," and a
`Deny` default action does not block that required platform connectivity. So you do not
need rules for the model endpoint or platform telemetry.

**NOT FOUND: the itemized list of those domains.**

For operations, this is convenient. For anyone trying to *prove* a causal claim, it is a
serious problem: if an allowed call succeeds, you cannot tell from the outcome alone
whether it succeeded because of your explicit rule or because the host fell inside an
undocumented implicit allow. Do not assume package mirrors, your own ACR, or a custom OTLP
collector are covered, and do not assume they are not. The only way to resolve it is
empirically — and the matched-rule field in the egress decision record (§9) is what
resolves it, which is another reason that evidence is not optional.

---

## 5. Binding a policy to an agent

A policy only takes effect when an agent version references it, through the hosted-agent
definition:

```jsonc
{
  "definition": {
    "kind": "hosted",
    "container_protocol_versions": [{ "protocol": "RESPONSES", "version": "v1" }],
```

> **`v1` was ACCEPTED at create time but REJECTED at invoke time** (HTTP 400, 2026-10-09:
> `Unsupported responses protocol version '' for agent 'containment-demo-audit:3'. Please use version '2.0.0'.`).
> The deployer now registers `2.0.0`, which is **UNVERIFIED** until a live invoke succeeds.
> See compatibility.md B9d.

```json
    "cpu": 1,
    "memory": "2Gi",
    "image": "<registry>/<repo>@sha256:<digest>",
    "environment_variables": { },
    "rai_config": {
      "rai_policy_name": "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/raiPolicies/<policy>"
    }
  }
}
```

**`rai_policy_name` takes the full ARM resource ID, not a bare name**, despite what the
field name suggests.

Equivalent spellings of the same field:

| Surface | Spelling |
| --- | --- |
| Data-plane REST / deprecated `agent.yaml` | `rai_config.rai_policy_name` (snake_case) |
| Python SDK | `RaiConfig(rai_policy_name=...)` passed to `HostedAgentDefinition` |
| `azure.yaml` (azd) | `raiPolicyName`, under a `policies` list with `type: rai_policy` |

### 5.1 Hosted agents are a data-plane resource

Verified 2026-10-08 by reading the installed azure-cli source, not from documentation.
`az provider show -n Microsoft.CognitiveServices` lists no `accounts/projects/agents` — the
agent is **not an ARM resource**. It lives on the project data plane:

| Item | Verified value | Source |
| --- | --- | --- |
| Base URL | `https://{account}.services.ai.azure.com/api/projects/{project}` | `_client_factory.py:71` |
| Create version | `POST /agents/{name}/versions` | `custom.py:~2204` |
| API version | `2025-11-15-preview` | `custom.py:495` |
| Start container | `POST /agents/{n}/versions/{v}/containers/default:start` | `_invoke_agent_container_operation` |
| Token scope | `https://ai.azure.com/.default` | `azure/ai/projects/_configuration.py:51` |

Two operational consequences:

**`az cognitiveservices agent` cannot attach a policy.** No subcommand in the group
(`create`, `update`, `show`, `status`) exposes a policy argument, and
`_create_agent_definition` never emits `rai_config`. If the attached policy is the variable
you care about, the CLI cannot deploy your agent. It has to be a direct data-plane POST.

**With `publicNetworkAccess: Disabled`, the data plane is unreachable from outside the
VNet** — `(403) Public access is disabled. Please configure private endpoint.` Agent
deployment must originate inside the VNet. This is an inbound concern, entirely independent
of egress enforcement, but it constrains how you deploy.

**NOT VERIFIED:** whether `definition.image` accepts a digest reference. The CLI's
`_validate_image_tag` (`custom.py:510`) requires a colon and treats everything after the
last colon as "the tag, which becomes the agent version" — a digest passes that check but
would name the version after raw hex. If you are comparing two agents and need them to run
identical code, digest pinning is the control that guarantees it, so prove this before
trusting any comparison.

---

## 6. Denial behaviour, and how not to misread it

**The egress proxy returns HTTP 403 to the agent's network client.**

Microsoft's own documentation raises the objection before anyone else can: *"A destination
can also return 403, and a DNS or TLS failure is not a successful denial."*

That single sentence is the crux of honest reporting here. From inside the tool, these are
not distinguishable by status code alone:

| Observed at the client | Could mean |
| --- | --- |
| HTTP 403 | platform denied it — **or** the destination denied it |
| DNS failure | no resolution — not a policy decision |
| TLS failure | trust/handshake problem — not a policy decision, but see §7 |
| Timeout | network or destination problem — not a policy decision |
| Model declines to call the tool | nothing was ever attempted; proves nothing about the network |

**Therefore a bare 403 at the client is not proof of containment.** A defensible pass
condition needs three independent signals agreeing:

1. the client-side failure, classified by *kind* (HTTP vs TLS vs DNS vs timeout — never
   collapsed into "it failed"), **and**
2. a matching platform egress decision record naming the destination and the decision,
   **and**
3. the absence of a receipt at the destination itself.

Missing evidence is **inconclusive**, never a pass. A denial you cannot attribute is
indistinguishable from an outage.

**NOT FOUND:** the 403 response body/header schema, and whether DNS still resolves for a
blocked hostname.

---

## 7. TLS interception — what it forces on client code

The proxy MITMs HTTPS. The runtime injects the proxy's CA into the sandbox trust bundle and
advertises its path through standard environment variables:

| Env var | Consumer |
| --- | --- |
| `SSL_CERT_FILE` | OpenSSL-style clients |
| `REQUESTS_CA_BUNDLE` | Python `requests` |
| `GRPC_DEFAULT_SSL_ROOTS_FILE_PATH` | gRPC |
| `NODE_EXTRA_CA_CERTS` | Node.js |

The CA is **infrastructure-specific and rotates roughly every 30 days**. Microsoft's
guidance is to treat it as runtime configuration and **not to pin, copy, or persist it**.

Rules this imposes on tool code:

- **Never disable TLS verification.** `verify=False` converts a trust problem into a silent
  success and destroys the evidence value of every result that follows.
- **Read the CA path from the environment at call time.** Never hardcode it; it rotates.
- **Know your HTTP client's behaviour.** `requests` honours `REQUESTS_CA_BUNDLE`
  automatically. `httpx` may not — if you use it, wire the bundle explicitly.
- **Set explicit bounded timeouts and disable redirects.** A redirect can move a request to
  a host you did not evaluate; an unbounded timeout turns a denial into a hang.
- **Never configure a fallback destination.** A silent failover makes the result
  unattributable.

A TLS failure caused by a missing or stale CA bundle is a **client misconfiguration**, not
a containment result. Classify it separately or you will report an infrastructure bug as a
security success.

---

## 8. Audit versus Enforced

`egressPolicy.mode` changes **only how `Deny` decisions behave**:

| | `Audit` | `Enforced` |
| --- | --- | --- |
| Request that matches an `Allow` rule | proceeds | proceeds |
| Request that would be denied | **logged, then proceeds** | **blocked, 403 returned** |
| `Rewrite` / `Transform` rules | **applied** | applied |
| Egress decision records emitted | yes | yes |

Two things follow.

**`Audit` is not "policy off."** `Rewrite` and `Transform` still mutate traffic. An audit
rollout is lower-risk, not zero-risk.

**`Audit` is what makes an enforcement result meaningful.** If you only ever run under
`Enforced`, a failed call is ambiguous: perhaps the policy blocked it, or perhaps the
destination was never reachable in the first place. An Audit baseline establishes that the
call genuinely completes when nothing stops it. Without that baseline, a denial under
`Enforced` proves far less than it appears to.

This is also why `mode` must be the *only* difference between the two policies. If the
allow rules, content filters, base policy, or image differ at all, the outcome is no longer
attributable to enforcement. In this lab both policies share one `local.egress_allow_rules`
and one `local.content_filters` so they are identical by construction rather than by
review.

Operational guidance from Microsoft, which matches the inconclusive-not-pass rule above:
*"Do not treat a missing event as proof that a call was allowed."*

---

## 9. Evidence: where egress decisions surface

Platform decisions land in the project's **Application Insights**, in the `traces` table,
identified by a literal message string:

```kusto
traces
| where timestamp > ago(1h)
| where message == "Network egress decision"
```

Each event is documented to include the destination host, matched rule, decision, and
enforcement mode. **The sub-field names are NOT documented.** Do not assume
`customDimensions` key names until you have observed real rows.

The Foundry portal shows the same data as a "Network egress decision" span in the
**Trajectories** trace view, with UI labels Decision, Reason, Matched rule, Rule source,
Enforcement, Destination, Default action. Those are **UI labels and are not confirmed to be
Log Analytics column names.**

**NOT FOUND:** any `Microsoft.CognitiveServices` diagnostic-settings resource-log category
for egress decisions separate from this Application Insights mechanism. Enable
project-linked Application Insights; do not assume a diagnostic setting will do.

### 9.1 Correlation — NOT FOUND

There is **no documented correlation key** joining an egress decision to the application
trace of the tool call that caused it. The portal nests the span in the same invocation
timeline, implying association by construction, and App Insights rows normally carry
`operation_Id` / `operation_ParentId` — but that is generic App Insights behaviour, not a
documented Foundry guarantee.

If you need defensible correlation, carry your own key (this lab uses `demo_run_id`)
through the tool call and into the destination's receipt log. It is the only correlation
under your control.

### 9.2 OTLP export probably does not carry this

The hosted-agent telemetry documentation scopes telemetry to "the protocol runtime … and
your agent code" and never mentions egress, RAI, or network decisions. It is **undocumented
and unconfirmed** whether egress evidence reaches a custom `OTEL_EXPORTER_OTLP_ENDPOINT` at
all. Do not claim an OTLP pipeline carries platform decisions.

---

## 10. What this does *not* control

**Inbound.** `publicNetworkAccess`, `networkAcls`, and private endpoints govern who reaches
the account. They place **no restriction whatsoever** on what the agent reaches outbound. An
agent behind a private endpoint can still call any host on the internet. If a diagram or
report presents a private endpoint as outbound containment, it is wrong regardless of how
private the rest of the environment looks.

**Anything outside the sandbox.** A caller that invokes the agent over A2A is governed by
its own environment's controls. Containment attaches to the runtime the code executes in,
never to the logical agent, and never follows a tool call back across a protocol boundary.

**Interaction with a managed VNet — undocumented.** Both features are independently
documented as applicable to hosted agents, but the egress-control documentation never
mentions VNets, `networkInjections`, `publicNetworkAccess`, or isolation modes. **No source
states the two are compatible, incompatible, or layered.** With isolation mode
`AllowInternetOutbound` it is unresolved whether outbound traffic is governed by the egress
policy, by managed-VNet outbound rules, or by both; and whether managed-VNet FQDN rules
(which force a managed Azure Firewall, ports 80/443 only) stack with or conflict with the
egress allowlist. This is a confirmed documentation gap, not a failed search — tracked as
Blocker 1 in `compatibility.md`.

Until that is resolved empirically, an observed denial in an environment with both features
active **cannot be attributed to the egress policy specifically**. It can only be reported
as "the platform denied it."

---

## 11. Reference configuration

Terraform, using `azapi_resource` because the egress block exists only on the preview API
version. Abridged from `infra/cloud/rai-policies.tf`:

```hcl
locals {
  # Shared by both policies so they cannot drift apart. If the allow rule differed between
  # Audit and Enforced, a difference in outcome would no longer be attributable to the mode.
  egress_allow_rules = [
    {
      name     = "allow-policy-api"
      ruleType = "Fqdn"
      match    = { host = local.policy_api_host }
      action   = { actionType = "Allow" }
    }
  ]
}

resource "azapi_resource" "rai_policy_enforced" {
  type                      = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                      = "egress-enforced"
  parent_id                 = azapi_resource.foundry.id
  schema_validation_enabled = false
  response_export_values    = ["*"]

  body = {
    properties = {
      basePolicyName = var.rai_base_policy_name   # omitting this fails: "invalid base policy"
      type           = "UserManaged"
      mode           = "Blocking"                 # CONTENT SAFETY. Held constant.
      contentFilters = local.content_filters      # required; not inherited from the base policy
      egressPolicy = {
        mode          = "Enforced"                # NETWORK. The variable under test.
        defaultAction = "Deny"
        rules         = local.egress_allow_rules
      }
    }
  }
}
```

Non-obvious requirements, each discovered by a failed apply rather than from documentation:

- `basePolicyName` is **required**. Omitting it fails with "Resource has invalid base
  policy".
- `contentFilters` is **required** and is **not inherited** from the base policy. Omitting
  it fails with "Content filters cannot be null". Copy the base policy's own filters
  verbatim so content filtering cannot become an accidental second variable.
- `type = "UserManaged"` is required for a custom policy.
- `schema_validation_enabled = false` is needed because the provider's schema does not know
  the preview shape.

### 11.1 Reading the live state back

Control-plane acceptance is not data-plane enforcement, but you should at minimum confirm
ARM stored what you sent — preview APIs do silently drop unknown properties:

```bash
az rest --method get \
  --url "https://management.azure.com${ACCOUNT_ID}/raiPolicies?api-version=2026-05-15-preview" \
  --query "value[?properties.type=='UserManaged'].{name:name, egress:properties.egressPolicy}" \
  -o json
```

---

## 12. Current state in this lab

Read back from Azure on **2026-10-08**, subscription `ccfc5dda-…`, region canadacentral:

| | `egress-audit` | `egress-enforced` |
| --- | --- | --- |
| `egressPolicy.defaultAction` | `Deny` | `Deny` |
| `egressPolicy.mode` | **`Audit`** | **`Enforced`** |
| `rules` | 1 × `Fqdn` allow | 1 × `Fqdn` allow (identical) |
| `properties.mode` (content safety) | `Blocking` | `Blocking` |
| `basePolicyName` | `Microsoft.DefaultV2` | `Microsoft.DefaultV2` |

The single allow rule names the deployed policy-api host. The test-receiver host is
**deliberately absent**, so it falls through to `defaultAction: Deny`. No application code
anywhere in this repository knows which of the two hosts is special; both tools are
registered unconditionally in every mode.

Also in effect on the account: `networkInjections` with `scenario: agent` and
`useMicrosoftManagedNetwork: true`, and `publicNetworkAccess: Disabled`.

**Nothing is enforced today.** Both policies exist and are correct, and both are attached
to nothing, because no agent version has been created yet. A policy with no agent
referencing it is inert. Enforcement begins at the moment an agent version names it in
`rai_config.rai_policy_name` — not before.

---

## 13. Open questions

| # | Question | Status |
| --- | --- | --- |
| 1 | Does `definition.image` accept a digest reference? | NOT VERIFIED — blocks trustworthy A/B comparison |
| 2 | Which layer enforces when managed VNet and egress policy both apply? | NOT FOUND — Blocker 1 |
| 3 | What are the implicit-allowlist domains? | NOT FOUND — Blocker 3; limits attribution of successes |
| 4 | What are the real egress-decision field names? | NOT DOCUMENTED — must observe live rows |
| 5 | Is there a documented correlation key to the application trace? | NOT FOUND — Blocker 4 |
| 6 | 403 response body/header schema; does DNS still resolve for a blocked host? | NOT FOUND |
| 7 | Any region list scoped to the egress preview? | NOT FOUND |

---

## 14. References

Primary sources, accessed **2026-10-08**:

- Add hosted-agent guardrails (egress controls): https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/add-hosted-agent-guardrails
- RAI policy ARM template reference, `2026-05-15-preview`: https://learn.microsoft.com/en-us/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies
- Egress controls announcement: https://devblogs.microsoft.com/foundry/egress-controls-hosted-agent/
- Configure hosted-agent telemetry: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/configure-hosted-agent-telemetry
- Managed virtual network: https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network
- "Your private endpoint does not cover agent egress": https://techcommunity.microsoft.com/blog/azurearchitectureblog/your-private-endpoint-does-not-cover-agent-egress-locking-down-azure-ai-foundry-/4547864

Source inspection (no Learn page documents these payloads):

- `azure/cli/command_modules/cognitiveservices/custom.py`, `_client_factory.py` — azure-cli,
  installed at `/opt/az/lib/python3.14/site-packages/`
- `azure/ai/projects/_configuration.py` — token scope

In this repository:

- `docs/compatibility.md` §B, §C, §D and the Blockers section — the verified-facts record
- `infra/cloud/rai-policies.tf` — the deployed configuration
- `docs/README.md` — why private endpoints are not egress containment
