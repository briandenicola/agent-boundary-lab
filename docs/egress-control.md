# How Foundry egress control works

Foundry evaluates outbound HTTP/HTTPS requests inside the hosted-agent sandbox.
The tool still runs; the platform decides whether its request may leave.
This is separate from ACS, which can stop a tool before it executes.

## The policy

Network rules live in the account's RAI policy resource:

```text
Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview
  properties.egressPolicy
    mode: Audit | Enforced
    defaultAction: Deny
    rules: exact-host allow rules
```

The policy takes effect when an agent version references its **full ARM ID** in
`definition.rai_config.rai_policy_name`.
[Terraform source](../infra/cloud/rai-policies.tf)

Two fields share the name `mode`; they control different things:

| Field | Controls |
| --- | --- |
| `properties.mode` | Content safety |
| `properties.egressPolicy.mode` | Network Audit/Enforced behavior |

## Audit versus Enforced

| Request | Audit | Enforced |
| --- | --- | --- |
| Matches Allow | Proceeds | Proceeds |
| Matches Deny or default Deny | Proceeds; would-deny recorded | Blocked; HTTP 403 returned |
| Matches Rewrite/Transform | Request is modified | Request is modified |

Audit is the positive comparison: it shows the receiver works when denial is
not enforced. The lab uses the same image, destinations, and allow rules in both
agents. Compare live content-safety settings as well; existing externally managed
settings may differ from Terraform's declarations.

## Rule matching

Rules match hostnames and optional path prefixes. The preview supports wildcards,
but not port or IP matching. The lab uses two distinct hostnames:

```json
{
  "name": "allow-policy-api",
  "ruleType": "Fqdn",
  "match": { "host": "policy-api.example.com" },
  "action": { "actionType": "Allow" }
}
```

The policy API is explicitly allowed; the receiver is omitted and falls through
to `defaultAction: Deny`. Evaluation failure is fail-closed.

The platform also has an implicit allowlist for required runtime connectivity.
Its complete domain list is not documented. Use the matched-rule evidence rather
than assuming every successful call came from an explicit rule.

## What is separate

| Mechanism | Controls |
| --- | --- |
| Private endpoint / public-access ACL | Inbound access to Foundry |
| Managed-network outbound rules | Runtime connectivity, separate from RAI policy |
| AKS network policy | AKS workloads, not the hosted-agent sandbox |
| Prompt or application check | Application behavior, not platform containment |

Both controlled API hosts are allowed by the managed network, so the RAI policy
is the network variable in this comparison. The policy does not follow work
delegated into another runtime.

## TLS and HTTP clients

The egress proxy terminates TLS and supplies a runtime CA bundle.
Clients must use that bundle without disabling verification.
The relevant settings include `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`,
`GRPC_DEFAULT_SSL_ROOTS_FILE_PATH`, and `NODE_EXTRA_CA_CERTS`.

Do not bake the rotating CA into an image. Keep timeouts bounded, redirects
disabled, and destinations fixed. A TLS trust error is a client failure,
not a containment result.

## Proving a block

A 403 can come from the destination itself. DNS failures, timeouts, and model
refusals also do not identify a platform decision.

Require all three:

1. The tool attempted the configured destination.
2. A matching `AppDependencies` row records `NetworkEgressDecision` and Deny.
3. The receiver has no matching receipt after the ingestion window, with a
   successful servicing receipt and no unattributed arrivals.

The run marker in `/policy/{run_id}` or `/ingest/{run_id}` joins platform URLs to
receipt JSON. Missing evidence is **inconclusive**.
[Telemetry fields](telemetry-map.md) · [Queries](kql-queries.md)

## Preview limits and references

This feature is preview, not a production assurance. The lab tests HTTP/HTTPS
destinations, not every protocol or possible escape path. Custom OTLP export of
platform decisions and independent third-host managed-firewall denial are unverified.

Primary references, accessed **2026-10-08**; runtime observations are recorded
separately in [compatibility](compatibility.md):

- [Hosted-agent guardrails](https://learn.microsoft.com/azure/foundry/agents/how-to/add-hosted-agent-guardrails)
- [RAI policy schema](https://learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2026-05-15-preview/accounts/raipolicies)
- [Managed network](https://learn.microsoft.com/azure/foundry/how-to/managed-virtual-network)
- [Hosted-agent telemetry](https://learn.microsoft.com/azure/foundry/agents/how-to/configure-hosted-agent-telemetry)
