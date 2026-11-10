# Implementation plan

Updated 2026-11-10. This is the current delivery plan, not the original build proposal.
Superseded phase checklists and issue-specific squad plans are retained in Git history.

## Baseline

| Track | Status |
| --- | --- |
| Phase 0: compatibility | Completed; supported contracts and pins in [compatibility](compatibility.md) |
| Phases 1-7: hosted ADK, tools, egress and evidence | Implemented; dated live evidence in [telemetry map](telemetry-map.md) |
| Issue #4: user identity | Tested baseline, owner-confirmed 2026-11-06 |
| Issue #10: ACS G0-G3 | Implemented; real ACS/Rego and offline ADK boundary checks passed |
| Issue #10: ACS G4 deployment | Seven isolated agents active v4, three policies and seven model grants verified 2026-11-09; repeated deployment reused v4 |
| Issue #10: hosted comparison | Awaiting owner-run tests; deployment health is not a runtime result |
| Microsoft 365 Copilot | ACS-first chat and correlated deny/blocked events observed on v3 (2026-11-09) and v4 (2026-11-10); destination evidence and delegated lookup remain separate |
| Isolated OAuth extension | Isolated agent active v1 and separate Just you publication; authorized Copilot lookup and combined lookup/ACS-blocked send correlated with MCP/ACS evidence 2026-11-10; negative identity test deferred by owner, AKS/UI runtime regression pending |
| Phases 8-9: Dapr Workflow | Deferred; no dependency of the Copilot demo |
| Phase 10: messaging and portability | Deferred |

Do not rebuild the tested baseline or reinterpret an old failed spike as a current
blocker. A new deployment still requires its own runtime evidence.

## Implementation contract

Google ADK remains inside Foundry, with exactly two unconditionally registered
business tools. The diagnostic route uses the same implementations and governance
boundary; it is not a third tool. No arbitrary destinations, application hostname
allowlist, prompt-controlled governance mode or credential fallback.

The original Audit/Enforced egress experiment uses one image digest and identical
tool configuration. The attached network policy is the experimental variable.
ACS stays Disabled there. New governance scenarios use isolated agents and policies,
not changes to baseline or externally managed content-filter settings.

Generate implementation artifacts freely. The owner runs Task commands that install,
build, deploy, publish, mutate Azure/Entra/network configuration or invoke hosted
models. No new telemetry destination without approval. Local checks remain offline;
hosted and integration checks are opt-in.

## Issue #10 -- AGT/ACS runtime governance

### Standalone owner lifecycle

The owner selected reuse of the existing lab foundation. `cloud:up` remains
unchanged. The normal ACS interface is `acs:up`, `acs:build`, `acs:deploy`, optional
`acs:copilot`, and `acs:status` (`acs:report` alias). Infrastructure/publisher RBAC,
image builds and runtime deployment are separate lifecycle phases, not a checklist
of low-level registration, policy, helper and grant Tasks.

`up` ensures policy infrastructure, shared helper prerequisites, the dedicated
OAuth registration and publisher access without needing built agent images.
`deploy` ensures agent-specific grants after those agent identities exist.
`copilot` operates the existing owned ACS-first publication; it reuses an unchanged
publication and never blindly resubmits after an uncertain write. Reports show
resource identifiers, versions and sample prompts, and distinguish live readback
from recorded state and hosted runtime evidence.

Protected lookup is not supplied by the original publication. It now works in the
separate OAuth entry; see the dated acceptance evidence and remaining identity/UI
gates below. Consolidating Tasks alone is not runtime proof.

