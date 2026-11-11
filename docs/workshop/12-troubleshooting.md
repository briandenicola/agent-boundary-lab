# Module 12: Troubleshooting

Two rules first. A failed check isn't automatically a containment result; classify HTTP, TLS, DNS and timeout failures separately, and treat missing evidence as inconclusive. A failed Foundry agent version is never fixed in place; create a new version.

## Runtime and images

| Symptom | Cause and fix |
| --- | --- |
| `No usable temporary directory` in the harness pod | Read-only root filesystem. Mount an `emptyDir` at `/tmp`. |
| `No module named mcp` | LiteLLM imports it. Keep `mcp` and `mcp-types` pinned in the image and rebuild. |
| TLS timeout to GHCR during `az acr build` | The ACR build agent can't reach it. Use `Dockerfile.harness`, which pulls only from PyPI. |
| Facade JSON-RPC `-32603` | protobuf 7 or newer. Keep `protobuf<7`. |
| Agent version `failed` with `ImageError` | Registry pull role missing. Fix it, then create a new version. |
| 400 unsupported responses protocol version | Use protocol `2.0.0`. |
| Agent fails at its first model call | Missing model role for the agent identity. Run `task cloud:agent-access-plan`, then `cloud:agent-access-up`. |
| Tool 404 at policy-api or test-receiver | Stale image or wrong destination setting. Deploy the current image. |
| `403 Public access is disabled` | The Foundry data plane is private. Call it from inside the VNet, not a laptop. |
| Prompts or responses appear in telemetry | Content capture is on. Turn it off. |

## Ingress and sign-in

| Symptom | Cause and fix |
| --- | --- |
| 504 after 60 s during a chat turn | Default proxy timeout is shorter than a CPU-model turn. The harness ingress sets 300 s. |
| "Request Header Or Cookie Too Large" | The oauth2 ingress needs `proxy-buffer-size: 16k`. |
| `chat-agent:verify` expects 401 even with the token | Expected in `ingress_oidc` mode. Test through the HTTPS host. |
| Certificate not ready, challenge pending | The hostname doesn't resolve to the ingress IP, or port 80 is blocked. Compare `dig +short <fqdn>` with the `ingress-nginx-controller` external IP; fix the record. |
| Let's Encrypt rate limit | Too many failed validations. Fix DNS and wait. |
| Browser certificate warning | The certificate isn't issued yet. Wait for `READY=True` in `task chat-agent:external-status`. |
| AADSTS50011 redirect URI mismatch | The browser hostname differs from the `HOSTNAME` you passed. Re-run `chat-agent:external-app HOSTNAME=<fqdn>`. |
| `external-up` reports `harness-oidc-config` missing | Run `chat-agent:external-app` or `external-bootstrap`. |
| Load balancer backend unhealthy | Needs `externalTrafficPolicy=Local` and probe path `/healthz`. `chat-agent:external-prereqs` sets both. Don't edit the node resource group. |
| Saved login stops working | Secrets were rotated. Run `task chat-agent:token`. |
| Diagnostics links missing | Export the three `HARNESS_*_URL` variables and run `task chat-agent:secret`. |

## Identity

Details in [delegated identity](../token-flow-documented.md).

| Symptom | Meaning |
| --- | --- |
| `on-behalf-of exchange failed: <code>`, 401 | The exchange failed and the turn was refused. Look up the AADSTS code; consent is the usual cause. |
| `ingress_access_token_missing` | The ingress isn't forwarding `x-auth-request-access-token`. |
| `user_token_forwarded=false` | The tool didn't receive the user token. Not a policy decision. |
| 401 from the policy API | Authentication failed, not authorization. |
| 403 `user_not_authorized` | Valid token, user not on the allowed list. Expected for the unauthorized test user. |
| 403 `insufficient_scope` or `untrusted_oauth_client` | Check `policy.read` and `POLICY_API_CLIENT_IDS`. |

## Infrastructure

| Symptom | Cause and fix |
| --- | --- |
| `cloud:up` says the managed network must be imported | Run `task cloud:bootstrap` on a first environment, or `task cloud:network-import` after a partial apply. |
| Agent versions fail with `ProvisioningError`; publisher stuck in `creating` | The managed network can't pull from ACR. See [module 11](11-teardown-and-rebuild.md#what-changes-on-a-rebuild). |
| Endpoint image tag error | Run `task build:tool-apis`; it records the tag. Empty means placeholder images. |
| Namespace patch denied | `kubectl` identity differs from Terraform's. Add its object ID to `TF_VAR_aks_operator_object_ids`, apply, retry. |
| `tls: unrecognized name` | Stale kubeconfig. Run `task cloud:kubeconfig`. |
| `cloud:plan` shows RAI policies changing in place | Read the plan and don't apply it blindly. Never edit a production policy. |
| Foundry account stays `Creating` about 10 minutes | Managed network provisioning. Expected. |
| `verify_demo.py` exits 2 | Under 180 s since the call, wrong run ID or `--called-at`, or no App Insights connection. Inconclusive, not a failure. |
| No platform spans from the Enforced agent | That policy may also block its telemetry export. Treat as inconclusive and compare with KQL query 8. |

More: [deployment troubleshooting](../rebuild-runbook.md#troubleshooting), [compatibility](../compatibility.md).

**Back to:** [Workshop index](README.md)
