# Issue #4: delegated Foundry authentication probe

**2026-10-19: owner reports directory lifecycle passed and integrated setup configured.**
The owner completed isolated Graph sign-in and reported `directory_lifecycle: pass`
after creation, read/update verification and cleanup. The owner subsequently reported
`tenant_check=pass`, `tenant_verified=true`, `identity_setup=configured`,
`foundry_delegation=not_evaluated`, and `i0_complete=false` from live `identity:setup`.
These are owner-reported results, not independently observed delegated invocation evidence.
No hosted identity invocation has been reported. This does not establish Foundry
delegation or containment.
This is the first part
of [I0](PLAN.md#i0--compatibility-and-identity-contract-first-gate), not an identity rollout.
Existing hosted agents, policies, images and both business tools are unchanged.

## Run the probe using the completed setup

With the existing private `.identity-probe/setup-state.json` and matching `config.json`,
the expected AKS context selected, and existing CLI/Python prerequisites available:

```bash
task identity:verify
```

This target validates the completed setup **locally without changing it**. It does not
create identities, apply Terraform, start PowerShell, install modules, or request another
Graph operator sign-in. It does not silently reuse an operator token or introduce a
persistent token cache. Missing, partial, unknown-outcome, or mismatched setup is refused;
verification is not a setup/recovery command.

The two interactive Entra sign-ins are necessary actor transitions: first select the
configured **allowed synthetic test user**, then the **denied synthetic test user**.
They obtain distinct test-user tokens, not operator credentials. Actual authentication
and any consent remain interactive. Earlier advanced Graph commands below each use
separate process-local sessions; running them separately is not a prerequisite for
verification and would redundantly request operator authentication.

The target checks the existing context, namespace, Kubernetes 1.33+ requirement and
resource ownership, starts the isolated probe, and waits at most **660 seconds** for Job
completion (a failed Job may use that entire wait). API calls and cleanup add bounded
operation time; this is not a 660-second deadline for the interactive sign-ins.
Only a successful Job with the probe's complete positive/negative-control evidence can
report `foundry_delegation=pass`. Failures and inconclusive results return nonzero.
`i0_complete=false` and `containment=not_evaluated` remain unchanged: this probe does
not establish the HTTPS UI, downstream delegated policy runtime, or the full I0 gate.

The private, mode-600 `.identity-probe/verification-result.json` contains a redacted
verdict and fixed reason code; when probe output is available it includes only whitelisted
case names, stages, verdicts and HTTP statuses, plus validated optional correlation IDs.
It never contains raw logs, token claims, arbitrary exception text, prompts or responses.
A new run resets the result before sign-in; a login failure records which test-user
stage failed. Missing/malformed logs and unsuccessful Job state are not passes.

Normal success and failure paths remove local `allowed.jwt` / `denied.jwt`, stop the
owned probe Job, and delete its token Secret. The journal/config, Graph identities,
Azure RBAC, source ConfigMap, ServiceAccount and redacted result remain for reuse.
Cleanup failure makes the command fail even if the probe passed. If cluster access or
ownership checks prevent deletion, or execution is forcibly interrupted, remote cleanup
may remain incomplete. After restoring the expected cluster access, use:

```bash
task identity:verify-cleanup
```

That recovery target removes local tokens first and retains all ownership/context guards
before remote deletion. It does not delete Graph identities. This verification workflow
is **source/offline tested only**; it has not been freshly deployed or live-verified by
the assistant. Full workshop up/teardown consolidation remains separate work.

## Isolated interactive tenant check

Use the same tenant as the rebuilt Foundry account and AKS cluster:

```bash
task identity:graph-init
task identity:tenant-check TENANT_ID=REPLACE-deployment-tenant-uuid
```

The first command installs **Microsoft.Graph.Authentication 2.36.1** without a Task confirmation
for the current user. PowerShell **7.4+** is required (offline script checks run with
**7.6.6**). The module version is pinned to its published PowerShell Gallery package;
the owner has installed that SDK and successfully completed the isolated sign-in and
active-role check. That result does not establish Agent ID or Foundry compatibility.

The second command starts device-code sign-in without a Task confirmation. Complete sign-in yourself with
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
task identity:interactive-probe TENANT_ID=REPLACE-deployment-tenant-uuid
# If a run stops with recorded objects, use the same tenant and signed-in operator:
task identity:interactive-cleanup TENANT_ID=REPLACE-deployment-tenant-uuid
```

Both commands start sign-in and directory mutations directly. Review the delegated Graph
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

The owner starts the approved lifecycle operation directly:

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

## Integrated SDK/API setup (source/offline verified, not deployed)

Terraform now manages **only** the generated `random_pet` + `random_id` name,
incoming scope UUID, and allowed user's project-scoped Azure invoke role. It does not
manage Graph objects or run an external provisioner. The existing cloud state and
working hosted agents remain separate.

`identity:setup` first applies that isolated Terraform module, then signs in with
Graph PowerShell and runs `identity_setup.py` through the existing private request/reply
pipe. Graph tokens never leave PowerShell. Setup creates and reads back a browser
public client/principal, blueprint/principal, child Agent Identity, exact AKS
ServiceAccount federation, scope-only permission inheritance, and four per-user
delegated grants. It configures and verifies the blueprint's identifier URI.
Neither the denied user nor the agent receives an Azure invoke role.

Current primary guidance says to preauthorize interactive child-agent permissions on
the parent blueprint. Foundry consent is therefore granted to the **blueprint
principal**, for only the two test users; the child inherits delegated scopes for that
one verified resource. `inheritableRoles` is explicitly `none`. No tenant-wide
`AllPrincipals` consent, application permissions, secrets, or app-only fallback are added.
Incoming browser consent targets the blueprint principal, also per user.

The Agent Identity's returned **`id`** is used for the sidecar's `AgentIdentity` parameter,
not an assumed `appId` property. Blueprint/browser client IDs remain their actual `appId`
values. These are distinct identifiers with distinct roles.

Before creating any Graph object, setup checks the selected resource's actual ID,
`https://ai.azure.com` service-principal name, candidate audience, and enabled delegated
scope. It does not guess a Foundry permission or treat a published scope as proof that
the hosted endpoint accepts its token.

The owner-only `.identity-probe/setup-state.json` journal is bound to the exact inputs,
Graph client and signed-in operator. It records intent before each non-idempotent POST,
keeps successful resources for the subsequent probe, and never retries uncertain creation.
A rejected request leaves known objects cleanable; a timeout/server/transport error with
unknown creation requires administrator reconciliation. Do not delete the journal.
`identity:setup` refuses an existing journal before Terraform apply; use `configure`
to re-export a completed setup or `setup-cleanup` to delete recorded Graph objects.

Cleanup checks **all** remaining objects' names, linkage, federation and consent
configuration before deleting any, then verifies reverse-order deletion. It will not
adopt/delete an unrelated object or silently alter a changed grant. Cleanup refuses
while the dedicated probe workload or token Secret remains. It also works after partial
setup when no final probe configuration exists. `setup-down` cleans Graph before removing
Terraform-managed naming/RBAC. Neither command touches the working containment agents.

Offline validation executes the real PowerShell wrapper against a local fake Graph SDK,
including persistence, config export, deletion, read-only contract discovery, approval,
operator isolation, uncertain creation and redaction. Mocked Terraform tests cover the
same-tenant guard, including targeted RBAC plans. **No live persistent setup, sidecar
exchange, or delegated hosted invocation is claimed.**

### Historical provider blocker (replaced, not bypassed)

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
The original typed-URL draft therefore rejected plans before apply.

**Correction to the initial finding:** the ordinary application API explicitly supports
blueprints at `/applications` with `@odata.type`, and the ordinary service-principal API
supports blueprint principals. Terraform therefore is **not universally incompatible**
with Agent ID. However, the generic provider sends diff-only PATCH bodies, potentially
omitting an unchanged type discriminator, and the complete Agent Identity lifecycle at
the untyped endpoints has not been established. The checked-in typed-URL draft remains
never became an executable setup.

The replacement removes **all msgraph-managed resources and the msgraph provider**,
rather than disabling the guard on those unverified URLs. Canonical Graph SDK/API lifecycle,
private ownership journaling and Terraform-only Azure RBAC now implement the integrated
setup. The temporary directory check remains separate and need not be repeated.

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

The isolated Terraform state and Graph journal are **not included in `cloud:up` or `deploy:all`**.
The integrated setup's resources are a browser public client and service principal, an Agent ID
blueprint and mandatory blueprint principal, an Agent Identity, blueprint workload
federation, per-user incoming/OBO consent, and one project-scoped **Foundry Agent
Consumer** assignment to the allowed user. Names use `random_pet` plus `random_id`.
The blueprint defines its own incoming `access_as_user` scope; that is **not** a
claim that Foundry publishes a scope with this name.

Before reviewed setup, the owner must supply:

- The approved same-tenant Graph operator and reviewed delegated consent for:
  `User.Read`, `Application.ReadWrite.All`, `AgentIdentityBlueprint.ReadWrite.All`,
  `AgentIdentityBlueprintPrincipal.ReadWrite.All`, `AgentIdentity.Create.All`,
  `AgentIdentity.Read.All`, `AgentIdentity.DeleteRestore.All`,
  `AgentIdentityBlueprint.AddRemoveCreds.All`, and `DelegatedPermissionGrant.ReadWrite.All`.
  Setup/cleanup request these through process-scoped Graph sign-in; the operator also
  needs the applicable directory roles. No certificate deployer or Azure CLI Graph
  bearer is used. The independent certificate directory check remains optional.
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
`terraform.tfvars` after inspecting the contract and reviewing those inputs. Never commit actual user IDs,
certificates, tokens, Terraform state or private configuration.

## Owner commands

Available **now**, with no tenant or cluster access:

```bash
task identity:test
task identity:directory-plan
task identity:sdk-test  # downloads isolated SDK dependencies without a Task confirmation
terraform -chdir=infra/identity-probe validate
terraform -chdir=infra/identity-probe test
```

The real-SDK mocked request tests use `azure-ai-projects==2.8.0`,
`openai==3.31.0`, `httpx==0.28.1`, `PyJWT==2.15.1`, and `cryptography==50.0.2`.
The ordinary dev suite skips those optional SDK cases if projects SDK is absent;
`identity:sdk-test` runs them in isolation without changing the agent/model stack.
Mocked Terraform validation used the already-installed AzureRM **4.81.0** and random
**3.9.1** providers in an isolated copy; no provider was installed and the owner's deleted
identity lock file was not restored. Run `identity:init` to initialize this module
before its local Terraform commands on the owner's machine. Schema validation is not
proof of live Graph API compatibility.

**First owner-run step: read-only contract inventory.**

```bash
task identity:foundry-contract TENANT_ID=REPLACE-deployment-tenant-uuid
```

This requests only `User.Read` and `Application.Read.All`, makes one bounded Graph
resource query, and prints resource IDs, candidate audiences and enabled delegated scopes.
No identity, grant, Azure role, cluster workload or hosted call is changed.
Identity tasks have no extra Task confirmations. Explicitly running a mutation, billable
probe or deletion target authorizes that operation; Terraform apply/destroy also run
without another confirmation. Entra sign-in and consent still apply. Tenant, context,
ownership and journal guards remain enforced.
An absent/ambiguous resource, pagination or no enabled scope is **inconclusive**;
do not guess a scope or substitute workload authentication.

**After contract review and filling the private Terraform inputs, owner-run sequence:**

```bash
task identity:init
task identity:setup-plan
task identity:setup
# On a completed setup, configure can re-export the private config without recreation:
# task identity:configure
task identity:login CASE=allowed
task identity:login CASE=denied
task identity:manifest
task identity:probe
task identity:status
task identity:down
task identity:setup-down
```

The owner initiates setup/RBAC and probe execution through their respective Task targets;
the assistant does not run them independently. Entra consent remains interactive. Login uses
the browser client's localhost callback (`http://localhost:8400`), validates the chosen
test persona before writing, and saves short-lived JWTs in owner-only gitignored files
without a persistent token cache. This localhost probe is not the future HTTPS UI.
If Terraform completes but the local export fails before Graph setup, fix the export
error and rerun `identity:setup`. Terraform reuses the applied state, and the setup-journal
precondition prevents blindly repeating Graph creation. The atomic export uses `mktemp`
for an owner-only file without the unsupported `umask` builtin in Task's embedded shell.
The Job's read-only Secret is short-lived but remains a credential: run
`identity:down` after collecting results, even if the Job has expired.
Remove the two local JWT files after the experiment; Kubernetes TTL does not remove
the Secret or the local files. Then destroy the dedicated identity state.
Keep the setup journal and exact Terraform inputs for cleanup. If setup stops before
the final config is exported, use `task identity:setup-cleanup` rather than `identity:down`;
it checks for remaining workloads using the setup inputs and retains Azure RBAC for review.

Cluster operations validate configuration, expected context and namespace, server
version, and resource ownership before use. They cannot silently overwrite or delete
an unrelated resource with the same name. Secret apply is server-side, without a
client-side last-applied annotation containing a second token copy.

## Primary references

Rechecked **2026-10-19** for the integrated setup:

- [Interactive-agent pattern 4](https://learn.microsoft.com/en-us/entra/msidweb/agent-id-sdk/agent-identities).
- [Agent OBO protocol and required preauthorization](https://learn.microsoft.com/en-us/entra/agent-id/agent-on-behalf-of-oauth-flow).
- [Scope inheritance, no-role inheritance, exact navigation lifecycle](https://learn.microsoft.com/en-us/entra/agent-id/configure-inheritable-permissions-blueprints).
- [Create/configure blueprint, FIC, identifier URI and scope](https://learn.microsoft.com/en-us/entra/agent-id/create-blueprint).
- [Agent Identity properties](https://learn.microsoft.com/en-us/graph/api/resources/agentidentity?view=graph-rest-1.0).
- [Federated credential v1.0 lifecycle](https://learn.microsoft.com/en-us/graph/api/federatedidentitycredential-post?view=graph-rest-1.0)
  and [per-user delegated grants](https://learn.microsoft.com/en-us/graph/api/oauth2permissiongrant-post?view=graph-rest-1.0).

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
