# Module 08 — The Harness UI

The **harness** is the browser-facing piece you will actually drive during a demo. It is a small Starlette service on AKS that runs a *local* model with an ADK agent, whose two tools call the Audit and Enforced Foundry agents through the A2A facades (Module 05). The page shows the model's reply next to the raw tool results and run IDs, and links to the evidence. This module covers its API, its websocket protocol, its hardening and the CPU model it uses.

> **Labels.** The harness and its local model are **not governed by the Foundry egress policy**; the module docstring says so and every response carries `governed_by_foundry_policy: false` and the `determination` field is a constant, never a containment verdict. Websocket/HTTP behaviour below is covered by the unit suite (**TESTED** offline); hosted behaviour is **OWNER-REPORTED**.

## Objectives

1. Explain the harness's role and why it is a separate image and process from the Foundry agent.
2. Speak the `/ws` protocol (`accepted`, `progress`, `result`, `error`) and the `/chat` fallback.
3. Explain the auth modes (`legacy` token vs `ingress_oidc`), and what logout and the actor alias do.
4. Explain why the pod runs with `readOnlyRootFilesystem` plus a `/tmp` `emptyDir`.
5. Wire the Diagnostics chips with `HARNESS_WORKBOOK_URL`, `HARNESS_LOGS_URL`, `HARNESS_APPINSIGHTS_URL`.
6. Deploy and use the in-cluster local model.

## Concepts

| Term | Meaning |
|---|---|
| **Starlette / ASGI** | The lightweight Python web framework (and interface) the harness uses; `uvicorn` serves it on port 8080. |
| **Websocket** | A long-lived duplex connection. Model turns take tens of seconds on CPU, so the server streams status instead of leaving the browser waiting. |
| **ClusterIP** | A Service reachable only inside the cluster. The harness is never exposed directly; you use `port-forward` or the authenticated ingress. |
| **emptyDir** | A pod-scoped scratch volume, deleted with the pod. |
| **llama.cpp / GGUF** | A CPU inference server and model format. The lab bakes a small Qwen model into an image so no outside model API is needed. |

### The two tool sets are different

| Where | Tools | Purpose |
|---|---|---|
| Foundry hosted agent (Module 05) | `get_servicing_policy`, `send_to_external_processor` | The experiment: egress allowed vs denied. |
| Harness agent ([harness/agent.py](../../src/containment_demo/harness/agent.py)) | `ask_audit_agent`, `ask_enforced_agent` | Test driver: each sends one A2A message to a facade and returns the result as data; a failure in one cannot suppress the other. |

The harness never chooses a destination: facade URLs come from validated startup settings.

## Walkthrough

### 1. Prerequisites in order

```bash
task deploy:model-server     # local model (billable; large image)
task deploy:agent-bridge     # facades + their Secret
task deploy:chat-agent       # harness Secret + harness
```

Dry-run versions: `task model-server:plan`, `task chat-agent:render`, `task chat-agent:plan`. `chat-agent:up` refuses to proceed if the `harness-config`, `local-model` Service or `a2a-facade-config` Secret is missing.

### 2. Reach the UI

**Primary path: the external HTTPS URL.** Build it in [Module 07](07-external-access.md) (domain, DNS, certificate, Entra login), then browse to `https://<your-fqdn>`. This is how the demo is presented.

**Fallback for development only: port-forward.** It bypasses Entra and uses a shared token:

```bash
task chat-agent:open     # port-forward on http://localhost:8082 (Ctrl-C to stop)
task chat-agent:token    # password for the browser prompt (any user name)
task chat-agent:verify   # expect 401 without the token and 200 with it
```

Over the external Entra ingress (Module 07) you instead sign in with Entra; in that mode `chat-agent:verify` expects the token-bearing request to be refused too, because only ingress identity headers are accepted.

### 3. Optional diagnostics links

```bash
HARNESS_WORKBOOK_URL=<workbook-url> \
HARNESS_LOGS_URL=<log-analytics-url> \
HARNESS_APPINSIGHTS_URL=<app-insights-url> \
task chat-agent:secret
```

The task restarts the Deployment. Reload the page: **Evidence workbook**, **Log Analytics** and **App Insights** chips appear under a *Diagnostics* card, each opening in a new tab with `rel="noopener noreferrer"`. Unset variables produce no chip.

### 4. Talk to it from a script

Browser clients use the websocket; for scripting use `/chat` with the token (the `X-Demo-UI: 1` header is mandatory as a CSRF guard):

