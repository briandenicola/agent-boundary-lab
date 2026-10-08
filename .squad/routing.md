# Work Routing

How to decide who handles what.

## Routing Table

| Work Type | Route To | Examples |
|-----------|----------|----------|
| Terraform, AKS, Kubernetes YAML, Azure resources | Parker | `infra/`, Jobs, init containers, workload identity, Container Apps, RAI policy resources, Taskfile targets |
| Python, ADK, SDK, container contract | Brett | `src/containment_demo/`, agent + tools, protocol adapter, SDK-based agent deployment, Dockerfile, Dapr workflow app |
| Tests, verification harness, result classification | Dallas | `tests/`, `scripts/verify_demo.py`, pass/fail/inconclusive rules, baseline establishment |
| Telemetry, KQL, evidence fields, correlation | Lambert | App Insights queries, `docs/telemetry-map.md`, `telemetry.py`, monitoring RBAC |
| Scope, experiment design, review | Ripley | PLAN.md phase gating, "is this claim supported", arbitration, reviewer gate |
| Session logging | Scribe | Automatic - never needs routing |

## Reviewer Gate

**Ripley is the reviewer** for anything that produces or interprets evidence, or that
touches the experimental control (the attached RAI policy being the only variable).

**Dallas is the reviewer** for anything claiming a test result.

On rejection the original author is locked out of the revision. A different agent must
produce the next version. The Coordinator enforces this mechanically.

## Issue Routing

| Label | Action | Who |
|-------|--------|-----|
| `squad` | Triage: analyze issue, assign `squad:{member}` label | Ripley |
| `squad:{name}` | Pick up issue and complete the work | Named member |

## Rules

1. **Eager by default** - spawn all agents who could usefully start work, including
   anticipatory downstream work.
2. **Scribe always runs** after substantial work, always `mode: "background"`.
3. **Quick facts, the coordinator answers directly.** Do not spawn for "which region are we in".
4. **No agent applies Terraform, creates billable resources, or publishes an image.**
   They produce the artifact; Brian runs the command.
5. **Nothing that ships uses the `az` CLI.** Terraform or SDK only.
6. **Ask rather than assume.** If a requirement is ambiguous, surface the question to
   Brian instead of picking a plausible default.
