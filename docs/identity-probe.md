# Issue #4: delegated Foundry authentication probe

**2026-10-16: code and offline checks only. Identity provisioning is blocked.**
No new Entra identities, consent, RBAC, token acquisitions, Kubernetes workloads,
or hosted invocations have been performed for this work. This is the first part
of [I0](PLAN.md#i0--compatibility-and-identity-contract-first-gate), not an identity rollout.
Existing hosted agents, policies, images and both business tools are unchanged.

## Current blocker

Microsoft's `msgraph` Terraform provider **0.5.0** constructs an instance URL by
appending `/{id}` to the creation collection. For a blueprint this produces:

```text
Creation:               applications/microsoft.graph.agentIdentityBlueprint
Provider instance URL:  applications/microsoft.graph.agentIdentityBlueprint/{id}
Documented instance:    applications/{id}/microsoft.graph.agentIdentityBlueprint
```

The provider has no configurable separate instance URL. The undocumented alternate
path has **not** been tested against Graph; this is not a finding that Agent ID itself
is unavailable. A failed post-create refresh could leave an identity outside state.
`infra/identity-probe/compatibility.tf` therefore rejects plans before apply. An
offline Terraform test with mocked providers proves that rejection.

**Do not remove the guard to try a deployment.** Establish a supported Terraform
lifecycle covering creation, refresh, update, import and destruction, then update
the implementation and its tests. No `local-exec`, manual state rewriting, or
untracked Graph POST is used as a substitute.

The exact Foundry resource service principal, delegated scope, token audience and
Agent ID consent support also remain unverified. Setup requires explicit verified
inputs and checks the resource's published enabled scopes; it guesses no Foundry
permission. If the required delegated flow is unavailable, I0 remains blocked.

## What the probe checks

The proposed finite AKS Job mounts the current probe source into the **existing
digest-pinned publisher image**, using `/opt/deploy-venv/bin/python`. A private,
digest-pinned Entra Agent ID sidecar listens only on `127.0.0.1:5000`; no Service,
Ingress or public port is created. Native sidecar lifecycle requires Kubernetes
**1.33+**. Sidecar startup observation and HTTP requests are bounded.

The probe verifies incoming and exchanged JWT signatures against the fixed tenant's
Microsoft signing keys, plus issuer, audience, expiry, tenant, user, delegated scope
and OAuth client. It calls authenticated `/Validate`, then
`/AuthorizationHeader/Foundry?AgentIdentity=...` with that incoming bearer.
`RequestAppToken=false`; there is no workload-token or impersonation-header fallback.
The actual named-agent Responses endpoint receives the exchanged token as its bearer.

| Case | Required observation |
| --- | --- |
| Allowed test user | Validated delegated bearer, successful completed Foundry response and response ID |
| Denied test user | Same delegated flow but no effective Foundry invoke permission; HTTP 403 |
| Invalid token | Foundry rejects a deliberately invalid bearer with 401/403 |
| Wrong audience | Foundry rejects the genuine blueprint-audience user token with 401/403 |

Negative-case acceptance fails the gate. Missing consent, startup failures, malformed
exchanges, DNS/TLS/timeout/connection failures and absent positive control are
**inconclusive**, not passes. No individual rejection is labeled a pass without the
positive control. Connection classifications reuse the existing invocation helper.
Exit codes: **0 pass, 1 fail, 2 inconclusive**.

Evidence contains test aliases, status codes, safe diagnostic codes, response IDs,
timestamps and installed package versions, not raw tokens, user IDs, full claims,
prompt/response content, payloads or authorization headers. Sidecar validation bodies
are discarded. `identity:status` reads only the probe container, never sidecar logs.
Local mocked checks are functional tests, not hosted or containment evidence.
The probe records its own image and sidecar digests; the actual hosted-agent digest
and protocol version are explicitly unverified, not inferred from its caller image.
Verify and record those separately when approving a hosted run.
Even a hosted pass reports `i0_complete: false` and `containment: not_evaluated`:
downstream policy-token delivery/provenance and the rest of I0 are separate work.

## Dedicated setup design and prerequisites

The isolated Terraform state is **not included in `cloud:up` or `deploy:all`**.
Its intended resources are a browser public client and service principal, an Agent ID
blueprint and mandatory blueprint principal, an Agent Identity, blueprint workload
federation, per-user incoming/OBO consent, and one project-scoped **Foundry Agent
Consumer** assignment to the allowed user. Names use `random_pet` plus `random_id`.
The blueprint defines its own incoming `access_as_user` scope; that is **not** a
claim that Foundry publishes a scope with this name.

Before any future reviewed setup, the owner must supply:

- An existing, dedicated certificate-authenticated Graph deployer with reviewed,
  admin-consented application permissions. Agent ID APIs reject the Azure CLI's
  `Directory.AccessAsUser.All` token; the Graph provider explicitly disables CLI auth.
  Relevant API permission families include `Application.ReadWrite.All`,
  `AgentIdentityBlueprint.Create`, `AgentIdentityBlueprint.ReadWrite.All`,
  `AgentIdentityBlueprintPrincipal.Create`, `AgentIdentity.Create.All`,
  `AgentIdentity.ReadWrite.All`, and `DelegatedPermissionGrant.ReadWrite.All`.
  Verify each operation's current least-privilege and cleanup requirements before consent;
  this module does not bootstrap or consent its own privileged deployer.
- Two distinct existing synthetic test users and a blueprint sponsor. Inventory
  inherited/group/subscription/project permissions: the denied user must genuinely
  lack invoke access, and an existing allowed-user assignment must not be duplicated.
  This module neither strips unrelated grants nor gives the intermediary agent RBAC.
- The verified Foundry resource SP **object ID**, enabled delegated scope value and
  expected `aud`, existing private project endpoint/ARM ID, and AKS OIDC issuer.
- The existing publisher image digest and a verified digest for the documented
  `mcr.microsoft.com/entra-sdk/auth-sidecar:1.0.0-azurelinux3.0-distroless` tag.
  No sidecar digest has been resolved or hosted here.

Copy `infra/identity-probe/terraform.tfvars.example` to a gitignored
`terraform.tfvars` only after resolving the blocker. Never commit actual user IDs,
certificates, tokens, Terraform state or private configuration.

## Owner commands

Available **now**, with no tenant or cluster access:

```bash
task identity:test
task identity:sdk-test  # prompts before downloading isolated SDK dependencies
terraform -chdir=infra/identity-probe validate
terraform -chdir=infra/identity-probe test
```

The real-SDK mocked request tests use `azure-ai-projects==2.8.0`,
`openai==3.31.0`, `httpx==0.28.1`, `PyJWT==2.15.1`, and `cryptography==50.0.2`.
The ordinary dev suite skips those optional SDK cases if projects SDK is absent;
`identity:sdk-test` runs them in isolation without changing the agent/model stack.
The provider lock file records AzureRM **4.81.0**, random **3.9.1** and msgraph
**0.5.0**. Schema validation is not proof of Graph API compatibility.

**Future owner-run sequence, blocked today; not an instruction to deploy:**

```bash
task identity:init
task identity:setup-plan
task identity:setup
task identity:login CASE=allowed
task identity:login CASE=denied
task identity:manifest
task identity:probe
task identity:status
task identity:down
task identity:setup-down
```

Setup/consent/RBAC and probe execution require separate owner approval. Login uses
the browser client's localhost callback (`http://localhost:8400`), validates the chosen
test persona before writing, and saves short-lived JWTs in owner-only gitignored files
without a persistent token cache. This localhost probe is not the future HTTPS UI.
The Job's read-only Secret is short-lived but remains a credential: run
`identity:down` after collecting results, even if the Job has expired.
Remove the two local JWT files after the experiment; Kubernetes TTL does not remove
the Secret or the local files. Then destroy the dedicated identity state.

Cluster operations validate configuration, expected context and namespace, server
version, and resource ownership before use. They cannot silently overwrite or delete
an unrelated resource with the same name. Secret apply is server-side, without a
client-side last-applied annotation containing a second token copy.

## Primary references

Accessed **2026-10-16**:

- [Sidecar endpoints and health](https://learn.microsoft.com/en-us/entra/msidweb/agent-id-sdk/endpoints).
- [Agent identity interactive pattern 4](https://learn.microsoft.com/en-us/entra/msidweb/agent-id-sdk/agent-identities).
- [Create blueprint](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprint-post?view=graph-rest-1.0)
  and [get blueprint: canonical typed instance path](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprint-get?view=graph-rest-1.0).
- [Create blueprint principal](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprintprincipal-post?view=graph-rest-1.0)
  and [create Agent Identity](https://learn.microsoft.com/en-us/graph/api/agentidentity-post?view=graph-rest-1.0).
- [Delegated grant resource](https://learn.microsoft.com/en-us/graph/api/resources/oauth2permissiongrant?view=graph-rest-1.0).
  The generic v1.0 resource reference does not document `expiryTime`; no such field
  is invented here. Agent ID-specific grant support still needs tenant validation.
- [msgraph 0.5.0 lifecycle implementation](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/internal/services/msgraph_resource.go)
  and [resource schema](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/docs/resources/resource.md).
