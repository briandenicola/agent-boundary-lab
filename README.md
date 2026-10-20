# Agent Boundary Lab

A reproducible demonstration that **outbound network containment for an AI agent is enforced by the platform, not by the application**.

A Google ADK agent runs as a Microsoft Foundry hosted agent with exactly two business tools. One calls an allowlisted host; the other calls a host deliberately left off the allowlist. The same container image digest is deployed twice, attached to an **Audit** and an **Enforced** account-level network policy. The policy is the only variable.

## The claim

| Call | Audit agent | Enforced agent |
| --- | --- | --- |
| `get_servicing_policy` (allowlisted host) | allowed | allowed |
| `send_to_external_processor` (host not on the allowlist) | reaches the receiver; platform records `AuditWouldDeny` | **denied by the platform**; no receipt at the receiver |

The proof is not the agent's own 403, a DNS error, a timeout or the model's prose. It is the platform's egress decision row joined with the receipt log (or its absence) on a shared `run-...` id. If that join is missing, the result is **INCONCLUSIVE**, never a pass.

![Three layers](docs/workshop/diagrams/01-three-layers.svg)

The three independently observable layers are the agent, the policy, and the evidence (application traces, platform egress decisions and receipt logs). A browser harness with Entra login drives the demo and separates **identity authorization**, **policy API authorization** and **containment evidence** as three outcomes that are never merged.

## Status and honesty

Some results are TESTED (n is small, dated in [`docs/telemetry-map.md`](docs/telemetry-map.md)); a complete clean rebuild of the corrected configuration is **not yet verified end to end** ([`docs/rebuild-runbook.md`](docs/rebuild-runbook.md)); the allowed-vs-denied live demo is partly proposed ([`docs/demo-runbook.md`](docs/demo-runbook.md)). Local runs are functional tests, not containment proof. All data is synthetic.

## Quick start

Prerequisites: Azure subscription with owner-approved permissions, `az`, `terraform`, `kubectl`, `kubelogin`, `jq` and [Task](https://taskfile.dev). Details in [Module 02](docs/workshop/02-prerequisites.md). Settings go in an untracked `.env`.

```bash
task --list                 # every available task
task lint:test              # offline unit suite; no Azure, no credentials
task cloud:whoami           # confirm subscription and tenant
task cloud:plan             # read what would be created
task cloud:bootstrap        # BILLABLE: first environment only
task cloud:up               # BILLABLE: includes an AKS cluster
task cloud:kubeconfig
task build:all              # builds in ACR; no local Docker
task deploy:all             # tool APIs, both agent versions, harness
task chat-agent:token       # harness login password
task chat-agent:open        # http://localhost:8082
```

Wait at least 3 minutes after a run, then verify:

```bash
.venv/bin/python scripts/verify_demo.py --section b --audit-run-id <run-...> --audit-called-at <UTC ISO>
.venv/bin/python scripts/verify_demo.py --section c --enforced-run-id <run-...> --enforced-called-at <UTC ISO>
```

Exit code 0 is PASS, 1 FAIL, 2 INCONCLUSIVE. Creating billable resources, changing policies and publishing images need owner approval. Tear down with `task identity:destroy`, then `task cloud:down` ([Module 10](docs/workshop/10-teardown-and-rebuild.md)).

## Workshop

A guided, eleven-module lab for engineers new to Azure and Foundry: [docs/workshop/README.md](docs/workshop/README.md). The full contents are in [toc.md](toc.md).

## Reference documents

| Document | Purpose |
| --- | --- |
| [docs/architecture-as-built.md](docs/architecture-as-built.md) | What is deployed and observed today |
| [docs/compatibility.md](docs/compatibility.md) | Pinned versions and platform findings |
| [docs/telemetry-map.md](docs/telemetry-map.md) | Real field names and tables found during validation |
| [docs/egress-control.md](docs/egress-control.md) | How the network policy works |
| [docs/identity-probe.md](docs/identity-probe.md) | Entra identity checks for allowed and denied users |
| [docs/demo-runbook.md](docs/demo-runbook.md) | Presenter and operator procedure |
| [docs/rebuild-runbook.md](docs/rebuild-runbook.md) | End-to-end rebuild and recoveries |
| [docs/kql-queries.md](docs/kql-queries.md) | Evidence queries |
| [docs/README.md](docs/README.md), [docs/PLAN.md](docs/PLAN.md) | Original scope and phased plan |

## License

See [LICENSE](LICENSE).
