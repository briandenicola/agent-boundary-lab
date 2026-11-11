# Documentation

## Deploy and demonstrate

| I want to… | Read |
| --- | --- |
| Stand up both demos in Azure | [Azure deployment guide](rebuild-runbook.md) |
| Show user authorization and network containment | [AKS/Foundry walkthrough](demo-runbook.md) |
| Show permitted lookup and ACS-blocked sending in Copilot | [Copilot walkthrough](governance-demo.md) |
| Learn the components step by step | [Workshop](workshop/README.md) |

## Understand and investigate

| Topic | Read |
| --- | --- |
| Components and request paths | [Architecture](architecture-as-built.md) |
| Browser and Copilot user authorization | [Identity flow](token-flow-documented.md) |
| Foundry network rules and their limits | [Egress control](egress-control.md) |
| Log tables, fields, and recorded results | [Telemetry](telemetry-map.md) |
| Queries to inspect a run | [KQL queries](kql-queries.md) |
| SDK pins and platform contracts | [Compatibility](compatibility.md) |
| Editable diagrams | [Diagrams](diagrams/README.md) |
| Outstanding tests and deferred features | [Plan](PLAN.md) |

## Three separate controls

**Identity** decides who may read the policy. **ACS** decides whether a proposed
tool may execute. **Foundry egress** controls the destination of an executing
tool's request. A result from one is not proof of another.

Use synthetic data and keep content/token capture disabled. Local tests check
functionality; hosted decisions and receipts establish containment.
