A2A façade (issue #3 follow-up). Hosted agents are invoked through Responses; this server
exposes them as A2A. It is NOT the platform's native A2A endpoint (unsupported for hosted
agents, docs/compatibility.md B5d) and it is not policy-governed.

* `base/`      one Deployment and one ClusterIP Service, no target set.
* `audit/`     name suffix `-audit`, targets the audit agent.
* `enforced/`  name suffix `-enforced`, targets the enforced agent.

The two overlays differ only by the target env and the names that follow from it. The
image is the same digest in both (`REPLACE_WITH_A2A_FACADE_IMAGE`, pinned by the task).

The Secret `a2a-facade-config` (key `DEMO_A2A_TOKEN`) is deliberately NOT here:
`task a2a:secret` creates it so the token never exists in a manifest or in git.

Identity: pods run as the existing `demo-ui` ServiceAccount (workload identity, Foundry
Agent Consumer), which `task ui:up` creates. No new identity or role is added here.
Render with `task a2a:render`; the placeholders are substituted at render time.
