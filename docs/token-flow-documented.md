# Delegated identity and policy API authorization

Current contract, consolidated 2026-11-09. The owner confirmed the existing identity
demo was tested on 2026-11-06. That report supersedes the earlier "never deployed"
drafts; it does not establish Microsoft 365 channel token delivery.

## Baseline token path

```text
browser -> oauth2-proxy (Entra app A)
  -> harness: MSAL on-behalf-of exchange for policy API app B
  -> A2A facade: X-Delegated-Policy-Token
  -> Foundry Responses: x-client-policy-access-token
  -> hosted adapter: request-scoped ADK session state
  -> get_servicing_policy: Authorization bearer
  -> policy API: signature, tenant, audience, scope, client and user checks
```

`x-auth-request-access-token` carries the incoming app-A assertion to the harness.
The harness's `current_user_token` ContextVar carries the exchanged app-B token for
that turn. The hosted agent uses ADK session state, not the harness ContextVar.
The facade hop is plain in-cluster HTTP; do not claim end-to-end TLS for this path.
Caller `Authorization` to Foundry is not automatically forwarded to the container.

The external-processing tool never receives the policy API token. Its receiver is
unauthenticated so an API rejection cannot impersonate a network block.
No app-only token substitutes for the user's delegated authorization.

## Enforcement

`delegated_auth.py` validates RS256 signing keys, issuer, tenant, audience, expiry,
not-before time, user object ID, delegated scope and trusted OAuth client.
`AccessGuard` then checks the configured authorized-user set.
Partial identity configuration raises; it does not silently select legacy mode.
Only `/healthz` bypasses the policy API guard.

| API result | Meaning |
| --- | --- |
| 200 and verified user identifier | Authorized policy retrieval |
| 401 | Missing or invalid delegated token |
| 403 `user_not_authorized` | Verified user is not authorized |
| 403 `insufficient_scope` / `untrusted_oauth_client` | Verified token fails the API's permission/client contract |
| 503 | Signing keys unavailable or invalid |

Actor aliases are display labels, never authorization inputs.
The UI shows `allowed` only with 200 and the echoed verified identity.
`user_token_forwarded=false` or a bare 200 without identity evidence is "no evidence".
Policy-access and egress-containment verdicts stay separate.

## Evidence and privacy

The tool record carries `user_token_forwarded`; application telemetry carries
`demo.user_token_forwarded`, not the user's object ID.
Policy API receipt JSON identifies served policy retrieval. Rejections produce
`event=authorization_decision` with `determination=identity_only`.
Use `demo_run_id` to correlate; protected receipt paths may be redacted.
Do not print tokens, authorization headers, full claims or payloads.

See [KQL query 10](kql-queries.md#10-policy-api-identity-decisions-for-one-tool-run-id-issue-4)
and [telemetry map](telemetry-map.md).

## Operations

Use [workshop external access](workshop/07-external-access.md) and the
[rebuild runbook](rebuild-runbook.md) for the owner-run Task sequence.
`app:deploy-external` includes external identity setup; do not run it twice.
It updates `.env` and launches a fresh `cloud:up` process to load the new settings.
Review the full plan first: do not apply that aggregate path to overwrite externally
managed policy drift in an existing environment.

`identity:verify` is a separate delegated-Foundry compatibility probe with temporary
test-user tokens. `app:run-allowed` / `app:run-denied` are offline actor-context
regressions, not the OBO browser test. See
[the identity Task definitions](../tasks/Taskfile.identity.yml).

## Microsoft 365 channel

Microsoft 365 channel authorization is not this direct Responses-header contract.
A signed-in channel user does not automatically supply a policy API bearer.
The Copilot integration must validate downstream delegation without copying operator
tokens, trusting display names or weakening the API guard.

Primary reference, accessed 2026-10-15:
[Hosted-agent on-behalf-of flow](https://learn.microsoft.com/azure/foundry/agents/how-to/use-on-behalf-of-flow).
