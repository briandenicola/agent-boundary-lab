# Module 12: Troubleshooting

**Duration:** reference; about 20 minutes to read

## Objectives

- Recognise the failures that actually occurred while building this environment.
- Apply the documented fix and know which file holds it.

## Concepts

Two rules before you debug:

1. A failed check is not necessarily a containment result. Classify HTTP / TLS / DNS / timeout failures separately, and treat missing evidence as **INCONCLUSIVE**.
2. A failed Foundry agent version is never healed in place; create a new version.

## Walkthrough: symptom, cause, fix

### Runtime and image issues

| Symptom | Cause | Fix | File |
| --- | --- | --- | --- |
| `No usable temporary directory` in the harness pod | The container runs with `readOnlyRootFilesystem: true`, so Python cannot create temp files | Mount an `emptyDir` volume at `/tmp` | [`deploy/kustomize/harness/deployment.yaml` L22-L24, L57-L58, L65](../../deploy/kustomize/harness/deployment.yaml#L22-L24) |
| `No module named mcp` (hosted agent or harness HTTP 500, LiteLLM import) | LiteLLM imports `mcp`, which was not installed | Pin `mcp==2.3.0` and `mcp-types==2.3.0`; keep the build-time import check. Rebuild and redeploy the image | [`Dockerfile.harness` L21-L26](../../Dockerfile.harness#L21-L26); [`../rebuild-runbook.md`](../rebuild-runbook.md) "Runtime/logging recovery" |
| TLS handshake timeout to GHCR during `az acr build` | The build step pulled from `ghcr.io`, which was unreachable from the ACR build agent | Use the pip-only `Dockerfile.harness` (base `python:3.12-slim`, packages from PyPI) | [`Dockerfile.harness`](../../Dockerfile.harness), [`tasks/Taskfile.harness.yml` L27-L40](../../tasks/Taskfile.harness.yml#L27-L40) |
| Facade JSON-RPC `-32603` | protobuf 7 or newer in the image | Cap `protobuf<7` | [`Dockerfile.harness` L26](../../Dockerfile.harness#L26); `../compatibility.md` B5e |
| Version `failed`, `ImageError` | Registry pull role missing for the account identity | Fix the role, then create a **new** version | `../compatibility.md` B9e |
| 400 "Unsupported responses protocol version" | Wrong protocol version | Use `2.0.0` | `../compatibility.md` B9d |
| Agent dies at its first model call (404 / 401) | Missing model RBAC for the agent identity, or wrong api-version | `task cloud:agent-access-plan`, then `task cloud:agent-access-up` | [`tasks/Taskfile.cloud.yml` L493-L505](../../tasks/Taskfile.cloud.yml#L493-L505) |

### Ingress and login issues (external harness)

| Symptom | Cause | Fix | File |
| --- | --- | --- | --- |
| Request fails with **504 at 60 s** during a chat turn | ingress-nginx default proxy timeout (60 s) is shorter than a CPU-model turn (about 2 minutes) | Proxy read/send timeouts of 300 s on the harness ingress | [`deploy/kustomize/harness-external/ingress-harness.yaml` L11-L13](../../deploy/kustomize/harness-external/ingress-harness.yaml#L11-L13) |
| oauth2 callback returns **"Request Header Or Cookie Too Large"** | Entra session cookie and headers exceed the default nginx buffer | `proxy-buffer-size: "16k"` on the oauth2 ingress | [`deploy/kustomize/harness-external/ingress-oauth2.yaml` L8](../../deploy/kustomize/harness-external/ingress-oauth2.yaml#L8) |
| `chat-agent:verify` expects 401 even with the token | `HARNESS_AUTH_MODE=ingress_oidc`; legacy token auth is off | Expected; test through the HTTPS host | [`../demo-runbook.md`](../demo-runbook.md) "External run" |
| Certificate stays `READY=False`; cert-manager challenge **pending** | Hostname does not resolve to the ingress public IP (stale `A` record after a rebuild, or not created), or TCP 80 blocked | `dig +short <fqdn>` must equal `kubectl -n ingress-nginx get svc ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].ip}'`; fix the record; `kubectl -n <ns> describe certificate harness-external-tls` | [Module 07](07-external-access.md) |
| Let's Encrypt **rate limit** errors after repeated failures | Many failed validations against the production issuer | Fix DNS first, wait out the limit; set `LETSENCRYPT_CLUSTER_ISSUER` only if you intend a different issuer | [`external-render` L247-L269](../../tasks/Taskfile.harness.yml#L247-L269) |
| Browser shows certificate warning (fake/default cert) | Certificate not issued yet; ingress-nginx serves its default cert | Wait for `READY=True` in `task chat-agent:external-status` | [Module 07](07-external-access.md) |
| Entra error **AADSTS50011** redirect URI mismatch | Hostname used in the browser differs from the one passed as `HOSTNAME` to `external-app` | Re-run `chat-agent:external-app HOSTNAME=<exact fqdn>` | [`tasks/Taskfile.harness.yml` L167-L230](../../tasks/Taskfile.harness.yml#L167-L230) |
| `external-up` says secret `harness-oidc-config` missing | `external-app` did not run | Run `chat-agent:external-app` (or `external-bootstrap`) | [`tasks/Taskfile.harness.yml` L282-L299](../../tasks/Taskfile.harness.yml#L282-L299) |
| Public LB backend unhealthy | nginx needs `externalTrafficPolicy=Local` and probe path `/healthz` | Applied by `task chat-agent:external-prereqs`; do not hand-edit the node resource group | [`tasks/Taskfile.harness.yml` L127-L165](../../tasks/Taskfile.harness.yml#L127-L165) |

### Issue #4 identity flow (never run live; every row is UNVERIFIED)

Codes below are general Entra knowledge, not observed in this repo. Full detail: [`../token-flow-documented.md`](../token-flow-documented.md).

| Symptom | Likely cause | Check |
| --- | --- | --- |
| UI: `on-behalf-of exchange failed: <code>`, 401 `source: identity` | OBO exchange failed (harness refuses the turn) | `AADSTS65001` consent missing; `AADSTS50013` / `AADSTS70011` invalid assertion or scope; `AADSTS500133` expired token. Mapping is UNVERIFIED |
| Local label `ingress_access_token_missing` | `x-auth-request-access-token` not forwarded | `--pass-access-token`, ingress `auth-response-headers`, header or cookie size (16k buffer set; behaviour UNVERIFIED) |
| `user_token_forwarded=false` | Header did not reach the tool (Foundry delivery UNVERIFIED, or ContextVar/session state not reaching the tool) | Tool-record field; do not read as a policy decision |
| 401 from the policy API | Token missing/invalid (`authentication_required`, `invalid_bearer`, `invalid_token`, `invalid_delegated_token`) | Authentication failed, not authorization |
| 403 `user_not_authorized` | Valid token, user not in `AUTHORIZED_USER_IDS` | Expected for `10870cbe-74ab-4c46-b5a8-8fcded26e615` |
| 403 `insufficient_scope` / `untrusted_oauth_client` | Scope or client app id not accepted | `policy.read`, `POLICY_API_CLIENT_IDS` |
| Allowed user never shows `allowed` | Known code defects: `outcome_from_record` drops `user_object_id` on 200; `HARNESS_OBO_*` not mapped into the harness pod; receipt query only matches denials | token-flow section 6 |

### Harness and monitoring

| Symptom | Cause | Fix | File |
| --- | --- | --- | --- |
| Diagnostics links missing in the harness UI | `HARNESS_WORKBOOK_URL`, `HARNESS_LOGS_URL`, `HARNESS_APPINSIGHTS_URL` never reached the Secret | Export them, run `task chat-agent:secret` (it restarts the harness) | [`tasks/Taskfile.harness.yml` L60-L91](../../tasks/Taskfile.harness.yml#L60-L91); [`settings.py` L58-L64](../../src/containment_demo/harness/settings.py#L58-L64) |
| Saved browser login stops working | Secrets were rotated or rebuilt | `task chat-agent:token` (or `test-ui:token`) | [`tasks/Taskfile.harness.yml`](../../tasks/Taskfile.harness.yml) |
| Tool 404 at policy-api / test-receiver | Double slash from a trailing-slash URL | Rebuild images from a commit that includes the fix | [`../demo-runbook.md`](../demo-runbook.md) section 6 |
| `403 Public access is disabled` | The Foundry data plane is private | Call only from inside the VNet (harness, facade, UI), never a laptop | `../compatibility.md` |
| Prompts or responses visible in telemetry | ADK content capture is on | Stop and turn it off; see [`../telemetry-map.md`](../telemetry-map.md) §0.10 | `src/containment_demo/telemetry.py` |
| `scripts/verify_demo.py` exits 2 (INCONCLUSIVE) | Under 180 s since the call, wrong run id, wrong `--called-at`, `--no-terraform`, or no App Insights connection | Wait, check `matched_run_ids`, use the tool-start time, run `task cloud:app-insights-connection`. Not a pass, not a failure | [`../demo-runbook.md`](../demo-runbook.md) |
| No platform spans from the enforced slot | The Enforced policy also denies the agent's App Insights export (not verified as the cause) | Treat as inconclusive; compare with the audit slot using KQL query 8 | [`../kql-queries.md`](../kql-queries.md) |

### Infrastructure and rebuild

| Symptom | Cause | Fix | File |
| --- | --- | --- | --- |
| `cloud:up` refuses: managed network must be imported | Azure creates `managednetworks/default` with the account and AzAPI will not create it again | `task cloud:bootstrap` on a first environment, `task cloud:network-import` for a partial apply | [`../rebuild-runbook.md`](../rebuild-runbook.md) "Recover the reported partial apply" |
| Agent versions fail with generic `ProvisioningError`, publisher times out in `creating` | The Foundry managed network had no ACR private endpoint or approval grants | Declared in `managed-network.tf`; for a manual repair run `task cloud:acr-network-import`, then restart the publisher pod | [`../rebuild-runbook.md`](../rebuild-runbook.md) "Recover the ACR managed-network gap"; [`managed-network.tf`](../../infra/cloud/managed-network.tf) |
| `cloud:up` or `deploy:tool-apis` stops on endpoint image tag | Image not in ACR, or tag unreadable | `task build:tool-apis` (records the tag and writes `ENDPOINT_IMAGE_TAG`). Empty means placeholder images | [`../rebuild-runbook.md`](../rebuild-runbook.md) |
| Namespace patch denied by AKS | kubectl identity differs from the Terraform caller; Azure Owner grants no Kubernetes data-plane access | Add the object id to `TF_VAR_aks_operator_object_ids` in `.env`, plan and apply, retry `deploy:all` | [`../rebuild-runbook.md`](../rebuild-runbook.md) section 3 |
| `Unable to connect to the server: remote error: tls: unrecognized name` | kubeconfig points at a dead cluster | `task cloud:kubeconfig` and compare the context name with Terraform output | [`../demo-runbook.md`](../demo-runbook.md) P0a to P0c |
| `chdir ./infra/cloud: no such file or directory` | Local path resolution in an old preflight | Update to a version that resolves `{{.ROOT_DIR}}/infra/cloud`; not evidence the environment needs bootstrapping | [`../rebuild-runbook.md`](../rebuild-runbook.md) |
| `cloud:plan` shows the RAI policies updating in place | Unexplained content filter drift (2026-10-10) | Read the plan; do not apply blind; never edit a production policy | [`../rebuild-runbook.md`](../rebuild-runbook.md) "Known rough edges" |
| Foundry spike account stays `Creating` about 10 minutes | Managed network provisioning | Expected; not a failure signal | [`../demo-runbook.md`](../demo-runbook.md) section 12 |
| `deploy:*` after model grant still fails | Propagation, restart or new version needed (UNVERIFIED) | Wait and retry; do not assume a grant proves a model call works | [`../rebuild-runbook.md`](../rebuild-runbook.md) section 6 |

## Code tour

| What | Where |
| --- | --- |
| All hosted-agent and platform observations | [`../compatibility.md`](../compatibility.md) (B-numbered findings) |
| Rebuild recoveries | [`../rebuild-runbook.md`](../rebuild-runbook.md) |
| Telemetry gaps | [`../telemetry-map.md`](../telemetry-map.md) §0.15 |
| Lint checks for task wiring and manifests | [`tasks/Taskfile.lint.yml`](../../tasks/Taskfile.lint.yml) (`task lint:tasks`, `lint:manifests`, `lint:cloud`) |

## Checkpoint

- [ ] You can name the first command you would run for each of: a 504, a cookie-too-large login, a missing diagnostics link, and a failed agent version.
- [ ] You know that a failed check is never automatically a containment result.

**Back to:** [Workshop index](README.md)
