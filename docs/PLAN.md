# Remaining work

## Working today

| Area | Status |
| --- | --- |
| Foundry Audit/Enforced agents | Implemented; network comparison has recorded results |
| Browser user authorization | Implemented; allowed/denied access demonstrated |
| ACS pre-tool enforcement | Implemented; offline Rego and tamper checks passed |
| Seven governance scenarios | Deployed; full hosted comparison pending |
| Copilot blocked-send entry | Published as **ACS Servicing Demo**, v4 |
| Copilot OAuth entry | Published as **ACS OAuth Servicing Demo**, v1; lookup and combined lookup/blocked send demonstrated |

[Recorded evidence](telemetry-map.md) · [Deployment](rebuild-runbook.md)

## Next checks

- Test the Copilot OAuth entry with an unauthorized user. This test is deferred.
- Repeat the original AKS/UI flow after the Copilot extension.
- Run the seven-scenario hosted comparison and retain its reports.
- Replay a fresh deployment, credential renewal, and teardown. These paths have
  offline coverage but have not all been replayed live.

## Governance comparison

Each scenario uses the same governed image. The ACS mode/policy and Foundry
network policy determine the expected result.

| Scenario | ACS behavior | Network behavior | Required evidence |
| --- | --- | --- | --- |
| Governance denial | Deny and block | Both destinations allowed | ACS block, no send, successful receipt positive control |
| Network denial | Allow execution | Receiver denied | ACS allow, platform Deny, servicing receipt, receiver absence |
| Success | Allow execution | Both destinations allowed | Successful tools and matching receipts |
| Evaluation failure | Error and block | Both destinations allowed | Evaluator error, no execution, receipt positive control |
| Audit control | Deny but continue | Both destinations allowed | Audit decision and receiver receipt |
| Baseline Audit | Disabled | Receiver would-deny | Platform Audit decision and receiver receipt |
| Baseline Enforced | Disabled | Receiver denied | Platform Deny and receiver absence |

The [comparison procedure](demo-runbook.md#hosted-governance-comparison)
makes fourteen hosted calls. Missing evidence remains inconclusive.

## Deferred features

Dapr Workflow would run on AKS, invoke the existing Foundry agent from activities,
and use authenticated approvals, durable deadlines, and restart recovery.
It needs a persistent actor-compatible state store; PostgreSQL is a candidate
and is disabled by default. Azure Durable Task Scheduler is not a dependency.

Human approval resolution, ACS A2A authorization, APIM, Agent 365, messaging
bridges, and on-premises/OpenShift deployment are outside the current demo.

## Constraints

Keep both business tools registered, with destinations fixed at startup.
The Copilot extension uses separate agents, policies, configuration, and publication
without changing the original UI/OBO path. Projects in one Foundry account still
share managed networking and model capacity.

Keep identity, ACS, and network outcomes separate. No credentials, prompts, or
payloads belong in telemetry.
