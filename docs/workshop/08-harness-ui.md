# Module 08: The harness UI

The harness is the browser page you present from. It is a small Starlette service on AKS with a local CPU model and an ADK agent. Its two tools send one message each to the Audit and Enforced Foundry agents through the A2A bridge. The page shows the reply next to the raw tool results and run IDs.

The harness and its local model are not governed by the Foundry egress policy. Every response says `governed_by_foundry_policy: false`, and `determination` is a constant, never a containment verdict.

## What to know

- **Two tool sets.** The Foundry agent has `get_servicing_policy` and `send_to_external_processor` (the experiment). The harness has `ask_audit_agent` and `ask_enforced_agent` (the test driver). One failing never hides the other.
- **Why a local model.** The harness needs some LLM to drive tool calls without adding an Azure OpenAI dependency. A small CPU model is slow (tens of seconds per turn) and may skip a tool, so evidence comes from tool results and logs, never the model's text.
- **Websocket.** Browsers use `/ws`, which streams `accepted`, `progress` (every 5 s), then `result` or `error`. One turn runs at a time; a second gets 409.
- **Auth.** Presented use is Entra sign-in through the ingress (`ingress_oidc`). The shared-token mode is for development only.
- **Hardened pod.** Read-only root filesystem, no privilege escalation, no service account token, and a `/tmp` `emptyDir` as the only writable path. Without the `emptyDir`, Python cannot create temp files.

## Open it

Deploy it as part of the [deployment guide](../rebuild-runbook.md#2-build-and-deploy-the-applications), then browse to `https://<your-fqdn>` and sign in.

For development without Entra:

```bash
task chat-agent:open     # http://localhost:8082
task chat-agent:token    # password for the browser prompt
```

## Diagnostics links

To show Workbook, Log Analytics and App Insights links on the page:

```bash
HARNESS_WORKBOOK_URL=<url> HARNESS_LOGS_URL=<url> HARNESS_APPINSIGHTS_URL=<url> \
task chat-agent:secret
```

The task restarts the harness. Unset variables produce no link.

## Read the result

Each turn shows two separate cards:

| Card | Answers | Values |
| --- | --- | --- |
| Policy API access | Did this user's token reach the policy API? | allowed (200 with a verified user id), denied (403 `user_not_authorized`), not authenticated (401), no evidence |
| Egress / containment | Did the platform block the tool? | `inconclusive` until platform logs say otherwise |

An identity denial never changes the containment card. If the on-behalf-of exchange fails, the turn does not run and the UI shows `on-behalf-of exchange failed: <code>`. See [delegated identity](../token-flow-documented.md).

## Code

- Service: [`harness/chat.py`](../../src/containment_demo/harness/chat.py) (`build_view`, `/chat`, `/ws`)
- Settings: [`harness/settings.py`](../../src/containment_demo/harness/settings.py)
- Pod: [`deploy/kustomize/harness/deployment.yaml`](../../deploy/kustomize/harness/deployment.yaml)
- Local model: [`deploy/kustomize/local-model/`](../../deploy/kustomize/local-model/)

## Check yourself

1. Why does the response keep authorization status and `determination` separate?
2. What breaks if you drop the `/tmp` `emptyDir` but keep the read-only root?
3. Why is the harness outside the Foundry policy, and where is that recorded?

**Next:** [09 Run and verify](09-run-and-verify.md)
