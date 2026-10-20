# Workshop: Prove Network Containment Is Enforced by the Platform

A hands-on lab series for the Agent Boundary Lab. You deploy a Google ADK agent as a Microsoft Foundry hosted agent, attach two otherwise identical network policies (Audit and Enforced), and collect evidence that the **platform**, not your code, blocked an outbound call.

## Audience and level

- Technical readers (level 300/400) who build AI applications and know Python, containers and Kubernetes basics.
- No deep Azure or Foundry experience is assumed. Each module explains the Azure concepts it uses.
- Synthetic data only. No customer records or real credentials are used anywhere.

## Duration

About 9 to 11 hours of lab time, plus unattended waits for Azure provisioning. Suggested split: day 1 modules 01 to 05, day 2 modules 06 to 11. Billable resources (an AKS cluster, a Foundry account with a managed network) are created in modules 03 and 06; the owner approves them first.

## Modules

| # | Module | Summary |
| --- | --- | --- |
| 01 | [Architecture](01-architecture.md) | The three layers (agent, policy, evidence) and the claim being proved |
| 02 | [Prerequisites](02-prerequisites.md) | Tools, Azure access, `.env`, and the Task runner |
| 03 | [Infrastructure](03-infrastructure.md) | Terraform for Foundry, the managed network, AKS, ACR, monitoring |
| 04 | [Identity](04-identity.md) | Entra test users, the OIDC identity flow and the allowed/denied actors |
| 05 | [Agent and tools](05-agent-and-tools.md) | The ADK agent and its exactly two business tools |
| 06 | [Build and deploy](06-build-and-deploy.md) | Images built in ACR, same-digest agent versions, application rollout |
| 07 | [External access: domain, DNS, TLS and Entra login](07-external-access.md) | Public hostname, DNS A record, ingress-nginx, Let's Encrypt, Entra OIDC |
| 08 | [Harness UI](08-harness-ui.md) | The chat harness, local model, A2A facades and external Entra login |
| 09 | [Run and verify](09-run-and-verify.md) | Allowed vs denied user, Audit vs Enforced, `verify_demo.py` |
| 10 | [Monitoring](10-monitoring.md) | KQL, Log Analytics, Application Insights, the workbook |
| 11 | [Teardown and rebuild](11-teardown-and-rebuild.md) | Safe deletion and a from-scratch rebuild |
| 12 | [Troubleshooting](12-troubleshooting.md) | Symptom, cause, fix for real failures |

![Three layers](diagrams/01-three-layers.svg)

## Learning outcomes

After the workshop you can:

1. Explain why an application-level 403, DNS error, timeout or model refusal is not proof of containment.
2. Deploy one image digest to two Foundry hosted-agent versions that differ only by RAI network policy.
3. Operate the Taskfile-driven build, deploy, identity and teardown flows.
4. Join a platform egress decision to a destination receipt by run id with KQL.
5. Run the verifier and report PASS, FAIL or **INCONCLUSIVE** honestly, labelling local and hosted runs separately.
6. Diagnose the common failures of this stack.

## Conventions

- Commands run from the repository root with [Task](https://taskfile.dev) (`task <name>`). Task names come from `Taskfile.yml` and `tasks/*.yml`; run `task --list` to see them.
- Each module has: Objectives, Concepts, Walkthrough, Code tour, Checkpoint, Next.
- Existing reference docs live in `docs/` and are linked with `../` paths.
- Task descriptions start with a risk label such as `BUILDS IN AZURE`, `CHANGES THE CLUSTER`, `CREATES BILLABLE RESOURCES`, `DELETES`. Read it before you run the task.
- Labels used in the reference docs: **TESTED** (observed, with a date), **PROPOSED** (designed, not shown), **BLOCKED**, **UNVERIFIED**, **INCONCLUSIVE** (missing evidence, never a pass).
- Local runs are functional tests, not containment proof.
- Secrets are created by `*:secret` tasks and never printed or committed. Use `.env` (untracked) for settings; the repository ships placeholders only.

## Reference docs

[Architecture as built](../architecture-as-built.md) · [Compatibility](../compatibility.md) · [Telemetry map](../telemetry-map.md) · [Egress control](../egress-control.md) · [Identity probe](../identity-probe.md) · [Demo runbook](../demo-runbook.md) · [Rebuild runbook](../rebuild-runbook.md) · [KQL queries](../kql-queries.md)

**Start here:** [Module 01: Architecture](01-architecture.md)
