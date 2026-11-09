# Implementation plan

Updated 2026-11-09. This is the current delivery plan, not the original build proposal.
Superseded phase checklists and issue-specific squad plans are retained in Git history.

## Baseline

| Track | Status |
| --- | --- |
| Phase 0: compatibility | Completed; supported contracts and pins in [compatibility](compatibility.md) |
| Phases 1-7: hosted ADK, tools, egress and evidence | Implemented; dated live evidence in [telemetry map](telemetry-map.md) |
| Issue #4: user identity | Tested baseline, owner-confirmed 2026-11-06 |
| Issue #10: ACS G0-G3 | Implemented; real ACS/Rego and offline ADK boundary checks passed |
| Issue #10: ACS G4 deployment | Seven isolated agents active, three policies and seven model grants verified 2026-11-09 |
| Issue #10: hosted comparison | Awaiting owner-run tests; deployment health is not a runtime result |
| Microsoft 365 Copilot | ACS-first chat and correlated deny/blocked event observed on version 3, 2026-11-09; destination evidence and delegated lookup remain separate |
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

Protected Copilot lookup remains a separate blocked gate, not a capability made
ready by renaming or consolidating Tasks.

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
version `1` on the same image digest. Later owner deployments updated the image;
use `governance:status` for current versions. The published Copilot run below used
version `3`. Existing baseline policy properties were preserved.

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
Successful policy lookup and the combined prompt are deferred until downstream
user delegation is available; API authentication remains unchanged.

- [x] Implement Foundry's native publication API for the owned governance-denial agent.
- [x] Observe channel delivery into the hosted ADK runtime and a successful reply.
      The initial model-authentication failure was corrected in version 3.
- [x] Preserve existing endpoint protocols and authorization schemes when enabling
      scoped Activity access. Do not enable account-wide public network access.
- [x] Automate metadata, publication and readback through a small Task workflow.
      Choose publication scope explicitly; do not silently publish tenant-wide.
- [x] Generate request-scoped chat markers without end-user headers, retaining the
      direct-client header contract. Include the marker in the chat reply.
- [x] Owner deployed the chat-capable image and published Shared/Just you, pinned
      to version 2. Authorization and endpoint readback succeeded.
- [x] Owner deployed the v1 model-authentication correction, pinned version 3 and
      obtained a fresh chat reply with its Demo run marker.
- [ ] Validate downstream delegated API authorization for the channel. Microsoft 365
      sign-in alone is not a policy API token; never substitute app credentials.
- [ ] Correlate a natural-language turn, model-selected tool and ACS outcome with
      destination evidence. Do not require direct-client headers from an end user.
- [x] Demonstrate the model-selected blocked send in Copilot. The 2026-11-09
      [chat and matching ACS event](telemetry-map.md#microsoft-365-copilot-blocked-action-observation)
      record `send_to_external_processor`, `deny`, `blocked` and
      `external_processor_prohibited`; this is not just a model refusal.
- [ ] Later: demonstrate permitted lookup and the combined prompt with delegated auth.
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
2026-11-09; deployment and hosted acceptance remain unverified. A guarded owner-run
`acs:up` now ensures the dedicated Entra client. The extension's separate project,
MCP service and connection are not provisioned by the core ACS lifecycle while
its custom-OAuth provisioning contract remains unverified.
The owner ran registration; readback verified the dedicated application and its
requested delegated permission, with no secret or callback configured.
Foundry custom-OAuth connection/callback/credential
automation remains blocked pending its verified provisioning contract; GitHub
source access was denied by organization SAML enforcement. This does not block
the separately documented Entra registration API.
See [the blocked extension](governance-demo.md#8-operator-reference-isolated-toolbox-project).

Read-only Azure discovery found a ready account-level `Agents` capability host,
with no explicit BYO storage/vector/conversation connections, and **no project-level
capability host** in the existing project. The documented prerequisite for external
toolbox calls in a network-isolated project is a project-level capability host.
Creating one on the existing project would change project-wide routing, so that
approach is not approved.

Plan, in dependency order:

1. Add a separate Terraform state owning a convention-named Copilot project and its
   project-level capability host. Reuse the current account's existing managed
   networking and platform-managed data resources without changing them. Verify
   this combination's ARM contracts and runtime support before creating resources.
   If it requires account-wide changes, stop for a separate-account decision.
2. Deploy a separate protected MCP policy service, using the existing delegated
   verifier and policy response logic. Give it a dedicated OAuth client; retain
   the original API audience, scope and synthetic-user authorization requirements.
   Do not change the existing policy API, UI client, OBO settings or receiver.
3. Configure an OAuth connection and immutable toolbox version **in the new project**.
   The owner requested creation automation. Keep placeholders while the custom
   OAuth provisioning/callback contract remains unverified; do not guess fields
   or treat the dedicated client's registration as completed connection setup.
   Verify downstream network reachability; a toolbox listing is not a successful MCP call.
4. Deploy a new owned agent in the new project, with exactly the same two ADK tools
   and ACS-first enforcement. Use dedicated image repositories, version journals,
   scoped grants and a dedicated RAI policy. Reuse the existing private operator
   helper only through isolated files/process environment, without rolling out
   any AKS/UI workload or overwriting its journals.
5. Create a **separate Microsoft 365 Copilot publication and journal**. The existing
   publication cannot be repinned to an agent version in another project; leave
   its endpoint, version pin and catalog entry unchanged.
6. Owner-run acceptance: consent and authorized lookup; an unauthorized user's
   lookup denied by the MCP service; external processing ACS-blocked; correlated
   ACS and dedicated-service receipts. Recheck the existing AKS/UI flow independently.
   Keep toolbox authorization evidence separate from direct-HTTP containment proof.

The `copilot-toolbox:*` Task workflow covers preflight, offline checks/tampering,
build, separate provisioning, deploy/publish, status, recovery and owned teardown.
The new project links the existing Application Insights destination; it does not
create a new telemetry destination. Connection credentials remain in sensitive
Terraform state, not plan output or deployment journals.
The workflow must not call `governance:up`,
`deploy:tool-apis` or apply the baseline cloud state to enable this feature.
The owner runs builds, resource changes and hosted calls.

A separate project isolates configuration, agents, connections and publication;
it does **not** create an independent network or model-capacity boundary inside
the same account. Account-level network changes remain prohibited by this plan.
No Azure configuration was changed during discovery.

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
