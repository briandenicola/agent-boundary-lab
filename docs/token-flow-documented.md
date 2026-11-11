# How user authorization works

[Deploy in Azure](rebuild-runbook.md) | [Run the demo](demo-runbook.md) | [Telemetry](telemetry-map.md)

Signing in lets a user reach the demo. It does **not** automatically let them
read the servicing policy. The policy service checks their token and whether
they are on its allowed-user list.

There are two ways to reach that service.

## From the AKS browser demo

```text
User signs in with Entra
  -> Browser harness receives the user's sign-in token
  -> Harness exchanges it for a policy API token on the user's behalf
  -> Bridge forwards that token to the Foundry-hosted agent
  -> Policy tool sends it to the API
  -> API validates the token and checks the user
```

The harness uses MSAL's on-behalf-of exchange. The policy token belongs to that
user and that request; the agent's own model-access credential cannot replace it.

For code tracing, the token crosses the bridge as `X-Delegated-Policy-Token`,
then Foundry as `x-client-policy-access-token`. The hosted adapter puts it in
request-scoped ADK session state. The policy tool sends it as a bearer token.
The bridge hop uses in-cluster HTTP, so this path is not end-to-end TLS.

## From Microsoft 365 Copilot

```text
User opens ACS OAuth Servicing Demo
  -> Hosted agent calls the Foundry toolbox with trusted user/request context
  -> OAuth connection supplies the user's delegated token
  -> Protected MCP service validates it and checks the user
  -> Synthetic policy returns to Copilot
```

The toolbox caller authenticates with managed identity. The OAuth connection
handles downstream user authorization, including browser consent when needed.
**Consent and service access are separate:** consenting does not add a user to
the MCP service's allowed list.

The older **ACS Servicing Demo** entry does not use this OAuth connection.
It can show ACS blocking a send, but it does not support delegated policy lookup.

## What the policy service checks

The service validates the token's signature, issuer, tenant, audience, lifetime,
delegated scope, OAuth client, and user identity. It then checks the allowed-user
list. A typed alias is only a display label.

| Result | Meaning |
| --- | --- |
| **200 with verified identity** | The user is allowed to read the policy |
| **401** | The delegated token is missing or invalid |
| **403 `user_not_authorized`** | The user is authenticated but not allowed |
| **403 `insufficient_scope` / `untrusted_oauth_client`** | The token lacks the required permission or comes from an untrusted client |
| **503** | The service could not obtain valid signing keys |

Only the health endpoint bypasses authorization. The external-processing tool
never receives the policy token, and its test receiver has no authentication gate.

## What to show in the demo

Sign in as the allowed user and retrieve the policy. Repeat as the denied user;
the API should return `user_not_authorized`.

The browser UI requires HTTP 200 **and** verified identity before showing
`allowed`. Missing identity evidence is not success. These identity results say
nothing about whether the network allowed or blocked a destination.

Authorized Copilot lookup was observed on **2026-11-10**; the Copilot unauthorized-user
acceptance test remains deferred. See the [dated evidence](telemetry-map.md#isolated-copilot-acceptance).

Use the run marker to check [authorization events](kql-queries.md#10-policy-api-identity-decisions-for-one-tool-run-id-issue-4).
Never record tokens, authorization headers, full claims, or user identifiers in
demo reports.