On 2026-11-09, the owner authorized execution while away. `acs:up`, `acs:build`,
`acs:deploy`, `acs:copilot` and `acs:status` completed against the existing
foundation. Build `dtc` used committed source `a87cc7a`; all seven agents are
active version `4`. The existing ACS-first publication retained its title ID and
now pins version `4`. Repeated deployment/publication reused those resources.
Before/after readback confirmed the original policy properties, API images and
selected authorization configuration, and account public-network setting were
unchanged. No hosted comparison/model calls or toolbox deployment were performed.
The actual digest and publication identifiers are recorded in
[compatibility](compatibility.md#acs-lifecycle-and-status-transport----2026-11-09).

### G0-G3 -- completed implementation

- Published ACS 0.3.1b1, manifest schema 0.3.1-beta and OPA 1.9.0 are pinned.
- Rego allows servicing and denies external processing, with an independent
  allow policy for the network-denial comparison.
- ADK's supported `before_tool_callback` and authenticated diagnostics share
  pre-tool evaluation and explicit host enforcement.
- Disabled skips evaluation; Audit records and continues; Enforced blocks denials,
  approval requirements and evaluation failures.
- Decision evidence excludes tokens, prompts, payloads and tool arguments.
- Offline regressions and five tamper checks passed 2026-11-06.

### G4 -- isolated hosted scenarios and owner-run Task automation

Initial deployment completed 2026-11-09 with all seven scenario agents active as
version `1` on the same image digest. The latest owner-authorized ACS setup
updated all seven to active version `4`; use `acs:status` for current versions.
The first successful Copilot conversation below used version `3`; a second
correlated deny/blocked event was observed on version `4` on 2026-11-10.
Existing baseline policy properties were preserved.

| Scenario | ACS / host | Foundry network | Required runtime evidence |
| --- | --- | --- | --- |
| Governance denial | Deny / block | Both APIs allowed | ACS denial, execution prevented, no receiver receipt, receipt positive control |
| Network denial | Allow / execute | Receiver denied | ACS allow, attempt, platform Deny, no receiver receipt, servicing receipt |
| Success | Allow / execute | Both APIs allowed | ACS allow, execution and matching receipts |
| Evaluation failure | Error / block | Both APIs allowed | Distinct evaluator error, no execution, receipt positive control |
| Audit control | Deny / continue | Both APIs allowed | Non-enforcing denial, execution and receiver receipt |
| Baseline Audit | Disabled | Receiver would-deny | Platform Audit decision and receiver receipt |
| Baseline Enforced | Disabled | Receiver denied | Platform Deny and no receiver receipt |

Remaining gates:

- [ ] Owner runs the hosted comparison: deterministic and model-selected paths
      separately, with an authorized synthetic user.
- [ ] Inspect real hosted ACS event rows and confirm the candidate telemetry mapping.
- [ ] Check the original egress regression clones without modifying the baseline.
- [ ] Retain pass/fail/inconclusive reports and tested configuration readback.

`governance:run` makes fourteen hosted calls; it is operator regression automation,
not the end-user Copilot experience. The owner chose to perform manual tests.

### G5 -- Microsoft 365 Copilot experience

Deliver one published demo agent that an end user selects in Microsoft 365 Copilot.
The user signs in and types a business prompt; they do not install this repository,
run Tasks, export tokens or configure GitHub Copilot.

The owner selected **Shared / Just you**, with the **ACS-blocked action first**.
That original entry still does not supply delegated lookup. The separate OAuth
publication now supports authorized lookup and the combined prompt, without
changing the baseline API authentication.

- [x] Implement Foundry's native publication API for the owned governance-denial agent.
- [x] Observe channel delivery into the hosted ADK runtime and a successful reply.
      The initial model-authentication failure was corrected in version 3.
- [x] Preserve existing endpoint protocols and authorization schemes when enabling
      scoped Activity access. Publication does not change account PNA; preserve the
      owner's separately approved selected-IP/default-Deny configuration.
- [x] Automate metadata, publication and readback through a small Task workflow.
      Choose publication scope explicitly; do not silently publish tenant-wide.
- [x] Generate request-scoped chat markers without end-user headers, retaining the
      direct-client header contract. Include the marker in the chat reply.
- [x] Owner deployed the chat-capable image and published Shared/Just you, pinned
      to version 2. Authorization and endpoint readback succeeded.
- [x] Owner deployed the v1 model-authentication correction, pinned version 3 and
      obtained a fresh chat reply with its Demo run marker.
- [x] Validate authorized downstream delegation through the separate OAuth channel.
      Negative identity acceptance remains deferred. Microsoft 365 sign-in alone
      is not a policy API token; never substitute app credentials.
- [x] Correlate a natural-language turn, model-selected tool and ACS outcome with
      destination evidence in the isolated OAuth entry on 2026-11-10.
- [x] Demonstrate the model-selected blocked send in Copilot. The 2026-11-09
      [chat and matching ACS event](telemetry-map.md#microsoft-365-copilot-blocked-action-observation)
      record `send_to_external_processor`, `deny`, `blocked` and
      `external_processor_prohibited`; this is not just a model refusal.
- [x] Demonstrate permitted lookup and the combined prompt with delegated auth in
      **ACS OAuth Servicing Demo** v1, with actual MCP receipts.
- [x] Published entry point: Microsoft 365 Copilot -> Your agents ->
      **ACS Servicing Demo**. No AKS ingress or browser harness is used.

Primary publication references, accessed 2026-11-09:
[portal](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot),
[REST/private networking](https://learn.microsoft.com/azure/foundry/agents/how-to/publish-copilot-virtual-network).

### G5 follow-on -- isolated toolbox project (owner-selected plan)

The owner selected a **separate Foundry project** on 2026-11-09. Do not enable
toolbox routing in the existing project or deploy the earlier same-project variant.
Runtime/MCP code, isolated Terraform, deployment/publication Tasks and offline
regressions are implemented. The owner reported the dedicated images built on
2026-11-09; `acs:up` ensures the dedicated Entra client.

Owner-authorized continuation on 2026-11-10 provisioned the separate project
`normal-manatee-55075-copilot`, its ready `agents` capability host, protected MCP
service `normal-manatee-55075-copilot-mcp`, dedicated RAI policy, separate link
to the existing telemetry destination and scoped grants. Terraform validation
passed and a repeat guarded plan reported **No changes**.

The initial unsupported-target `error` and `useCustomConnector: false` were
incorrectly interpreted as an OAuth rejection. Live private-endpoint fields were
`NotApplicable`; a working telemetry connection carried a similar error. Functional
probing instead returned `CONSENT_REQUIRED`, followed by a real completed consent.
The owner-created connection `normal-manatee-copilot` now has its actual callback
registered and a securely bound 30-day credential; an existing credential was
preserved. Immutable toolbox `copilot-policy` v2 uses that connection.

An approved exact-host managed-network FQDN rule removed the downstream TLS
failure. The service then correctly rejected the consenting admin as
`user_not_authorized`. The owner approved adding that identity to the isolated MCP
only, retaining the original guest. The guarded Terraform plan changed only that
user list; a repeat plan reported **No changes**. Discovery returned
`policy___get_servicing_policy` with approval policy `never`, and one separately
approved synthetic developer lookup returned `SVC-DEMO-0001`. This is not a hosted
agent or Copilot acceptance result. Subsequently, the owner approved deploying
isolated agent v1 and the separate **ACS OAuth Servicing Demo** publication,
Shared / Just you. Owner-run lookup and combined lookup/blocked sending succeeded
with correlated MCP receipts and ACS evidence. The owner deferred the negative
identity test without changing access; AKS/UI runtime regression remains pending.
The original publication still pins v4. See
[the verified setup and remaining gates](governance-demo.md#8-operator-reference-isolated-toolbox-project).

Read-only Azure discovery found a ready account-level `Agents` capability host,
with no explicit BYO storage/vector/conversation connections, and **no project-level
capability host** in the existing project. The documented prerequisite for external
toolbox calls in a network-isolated project is a project-level capability host.
Creating one on the existing project would change project-wide routing, so that
approach is not approved.

Plan, in dependency order:

1. **Infrastructure provisioned, 2026-11-10.** Use a separate Terraform state
   owning a convention-named Copilot project and its
   project-level capability host. Reuse the current account's existing managed
   networking and platform-managed data resources. Verify
   this combination's ARM contracts and runtime support before creating resources.
   The one exact-host MCP rule below is explicitly approved; any other account-wide
   change still requires separate approval.
2. **Service and developer delegated execution verified, 2026-11-10; channel pending.**
   Deploy a separate protected MCP policy service, using the existing delegated
   verifier and policy response logic. Give it a dedicated OAuth client; retain
   the original API audience, scope and original authorized guest. Additional
   isolated users require explicit approval through
   `TF_VAR_mcp_additional_authorized_user_ids`; the default adds nobody.
   Do not change the existing policy API, UI client, OBO settings or receiver.
3. **Developer discovery and one synthetic lookup verified, 2026-11-10.**
   Connection, callback, real credential and immutable toolbox v2 are configured
   **in the new project**. The existing `copilot-toolbox:infra-up` now consolidates
   registration, infrastructure, exact-host egress, credential, actual callback,
   immutable toolbox selection and delegated discovery. Browser consent is still
   interactive; rerun the same command afterward. Deployment derives endpoint/tool
   from the owned configuration journal, without manual exports. Existing resources
   were reused live with a no-change Terraform plan. Fresh creation, renewal and
   teardown are covered offline, not claimed as a tested live rebuild.
   Preserve journals and credential expiry/rotation ownership.
   Do not treat generic connection metadata, consent or discovery alone as lookup
   success. Do not replay a completed consent link to switch identities.
4. **Deployed v1, 2026-11-10.** Deploy a new owned agent in the new project, with exactly the same two ADK tools
   and ACS-first enforcement. Use dedicated image repositories, version journals,
   scoped grants and a dedicated RAI policy. Reuse the existing private operator
   helper only through isolated files/process environment, without rolling out
   any AKS/UI workload or overwriting its journals.
5. **Published 2026-11-10.** Create a **separate Microsoft 365 Copilot publication and journal**.
   **ACS OAuth Servicing Demo**, title `T_eccd3260-6696-eb05-5c28-ee705fb2e742`,
   pins isolated v1. The existing
   publication cannot be repinned to an agent version in another project; leave
   its endpoint, version pin and catalog entry unchanged.
6. **Authorized lookup and combined lookup/ACS-blocked send verified 2026-11-10.**
   Actual toolbox outcomes, dedicated MCP receipts and ACS allow/deny decisions
   correlate with the owner's Copilot run markers. The negative identity test is
   deferred by owner choice; access remains unchanged. Recheck the existing AKS/UI
   flow independently; configuration preservation is not a new UI runtime result.
   Keep toolbox authorization evidence separate from direct-HTTP containment proof.

The `copilot-toolbox:*` Task workflow covers preflight, offline checks/tampering,
build, separate provisioning, deploy/publish, status, recovery and owned teardown.
The new project links the existing Application Insights destination; it does not
create a new telemetry destination. The reused Application Insights connection
string remains in sensitive Terraform state, not plan output or deployment
journals. The OAuth secret was created and passed directly to the connection in
memory; it was not written to Terraform state, arguments, journals or logs.
The workflow must not call `governance:up`,
`deploy:tool-apis` or apply the baseline cloud state to enable this feature.
The owner runs builds, resource changes and hosted calls.

A separate project isolates configuration, agents, connections and publication;
it does **not** create an independent network or model-capacity boundary inside
the same account. The owner explicitly approved retaining the single
`copilot-toolbox-mcp` FQDN rule after it restored transport. Existing outbound rules
and `AllowOnlyApprovedOutbound` remain unchanged. The owner separately confirmed
that selected-IP public access, enabled before that test, is intentional and must
be retained. These exceptions do not authorize any other account-network change.
Initial read-only discovery changed no Azure configuration; the isolated resources
above were subsequently provisioned with the owner's explicit continuation approval.

## Deferred work

Human approval resolution, ACS A2A authorization, APIM and Agent 365 remain separate
extensions. An approval-bearing ACS result stays blocked in Enforced mode.

Dapr Workflow would run on AKS with a persistent actor-compatible state store,
authenticated approval events, a durable deadline and pod-restart recovery.
It would invoke the unchanged Foundry agent from activities. Azure Durable Task
Scheduler and its SDK are not dependencies. PostgreSQL remains disabled until needed.
True on-premises/OpenShift deployment and messaging bridges need separate validation.

## Definition of done

The owner can rebuild, publish and exercise the Azure demo with Task targets.
An end-user conversation shows independent identity, ACS and network outcomes.
Every claimed result is supported by its own evidence; missing evidence remains
inconclusive. No baseline policy, business-tool invariant or telemetry privacy rule
is weakened to make the walkthrough work.
