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
| [Diagrams](diagrams/README.md) | Editable diagram sources |

## Current baseline

The owner confirmed the existing Foundry egress and identity demo was tested on
2026-11-06. Dated baseline observations remain in the telemetry map; they are not
results for a later deployment.

On 2026-11-09 the real controlled APIs were deployed and healthy, and seven isolated
governance agents were active on one image digest, with three dedicated RAI policies
and verified model-access grants. No hosted governance comparison was invoked.
Microsoft 365 Copilot integration is the active implementation track.

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
