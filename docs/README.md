# Agent Boundary Lab documentation

The lab demonstrates three independent controls in Azure:

1. **Identity:** the protected servicing API accepts an authorized user's delegated
   token and rejects an unauthorized user.
2. **ACS governance:** the Foundry-hosted ADK runtime evaluates a proposed tool call
   before executing it.
3. **Foundry egress:** the platform controls which HTTPS destinations an executing
   tool can reach.

Exactly two business tools are always registered: `get_servicing_policy` and
`send_to_external_processor`. Tool destinations come from validated startup settings,
not the prompt. ACS denial is application governance, not platform network enforcement.

## Start here

For the standalone ACS lifecycle on the existing lab foundation, use
`acs:up`, `acs:build`, `acs:deploy`, optional `acs:copilot`, and `acs:status`
(`acs:report`). Use the [canonical deployment sequence](rebuild-runbook.md#current-acs-and-copilot-lifecycle)
for both tracks, metadata, consent, recovery and teardown.
`cloud:up` is unchanged. Protected lookup uses the separate **ACS OAuth Servicing
Demo** entry, not the original **ACS Servicing Demo** publication.

| Document | Purpose |
| --- | --- |
| [Demo runbook](demo-runbook.md) | Present the tested identity and egress baseline |
| [Governance demo](governance-demo.md) | Microsoft 365 Copilot prompts, isolated ACS scenarios and operator evidence |
| [Rebuild runbook](rebuild-runbook.md) | Task-driven provisioning, deployment, recovery and teardown |
| [Architecture](architecture-as-built.md) | Components, call paths and trust boundaries |
| [Implementation plan](PLAN.md) | Current work and remaining acceptance gates |
| [Workshop](workshop/README.md) | Guided baseline lab |

## Reference

| Document | Purpose |
| --- | --- |
| [Compatibility](compatibility.md) | Pinned runtime contracts and primary references |
| [Identity token flow](token-flow-documented.md) | Delegated API authorization and UI interpretation |
| [Egress control](egress-control.md) | RAI network policy mechanics, TLS and limits |
| [Telemetry map](telemetry-map.md) | Observed schemas, joins and dated evidence |
| [KQL queries](kql-queries.md) | Evidence inspection queries |
| [Diagrams](diagrams/README.md) | Current Copilot OAuth/ACS flow, deployment lifecycle and historical baseline |

## Current baseline

The owner confirmed the existing Foundry egress and identity demo was tested on
2026-11-06. Dated baseline observations remain in the telemetry map; they are not
results for a later deployment.

On 2026-11-09 the real controlled APIs were deployed and healthy, and seven isolated
governance agents were active on one image digest, with three dedicated RAI policies
and verified model-access grants. No hosted governance comparison was invoked.
The Microsoft 365 Copilot ACS-first path was then observed working on version 3:
the external-processing prompt returned `governance_denied` and its Demo run marker
matched a real ACS `deny` / `blocked` event. See the
[dated observation and limits](telemetry-map.md#microsoft-365-copilot-blocked-action-observation).
Protected lookup and the full hosted comparison remain separate work.

The latest owner-authorized setup on 2026-11-09 deployed all seven agents as
active version `4` and updated the existing Copilot publication's pin to `4`.
Repeated deployment/publication reused those resources. Original policy and API
configuration were unchanged. No new hosted conversation or comparison was
invoked during that setup; use `task acs:status` for current resource identifiers
and sample prompts.

On 2026-11-10, a second owner-supplied Copilot reply correlated with an ACS
`deny` / `blocked` event on version `4`. The isolated OAuth extension's project
`normal-manatee-55075-copilot`, project capability host, protected MCP service,
dedicated policy and scoped grants were then provisioned. The repeat Terraform
plan reported no changes. Subsequent owner-approved troubleshooting verified the
real callback, securely bound a 30-day client credential, completed consent and
created toolbox `copilot-policy` v2. The generic unsupported-target metadata was
not an OAuth rejection: both private-endpoint status fields were `NotApplicable`.
One approved exact-host managed-network rule removed the TLS failure. The
consenting admin was then explicitly authorized on the isolated MCP only, retaining
the existing guest and leaving the baseline API unchanged. Discovery and one
synthetic policy lookup succeeded through v2. See the
[verified setup and remaining gates](governance-demo.md#8-operator-reference-isolated-toolbox-project).
`task copilot-toolbox:infra-up` now consolidates registration, infrastructure,
exact-host egress, OAuth credential/callback and immutable toolbox configuration.
It reused the working resources live; browser consent remains interactive.
Deployment reads endpoint/tool from the verified journal, not manual exports.
Later on 2026-11-10, the isolated hosted agent became active as version `1` and
**ACS OAuth Servicing Demo** was published separately, Shared / Just you, pinned
to `1`. Owner-run Copilot lookup and a combined lookup/ACS-blocked send were
correlated with actual toolbox outcomes, MCP receipts and ACS decisions. The
negative identity test was explicitly deferred; the original AKS/UI runtime
regression is pending. See the [dated acceptance evidence](telemetry-map.md#isolated-copilot-acceptance).
The original publication remains pinned to active version `4`; original RAI policies, API
authorization and images are unchanged. The owner separately enabled and approved
retaining selected-IP public access; it was not changed by the outbound-rule test.

## Operating rules

Use the repository's Task targets. The owner runs builds, deployments, hosted calls
and teardown. Preserve Terraform state and externally managed policy settings.
Do not run `cloud:up` to erase unrelated policy drift; `deploy:tool-apis` applies a
guarded plan limited to the two existing Container Apps.

Use synthetic data, verified TLS, bounded timeouts and disabled redirects. Never
capture prompts, responses, payloads, tokens or authorization headers in telemetry.
No arbitrary-URL tool, application hostname allowlist, conditional tool registration
or prompt-only refusal substitutes for the platform experiment.

Missing evidence is **inconclusive**, never a pass. Local execution is a functional
test, not containment proof. Network egress controls are preview and are not a
production assurance or compliance certification.
