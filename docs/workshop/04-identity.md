# Module 04: Identity

The tested baseline distinguishes signing in from authorization to retrieve policy.
The owner confirmed the identity/egress demo was tested on 2026-11-06.
This module covers that baseline, not Microsoft 365 channel integration.

## Objectives

- Explain Entra delegated versus application tokens.
- Trace the browser-to-policy API flow.
- Demonstrate authorized and unauthorized synthetic users without confusing their
  API result with network containment.

## Concepts

| Term | Meaning |
| --- | --- |
| Tenant | The Entra directory issuing the user's token |
| App registration | The OAuth client/API definition and its exposed scopes |
| Service principal | The tenant-local instance of an application |
| Managed/workload identity | Workload credentials without a stored application secret |
| Delegated token | Access granted to an application on behalf of a signed-in user |
| OBO | On-behalf-of exchange for a downstream API-specific token |
| Azure RBAC | Resource permissions, distinct from downstream API user authorization |

```text
browser -> oauth2-proxy -> harness OBO -> A2A facade
  -> private Foundry Responses -> hosted ADK -> policy API guard
```

The policy API verifies signature, tenant, audience, expiry, delegated scope, trusted
OAuth client and authorized-user list. An actor alias is only a display label.
The unauthenticated receiver never receives the policy API token.

The older identity SVG is omitted because it placed the guard at the facade.
The actual guard is at the policy API. See [the current token flow](../token-flow-documented.md).

## Walkthrough

All commands run from the repository root. The owner performs setup and sign-in.

1. Use [Module 07](07-external-access.md) to configure HTTPS and Entra login.
   `app:deploy-external` includes external identity setup; do not repeat it separately.
2. Open the configured harness URL as the authorized synthetic user. Ask for the
   servicing policy. The policy-access card needs HTTP 200 and a verified identity
   to show `allowed`.
3. Use a private browser session as the unauthorized synthetic user. The same
   tool should return 403 `user_not_authorized`, shown as `denied`.
4. Inspect the separate containment card. Neither identity outcome establishes
   whether Foundry denied outbound traffic.

For offline regression:

```bash
task identity:test
task identity:validate
```

Optional directory/delegated-Foundry compatibility probes have a separate lifecycle:
[identity-probe.md](../identity-probe.md). A successful directory setup is not a
hosted invocation or network-containment result.

Never paste tokens, authorization headers or full claims into chat or evidence.
Use synthetic user aliases in reports. `user_token_forwarded=false` means the tool
did not receive its downstream token; it is not an ACS or network denial.

## Code tour

| Source | Responsibility |
| --- | --- |
| `harness/obo.py` | MSAL exchange; explicit failure, no app-token fallback |
| `harness/chat.py` | Request-scoped token handling and separate identity/evidence cards |
| `a2a_facade/target.py` | Downstream token forwarding |
| `protocol_adapter.py` | Lowercase `x-client-*` headers into ADK session state |
| `delegated_auth.py` | Token validation and authorized-user checks |
| `services/policy_api/main.py` | Protected business routes; only health is unauthenticated |

Paths are relative to `src/containment_demo/` unless otherwise shown.
The facade hop is plain in-cluster HTTP; do not claim end-to-end TLS for it.

## Checkpoint

- Both synthetic users exercise the same tool and API.
- The alias never controls authorization.
- Policy API authorization and platform containment have separate verdicts.

**Next:** [Module 05: Agent and tools](05-agent-and-tools.md).
