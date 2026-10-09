# Demo UI (issue #1), checkpoint 1: code and tests only

- `src/containment_demo/demo_ui.py`: Starlette app. Buttons run slot `audit` or `enforced`; the slot maps to a configured agent name. Only invocation path is `invoke.invoke_agent`.
- Determination is always `invoke.DETERMINATION` (never read from the record). No pass path. Platform evidence panel says "not joined (GATE 0)" until a telemetry field joins to `demo_run_id`.
- Auth: token as Bearer or Basic password, constant-time compare; POST also needs `X-Demo-UI: 1` (CSRF). `/healthz` open. Nothing sensitive logged or rendered; DOM written via textContent only.
- Our own transport failure is rendered as "OUR CALL failed ... says nothing about egress"; tool failures show HTTP/TLS/DNS/timeout kind.
- `deploy/kustomize/demo-ui/` (new): ClusterIP only, no ingress, REPLACE_WITH_* placeholders. NOT yet substituted by any task and NOT covered by `lint:manifests`.
- Deferred/not done: platform-evidence rows, digest read-back (`read_version_facts`) display, side-by-side comparison beyond two columns.
- Needs Brian: a UI image (new `demo-ui` extra; not the agent image, its digest is the control), a Terraform identity + Foundry Agent Consumer grant + federated credential for SA `demo-ui`, a UI token secret, and a Taskfile substitution task.
