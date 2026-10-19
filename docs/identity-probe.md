# Issue #4: delegated Foundry authentication probe

**2026-10-19: owner-run directory lifecycle passed; full identity setup remains blocked.**
The owner completed isolated Graph sign-in and reported `directory_lifecycle: pass`
after creation, read/update verification and cleanup. No hosted identity invocation
has been reported. This does not establish Foundry delegation or containment.
This is the first part
of [I0](PLAN.md#i0--compatibility-and-identity-contract-first-gate), not an identity rollout.
Existing hosted agents, policies, images and both business tools are unchanged.

## Isolated interactive tenant check

For the owner-selected separate tenant, first run:

```bash
task identity:graph-init
task identity:tenant-check TENANT_ID=REPLACE-other-tenant-uuid
```

The first command prompts before installing **Microsoft.Graph.Authentication 2.36.1**
for the current user. PowerShell **7.4+** is required (offline script checks run with
**7.6.6**). The module version is pinned to its published PowerShell Gallery package;
the owner has installed that SDK and successfully completed the isolated sign-in and
active-role check. That result does not establish Agent ID or Foundry compatibility.

The second command prompts before device-code sign-in. Complete sign-in yourself with
the account in the requested tenant; review any consent for **User.Read** and
**RoleManagement.Read.Directory**. On first use, Microsoft may provision the Graph
Command Line Tools enterprise application and record your consent. The script does
not grant permissions programmatically, request directory-write scopes, create Agent ID
objects, access an Azure subscription, or deploy resources.

The Graph context is explicitly `Process`-scoped, checked for the requested tenant and
delegated authentication before the read, and disconnected afterward. The command does
not call `az login`, change the Azure CLI subscription/tenant, read a credential file,
or export tokens. There is no reusable authenticated session for subsequent Python
commands. Share the redacted JSON result, not credentials or device codes.
Device-code instructions are displayed directly to the terminal, not discarded by
`Out-Null`. Failures include an exception type and any `AADSTS` numeric error codes;
raw exception messages, tokens and claims remain suppressed.

The one Graph GET reads the signed-in user's active directory-role memberships with
the documented advanced-query header/count. Output includes only relevant built-in
role names, SDK/runtime versions and verdicts, never account identifiers or full Graph
responses. Limited role metadata or additional pages are **inconclusive**, not evidence
of missing roles. PIM eligibility and Agent ID service availability are not evaluated.
Successful sign-in is not proof of Agent ID provisioning or Foundry compatibility.

### Interactive directory lifecycle

The lifecycle check now supports interactive Graph authentication without a certificate:

```bash
task identity:interactive-probe TENANT_ID=REPLACE-other-tenant-uuid
# If a run stops with recorded objects, use the same tenant and signed-in operator:
task identity:interactive-cleanup TENANT_ID=REPLACE-other-tenant-uuid
```

Both commands prompt before sign-in and directory mutations. Review the delegated Graph
consent request: `User.Read`, `AgentIdentityBlueprint.ReadWrite.All`,
`AgentIdentityBlueprintPrincipal.ReadWrite.All`, `AgentIdentity.Create.All`,
`AgentIdentity.Read.All`, and `AgentIdentity.DeleteRestore.All`. These are permissions
for this temporary lifecycle check, not Foundry grants. Sign in with the approved operator
in the selected tenant; an Azure subscription and a certificate deployer are not required.

PowerShell owns the process-local Graph authentication. The existing Python lifecycle
engine asks it to execute fixed-origin typed Graph requests over private process pipes;
no access token is exported to Python, a file, or the terminal. SDK retries are disabled
and requests use a 30-second timeout. The same engine and ownership/unknown-creation
guards serve the certificate and interactive paths.

**Wrapper correction (2026-10-19):** Graph SDK 2.36.1's `Set-MgRequestContext`
returns a settings object. The wrapper now discards that output so it cannot corrupt
the engine's final report; device-code instructions remain visible. The offline fake
SDK reproduces that return behavior. The previous wrapper could report
`interactive_directory_engine_failed` / `PropertyNotFoundException` **after the engine
had already run**. That error alone does not establish whether directory objects were
created or deleted.

If that error occurred, retain the existing journal and first run
`task identity:interactive-cleanup TENANT_ID=...` with the same operator and `STATE`
(if one was supplied). Cleanup verifies recorded remaining objects before deletion
and accepts a journal already marked fully deleted. An unknown creation still requires
administrator reconciliation; do not bypass it by deleting the journal. After successful
cleanup, a new lifecycle run requires a fresh `STATE`, as described below.

The private journal defaults to `.identity-probe/interactive-directory.json`, separate
from the certificate check. It is bound to the tenant, Graph client, and signed-in operator.
Cleanup refuses a different operator before any object lookup or deletion. An uncertain
creation retains its intent and is never retried automatically. Retain the journal;
for another approved run, provide a new `STATE=.identity-probe/interactive-2.json`
and use that same value for cleanup.

The real PowerShell script and Python engine completed creation, read/update verification
and reverse-order deletion against a local fake Graph SDK. **The owner also reported
a live lifecycle pass on 2026-10-19.** A lifecycle pass does not test Foundry, change Azure CLI context, provision
the browser/sidecar integration, or close I0.

## SDK-backed directory lifecycle check

The owner approved using documented Graph APIs/SDKs where Terraform cannot represent
the lifecycle. `identity:directory-probe` is a separate, opt-in compatibility check:
Azure Identity's `CertificateCredential` authenticates a dedicated Graph deployer;
bounded HTTPS requests use the canonical typed Graph v1.0 paths. No Azure CLI bearer,
client secret, Terraform state rewriting, consent changes, Azure RBAC, federation,
cluster access, hosted calls or public ingress are involved.

The check creates **three new temporary objects**: a blueprint, its mandatory blueprint
principal, and an Agent Identity. It reads each back, changes and reads the blueprint's
description, then deletes those objects in reverse dependency order and checks that
each typed resource is absent. A completed check reports `directory_lifecycle: pass`,
**not** Foundry delegation or containment success; `i0_complete` stays false.
The certificate backend has no reported live result; the interactive backend passed.
Graph deletion removes active objects but retains recoverable deleted objects for up to
30 days; this check does not permanently purge those tombstones.

First, review the offline plan:

```bash
task identity:directory-plan
```

Before an approved live run, configure these placeholders in your untracked `.env`
(also listed in `.env.example`):

```dotenv
IDENTITY_TENANT_ID=REPLACE-current-tenant-uuid
IDENTITY_GRAPH_CLIENT_ID=REPLACE-dedicated-graph-application-uuid
IDENTITY_SPONSOR_USER_ID=REPLACE-synthetic-sponsor-user-uuid
IDENTITY_GRAPH_CERTIFICATE_PATH=/REPLACE/private/graph-deployer.pem
```

The PEM must contain the deployer's certificate and private key, belong to the operator,
and have no group/other permissions (for example, mode `0600`). Register its public
certificate on the **dedicated deployer**, never on an Agent Identity. The check does
not bootstrap this application or grant its own privileges. The deployer needs reviewed,
admin-consented Microsoft Graph **application** permissions covering the operations:

| Object | Permissions used by this check |
| --- | --- |
| Blueprint | `AgentIdentityBlueprint.ReadWrite.All` |
| Blueprint principal | `AgentIdentityBlueprintPrincipal.ReadWrite.All` |
| Agent Identity | `AgentIdentity.Create.All`, `AgentIdentity.Read.All`, `AgentIdentity.DeleteRestore.All` |

These cover the check, not a recommendation for production-wide grants. The typed
Agent Identity read/delete references also list `AgentIdentity.CreateAsManager` for
application callers; review that alternative for a blueprint-manager design rather than
assuming create/read grants authorize deletion. The setup guide requires Privileged Role
Administrator authority to grant Microsoft Graph application permissions. An Azure
subscription role alone does not provide it. No privileged deployer or admin consent
has been created by this work.

After separate owner approval:

```bash
task identity:directory-probe
# Only if the run stops and leaves recorded objects:
task identity:directory-cleanup
```

`.identity-probe/directory.json` is an owner-only, gitignored journal bound to the
selected tenant and deployer. It records generated names and object IDs before later
operations; it never stores a token, private key, Graph response body or user claim dump.
Concurrent access, mismatched context and object ownership fail explicitly. A failed
check returns **inconclusive**, preserves the journal, and does not retry creation.
For HTTP errors, the report includes only the status; a 403 alone does not establish
whether consent, a role, tenant policy or service availability is responsible.

A timeout, 408, server error or malformed successful POST can leave creation uncertain.
The journal records that intent **before** POST, and cleanup then refuses to guess an ID.
An administrator must reconcile the generated name against directory/audit records.
Do not delete or edit the journal to bypass that warning. After a successful run or
cleanup, retain the journal as private evidence; use a new journal for another approved
run, for example `task identity:directory-probe STATE=.identity-probe/directory-2.json`.
Pass that same `STATE` to `identity:directory-cleanup` if needed. The default Task
targets deliberately refuse to overwrite an existing journal.

## Independent policy API identity code (not deployed)

The policy API now has an explicit, disabled-by-default `delegated` mode. Both
`/policy` and `/policy/{run_id}` use the same shared validator as the I0 probe.
`/healthz` remains liveness-only and unauthenticated. The receiver is unchanged.

The validator checks an RS256 signature using the configured tenant's fixed Microsoft
signing-key endpoint, issuer, exact audience, expiry/not-before, tenant, user object ID,
delegated scope and OAuth client. App-only tokens and forged identity headers do not
work. A separate configured user-ID set restricts access after authentication.
This is an implemented authorization option, **not an owner-approved rollout mapping**.
An authenticated tenant user is not automatically permitted.

| Result | Meaning |
| --- | --- |
| 200 | A permitted user/client/scope can read synthetic policy. |
| 401 + `WWW-Authenticate: Bearer` | Missing or invalid delegated credentials. |
| 403 | Insufficient scope, untrusted OAuth client, or user not authorized. |
| 503 | Signing keys unavailable/invalid; no stale-key or application-token fallback. |

Public signing keys alone are cached, for at most five minutes; unknown-key refresh is
throttled to thirty seconds. Key fetches verify TLS, use a five-second timeout and
disable redirects. No user/token/session cache or mutable global authorization header
exists. Request credentials have redacted representations; session-user keys are
tenant-qualified hashes rather than raw user IDs.

Review the commented `POLICY_API_*` placeholders in `.env.example`. All values are
required to enable delegated mode. Partial configuration, invalid IDs or an unknown mode
fail startup instead of falling back to the legacy API. Client IDs must be the **verified
OAuth client IDs** established by I0, not assumed Agent Identity or managed-identity IDs.
The API's audience/scope must be its own published contract, never the Foundry audience.
The policy image installs the pinned `policy-identity` profile from `pyproject.toml`;
`uv.lock` records the dependency resolution. No hosted-agent image has been rebuilt or replaced.

Policy authentication failures emit `authorization_decision`, not success receipts.
These records contain safe error categories and run markers, never tokens, claim dumps
or real user/client IDs. Policy access logging is disabled; structured logs sanitize
untrusted path/run markers. Responses in protected mode are not cacheable.

Run all offline identity checks with:

```bash
task identity:test
```

They use generated signing keys, fake Graph, and mocked HTTPS. No login, consent,
Azure call or deployment occurs. The private probe's source projection now includes
the shared validator; no hosted image rebuild is needed merely to prepare that probe.

**Still blocked:** public browser login requires the owner's hostname, certificate and
PKCE-versus-server-session choice. The delegated Foundry bearer, policy-token transport
and authenticated agent provenance still require I0. The harness and facade explicitly
reject `HARNESS_AUTH_MODE=delegated` and `DEMO_A2A_AUTH_MODE=delegated` at startup rather
than silently using shared credentials. No identity deployment target or ingress has
been enabled. Existing legacy mode remains for the private, port-forwarded demo only.

## Remaining full-setup blocker

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

**Correction to the initial finding:** the ordinary application API explicitly supports
blueprints at `/applications` with `@odata.type`, and the ordinary service-principal API
supports blueprint principals. Terraform therefore is **not universally incompatible**
with Agent ID. However, the generic provider sends diff-only PATCH bodies, potentially
omitting an unchanged type discriminator, and the complete Agent Identity lifecycle at
the untyped endpoints has not been established. The checked-in typed-URL draft remains
guarded; it is not the executable directory check above.

**Do not remove the guard to try a deployment.** Full setup still needs an integrated
ownership/lifecycle contract for identities, federation, consent and RBAC, whether
implemented with supported Terraform resources or the owner-approved Graph SDK/API path.
The separate temporary lifecycle check does not populate the Terraform draft or provision
the browser/sidecar integration.

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
  Agent Identity cleanup additionally needs a documented deletion permission such as
  `AgentIdentity.DeleteRestore.All`; do not infer it from create/read access.
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
task identity:directory-plan
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

- [Connect-MgGraph interactive authentication and process context](https://learn.microsoft.com/en-us/powershell/module/microsoft.graph.authentication/connect-mggraph?view=graph-powershell-1.0),
  [Invoke-MgGraphRequest](https://learn.microsoft.com/en-us/powershell/module/microsoft.graph.authentication/invoke-mggraphrequest?view=graph-powershell-1.0),
  and [pinned Graph Authentication package](https://www.powershellgallery.com/packages/Microsoft.Graph.Authentication/2.36.1).
- [Read signed-in user memberships and limited metadata](https://learn.microsoft.com/en-us/graph/api/user-list-transitivememberof?view=graph-rest-1.0)
  and [directory-role read permission](https://learn.microsoft.com/en-us/graph/api/directoryrole-get?view=graph-rest-1.0).
- [Sidecar endpoints and health](https://learn.microsoft.com/en-us/entra/msidweb/agent-id-sdk/endpoints).
- [Agent identity interactive pattern 4](https://learn.microsoft.com/en-us/entra/msidweb/agent-id-sdk/agent-identities).
- [Create blueprint](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprint-post?view=graph-rest-1.0)
  and [get blueprint: canonical typed instance path](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprint-get?view=graph-rest-1.0).
- [Create blueprint principal](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprintprincipal-post?view=graph-rest-1.0)
  and [create Agent Identity](https://learn.microsoft.com/en-us/graph/api/agentidentity-post?view=graph-rest-1.0).
- [Update blueprint](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprint-update?view=graph-rest-1.0),
  [get blueprint principal](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprintprincipal-get?view=graph-rest-1.0),
  [get Agent Identity](https://learn.microsoft.com/en-us/graph/api/agentidentity-get?view=graph-rest-1.0),
  [delete Agent Identity](https://learn.microsoft.com/en-us/graph/api/agentidentity-delete?view=graph-rest-1.0),
  [delete blueprint principal](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprintprincipal-delete?view=graph-rest-1.0),
  and [delete blueprint](https://learn.microsoft.com/en-us/graph/api/agentidentityblueprint-delete?view=graph-rest-1.0).
- [Base application blueprint support](https://learn.microsoft.com/en-us/graph/api/application-post-applications?view=graph-rest-1.0)
  and [base service-principal blueprint-principal support](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-post-serviceprincipals?view=graph-rest-1.0).
- [Agent ID setup and admin-consent prerequisites](https://learn.microsoft.com/en-us/entra/agent-id/agent-id-ai-guided-setup).
- [Delegated grant resource](https://learn.microsoft.com/en-us/graph/api/resources/oauth2permissiongrant?view=graph-rest-1.0).
  The generic v1.0 resource reference does not document `expiryTime`; no such field
  is invented here. Agent ID-specific grant support still needs tenant validation.
- [msgraph 0.5.0 lifecycle implementation](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/internal/services/msgraph_resource.go)
  and [resource schema](https://github.com/microsoft/terraform-provider-msgraph/blob/v0.5.0/docs/resources/resource.md).