```bash
TOKEN=$(task chat-agent:token)
curl -s -u "u:${TOKEN}" -H 'X-Demo-UI: 1' -H 'Content-Type: application/json' \
  -d '{"message":"Run the test."}' http://localhost:8082/chat
```

Expected shape (abridged; synthetic data only):

```json
{
  "turn_id": "turn-ab12cd34ef56",
  "run_label": "hosted",
  "model": "local-model",
  "reply": "...",
  "tool_results": [ ... ],
  "tool_run_ids": ["run-..."],
  "actor_alias": "unspecified-actor",
  "policy_authorization_status": "...",
  "determination": "inconclusive-without-platform-evidence",
  "governed_by_foundry_policy": false
}
```

(`determination` comes from `invoke.DETERMINATION`; the harness never reports a pass.)

### 5. Use the model and flow pages

Open `/` to chat and `/flow` for a diagram of the hop-by-hop flow. In `ingress_oidc` mode both pages show a **Logout** chip pointing at `/oauth2/sign_out?rd=%2F`.

## Code tour

### The service — [src/containment_demo/harness/chat.py](../../src/containment_demo/harness/chat.py)

| Lines | What |
|---|---|
| [1–10](../../src/containment_demo/harness/chat.py#L1-L10) | Design note: one **stateless** turn per request, fresh ADK session each time, no memory to leak between turns. |
| [39](../../src/containment_demo/harness/chat.py#L39) | `MAX_MESSAGE_CHARS = 1000`. |
| [97–122](../../src/containment_demo/harness/chat.py#L97-L122) | `_ingress_actor_alias*`: sanitize `x-auth-request-*` headers into a display-only alias. |
| [125–138](../../src/containment_demo/harness/chat.py#L125-L138) | `_is_authorised_headers`: legacy shared token via `Basic` or `Bearer`, constant-time `hmac.compare_digest`. |
| [141–175](../../src/containment_demo/harness/chat.py#L141-L175) | `build_view`: the response record. Authorization status and containment `determination` are kept as **separate** fields so an identity denial can never read as containment. |
| [178–196](../../src/containment_demo/harness/chat.py#L178-L196) | Logout chip and the diagnostics card built from the three settings. |
| [198–231](../../src/containment_demo/harness/chat.py#L198-L231) | `/` and `/flow` handlers; logout chip shown only in ingress mode. |
| [233–283](../../src/containment_demo/harness/chat.py#L233-L283) | `/chat`: 400 bad input, 403 missing CSRF header, 409 if a turn is already running, 504 timeout, 502 model/tool failure. |
| [285–419](../../src/containment_demo/harness/chat.py#L285-L419) | `/ws`: websocket protocol, below. |
| [421–432](../../src/containment_demo/harness/chat.py#L421-L432) | Routes: `/`, `/flow`, `POST /chat`, `/ws`, `/healthz`. |

### The `/ws` protocol

Auth happens *before* `accept()`; failing it closes with code **1008** ([lines 285–297](../../src/containment_demo/harness/chat.py#L285-L297)). Then the client sends JSON `{"message": "..."}` and the server emits:

| Event | When | Key fields |
|---|---|---|
| `accepted` | Message validated ([line 360](../../src/containment_demo/harness/chat.py#L360)) | `turn_id` |
| `progress` | Every 5 s while the turn runs ([365–388](../../src/containment_demo/harness/chat.py#L365-L388)) | `turn_id`, `elapsed_seconds` |
| `result` | Turn finished ([413–419](../../src/containment_demo/harness/chat.py#L413-L419)) | `turn_id`, `data` = the `build_view` record |
| `error` | Bad request (400), turn already running (409), timeout (504, `source: harness`), model/tool failure (502, `source: harness/model`) | `status`, `source`, `error`, usually `turn_id` |

A single `asyncio.Lock` serializes turns: the lab is single-user and the CPU model is slow, so concurrent turns are rejected with 409 instead of queued. The error text passes through `invoke.sanitize`, so raw exception text and secrets are not echoed.

The browser side is in [page.py](../../src/containment_demo/harness/page.py): `wsUrl()` picks `ws`/`wss` from the page protocol ([line 125](../../src/containment_demo/harness/page.py#L125)) and opens the socket at [line 162](../../src/containment_demo/harness/page.py#L162); the flow page is `FLOW_PAGE` ([line 223](../../src/containment_demo/harness/page.py#L223)).

### Settings — [src/containment_demo/harness/settings.py](../../src/containment_demo/harness/settings.py)

| Lines | Setting |
|---|---|
| [22–29](../../src/containment_demo/harness/settings.py#L22-L29) | `HARNESS_AUTH_MODE`: `legacy` (shared token) or `ingress_oidc`. |
| [30–37](../../src/containment_demo/harness/settings.py#L30-L37) | `LOCAL_MODEL_BASE_URL`, `LOCAL_MODEL_NAME`, placeholder API key (llama.cpp ignores it). |
| [38–47](../../src/containment_demo/harness/settings.py#L38-L47) | Bounded timeouts: model 180 s, tool 150 s, turn 600 s, all capped; no retries. |
| [49–55](../../src/containment_demo/harness/settings.py#L49-L55) | Facade URLs, token and agent names for the `audit` and `enforced` slots. |
| [56–57](../../src/containment_demo/harness/settings.py#L56-L57) | `HARNESS_UI_TOKEN` and `DEMO_RUN_LABEL` (`hosted` or `local`: how runs are labelled honestly). |
| [58–64](../../src/containment_demo/harness/settings.py#L58-L64) | `HARNESS_WORKBOOK_URL`, `HARNESS_LOGS_URL`, `HARNESS_APPINSIGHTS_URL`. |
| [71–76](../../src/containment_demo/harness/settings.py#L71-L76) | Tokens must be at least 16 characters. |

### Hardened pod — [deploy/kustomize/harness/deployment.yaml](../../deploy/kustomize/harness/deployment.yaml)

* `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`, drop `ALL` capabilities, `runAsNonRoot`, no ServiceAccount token ([lines 19–24, 63–67](../../deploy/kustomize/harness/deployment.yaml#L19-L24)).
* A read-only root filesystem breaks anything that writes scratch files (Python temp files, library caches). The `tmp` `emptyDir` mounted at `/tmp` ([lines 22–24, 56–58](../../deploy/kustomize/harness/deployment.yaml#L22-L24)) gives it the one writable place it needs, wiped on restart, so a compromised process cannot persist files elsewhere.
* Secrets arrive through `envFrom: secretRef: harness-config`, which is where the diagnostics URLs land.
* Readiness probe is `GET /healthz`, which is intentionally unauthenticated.

### The local model path — [deploy/kustomize/local-model/](../../deploy/kustomize/local-model/)

* [deployment.yaml](../../deploy/kustomize/local-model/deployment.yaml): one replica, `Recreate` strategy, same hardening plus a `/tmp` `emptyDir`; requests 2 CPU / 4 Gi; `LLAMA_THREADS` set to the CPU request; readiness `/health` with a generous failure threshold because the model loads slowly.
* [service.yaml](../../deploy/kustomize/local-model/service.yaml): ClusterIP on port 80 → the harness reaches it at `http://local-model.<namespace>.svc.cluster.local/v1`.
* [Dockerfile.local-model](../../Dockerfile.local-model): llama.cpp base image and GGUF pinned by digest/SHA-256; the build fails closed if any pin is empty.

Commands: `task model-server:build`, `task model-server:digest`, `task model-server:render`, `task model-server:plan`, `task model-server:up`, `task model-server:status`.

Why a local model? The harness needs *some* LLM to drive tool calls, but it must not add an Azure OpenAI dependency that could muddy the experiment. A 3B CPU model is slow (40–70 s per turn per the settings comment), which is exactly why the websocket and progress events exist. It is also why model quality is a limitation: a small model may skip a tool, so the harness's evidence comes from tool results and platform logs, not from the model's text.

Deeper reading: [architecture-as-built.md](../architecture-as-built.md), [identity-probe.md](../identity-probe.md), [egress-control.md](../egress-control.md), [compatibility.md](../compatibility.md).

## Checkpoint questions

1. Which `/ws` event tells the client the turn is still running, and how often is it sent?
2. Why does the `/chat` endpoint require `X-Demo-UI: 1`?
3. Why does the response keep `policy_authorization_status` and `determination` as separate fields?
4. What breaks if you remove the `/tmp` `emptyDir` but keep `readOnlyRootFilesystem: true`?
5. Which three environment variables create Diagnostics chips, and which task applies them?
6. Why is it important that the harness is *not* governed by the Foundry policy, and which response field records it?

## Next

Continue to [08 — Run and Verify](09-run-and-verify.md).
