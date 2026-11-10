# Diagrams

The diagrams map the environment; they are **not evidence**. ACS decisions,
delegated service authorization and platform egress decisions are independent.
Use [architecture](../architecture-as-built.md), [dated evidence](../telemetry-map.md)
and [queries](../kql-queries.md) for their actual contracts and results.

## Which diagram to use

| File | Use it for | Status |
| --- | --- | --- |
| [`copilot-oauth-flow.excalidraw`](copilot-oauth-flow.excalidraw) / [SVG preview](copilot-oauth-flow.svg) | Copilot Activity -> hosted ADK -> ACS -> immutable toolbox/OAuth -> protected MCP, with evidence and preserved-baseline boundaries | Current Copilot snapshot (2026-11-10): v1 agent, v2 toolbox |
| [`copilot-deployment-flow.excalidraw`](copilot-deployment-flow.excalidraw) / [SVG preview](copilot-deployment-flow.svg) | Existing-foundation owner lifecycle: build, consolidated infrastructure/consent, deploy, reviewed publication, status and recovery | Current Task workflow (2026-11-10); fresh rebuild/rotation/teardown are not live replay claims |
| [`environment.excalidraw`](environment.excalidraw) (source) and `environment.svg` (export) | October baseline: laptop, AKS, Foundry, Container Apps, evidence and ACR. Does not include ACS or Microsoft 365 integration. | Baseline snapshot (2026-10-09) |
| [`azure-environment.excalidraw`](azure-environment.excalidraw) / [`.svg`](azure-environment.svg) | Earlier Azure-resource-only view. Kept for history. | Superseded |

![Copilot delegated lookup and ACS flow](copilot-oauth-flow.svg)

![Consolidated Copilot deployment](copilot-deployment-flow.svg)

### Current Copilot legend

Green marks the permitted lookup or verified result; purple is a Foundry
component; blue is user identity or operator access. **Red means ACS application
blocking, not platform network enforcement.** Gray shows evidence, preserved
components or qualifications. Amber marks deferred checks/recovery cautions.
Dashed connectors carry evidence; the dashed enclosure identifies the separate
Foundry project/toolbox path, not a claim about a new platform Deny.

Authorized lookup and combined lookup/blocked sending have correlated evidence.
Negative identity acceptance was deferred, and the original AKS/UI runtime
regression is pending. The private AKS helper deploys/manages resources; **it never
relays chat**. The original seven v4 agents/publication remain separate.
Use the [canonical runbook](../rebuild-runbook.md#current-acs-and-copilot-lifecycle)
for executable steps.

## Edit and export

1. Open the desired `.excalidraw` source in VS Code with the *Excalidraw* extension
   (`pomdtr.excalidraw-editor`), or load it locally in [Excalidraw](https://excalidraw.com).
   Do not upload private configuration or create shared links containing it.
2. Edit. Copilot arrows are bound to shapes and box labels to their containers;
   arrow captions are separate text. Zoom to fit with Shift+1.
3. Export SVG under the matching basename in `docs/diagrams/`. **Embed scene**
   can be enabled for future exports; the current Copilot SVGs are generated
   previews, so open their `.excalidraw` files for the editable scene.
4. Commit the `.excalidraw` source and the `.svg` together. The source is authoritative; never edit the SVG by hand.

## Reading the October baseline

![Historical baseline environment](environment.svg)

The legend and F1-F11 flows below apply only to `environment.*`, not the current
Copilot diagrams above.

- **Zones** are the boxes: operator laptop, AKS namespace `agent-boundary-lab`, Foundry account and project, Container Apps
  (the two controlled endpoints), the evidence plane and ACR.
- **Arrows** carry a number `F1` to `F11`. The table below says what each one is and how sure we are.
- **Colour and line style** (below) tell you what is observed, what is not governed by the policy, and what is only proposed.

### Colour and line legend

| Style | Meaning |
| --- | --- |
| Green, solid | Observed / verified (dated evidence in `telemetry-map.md`, `compatibility.md`) |
| Blue, solid | AKS stand-in caller. **Not governed** by the Foundry policy. |
| Purple, solid | Foundry component (deployed, observed) |
| Teal, solid | Controlled endpoint (our code, Container Apps) |
| Orange, **dashed** | PROPOSED / UNVERIFIED (evidence workbook, Entra Agent ID, app-span link, F9) |
| Red | Blocked, denied or disabled by the platform (native A2A, enforced Deny) |

## The flows

| Flow | From to | What happens | Status |
| --- | --- | --- | --- |
| F1 | Browser to harness | `kubectl port-forward` to the chat service (`task chat-agent:open`, local port 8082) | Verified |
| F2 | Harness to local model | OpenAI-compatible `/v1` call with tool calling to llama.cpp serving Qwen2.5-3B (CPU) | Verified |
| F3 | Harness tool to façade | One A2A `SendMessage` (bearer token, `A2A-Version: 1.0`) to the audit or the enforced façade | Verified |
| F4 | Façade to hosted agent | Foundry Responses call by agent name, Entra token, `store=False`. The AKS to private-account network path is **assumed** | Calls verified; path assumed |
| F5 | Hosted agent to policy-api | `get_servicing_policy`: host is on the allow list. Platform decision `Allow` and a receipt | Verified |
| F6 | Hosted agent to test-receiver | `send_to_external_processor`: host is **not** on the allow list. Audit: `AuditWouldDeny`, the call reaches it, receipt. Enforced: `Deny`, no receipt | Verified (small n) |
| F7 | Platform to App Insights | The platform writes one `NetworkEgressDecision` row per outbound call (`AppDependencies`) | Verified |
| F8 | Container Apps to Log Analytics | Receipts from policy-api and test-receiver (`ContainerAppConsoleLogs_CL`) | Verified |
| F9 | Hosted agent to App Insights | The agent's own telemetry export. Enforced: `Deny` / `DefaultDeny` (observed). That this is why enforced app spans never land is **not verified** | Observed; link unverified |
| F10 | Operator to evidence | `verify_demo.py` B and C, the KQL queries and the proposed workbook read the rows by `run-…` id | Script verified; workbook proposed |
| F11 | Builds | `task *:build` to ACR, then AKS pulls images and Foundry pulls the agent image | Verified |

Two things the arrows do not mean:

- **The harness, the model and the façades are not governed by the Foundry policy.** Only the hosted agents' outbound calls are.
- **The `run-…` id is the only join.** It travels in the URL path of the tool call. The `ui-…` and harness ids do not link to it.

## Verified vs proposed vs assumed

- **Verified baseline:** F1 to F3, F5 to F8 and F10 (`verify_demo.py`), and the run-id join. See [dated evidence](../telemetry-map.md#dated-baseline-results) (small n). The
  same image digest on both agents and the policy attachment were read back by the deployer.
- **Assumed:** the network path of F4. Calls succeed, but how the managed VNet and the egress policy layer is an open documentation gap
  (`compatibility.md` D). The model deployment name and the `foundry-account-pe` rule come from `infra/cloud` and B9g.
- **Snapshot limits:** dashed styles reflect the October drawing, not current
  rollout status. The identity baseline was subsequently tested. Use
  [architecture](../architecture-as-built.md) for current boundaries.
- **Blocked:** native inbound A2A on hosted agents (`HOSTED_AGENT_NOT_SUPPORTED`). The façades exist because of this.

Digests and version numbers drift. Re-read them with the `*:digest` tasks rather than trusting the diagram.
