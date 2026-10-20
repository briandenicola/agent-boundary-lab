# Issue #4 token flow: user -> harness -> facade -> Foundry agent -> policy API

**Revised 2026-10-20 by Ripley from the code, replacing an earlier draft that overstated its claims.**
**Nothing in this flow has been run live.** No Entra app was created, nothing was deployed, no token was decoded,
no Foundry header delivery was observed.

Labels used on every claim below:

- **VERIFIED**: ran / observed. Only one fact is VERIFIED here: the unit suite passed (953 passed, 5 skipped; mocks
  only; run by the coordinator).
- **SOURCE-VERIFIED**: read in this repo's code or in a primary document. Not run against the real service.
- **UNVERIFIED**: not read or not run. Treat as unknown.

Identity result and network result are different things. A policy API 200/403 says who the user is allowed to be; it
says nothing about egress containment. Containment stays **inconclusive** without platform evidence.

## 1. The path

```text
browser
  -> ingress-nginx -> oauth2-proxy (Entra app A = middle tier, scope api://<A>/access_as_user)
       sets x-auth-request-access-token (access token for app A)
  -> harness (chat.py / obo.py): MSAL acquire_token_on_behalf_of -> OBO token for app B
       app B = 'agent-boundary-policy-api', scope policy.read
  -> A2A facade: header X-Delegated-Policy-Token        (in-cluster PLAIN HTTP, no TLS on this hop)
  -> Foundry Responses API: extra_headers x-client-policy-access-token
  -> hosted agent container: protocol_adapter reads context.client_headers
  -> ADK session state -> get_servicing_policy: Authorization: Bearer <OBO token>
  -> policy API (Container App): delegated guard verifies token + AUTHORIZED_USER_IDS
```

`send_to_external_processor` is unchanged: it carries no user token, the receiver does not need one, and its outcome
is decided by egress policy only.

## 2. The three tokens / headers (all are the same user, different hops)

| Name | What it is | Hop | Code (SOURCE-VERIFIED) |
|---|---|---|---|
| `x-auth-request-access-token` | Entra **access token for app A** (the assertion for OBO) | oauth2-proxy -> ingress -> harness | `harness/obo.py` `INGRESS_TOKEN_HEADER`; ingress `auth-response-headers`; oauth2-proxy `--pass-access-token=true` |
| `X-Delegated-Policy-Token` | **OBO token for app B** (policy API) | harness -> facade, plain HTTP | `a2a_facade/client.py` (sends), `a2a_facade/server.py` `USER_TOKEN_HEADER` (reads) |
| `x-client-policy-access-token` | the same OBO token, as a Foundry `x-client-*` header | facade -> Foundry -> container | `a2a_facade/target.py` (`extra_headers`), `protocol_adapter.py` (reads) |

Then the tool sends it as `Authorization: Bearer` to the policy API (`tools.py` `get_servicing_policy`). The token is
never logged or put in a result record; only the boolean `user_token_forwarded` is recorded (`tools.py`,
`telemetry.py`).

## 3. Hop by hop

1. **oauth2-proxy.** Scope comes from Secret key `OAUTH2_PROXY_SCOPE` =
   `openid profile email offline_access api://<A>/access_as_user` (written by `chat-agent:external-app`).
   `--pass-access-token=true` and `--cookie-refresh=50m` are set; the ingress forwards the header and sets
   `proxy-buffer-size: 16k`. SOURCE-VERIFIED (manifests/task). Whether oauth2-proxy v7.7.1 behaves as intended with
   these flags, and whether 16k is enough, is **UNVERIFIED**.
2. **Harness OBO** (`harness/obo.py`, `harness/chat.py`). Runs only when `HARNESS_AUTH_MODE=ingress_oidc` **and** all
   four `HARNESS_OBO_*` settings are set (all-or-none; `harness/settings.py`). Uses
   `msal.ConfidentialClientApplication(...).acquire_token_on_behalf_of(user_assertion, scopes=[HARNESS_OBO_SCOPE])`.
   On failure the turn is **not run** and the UI gets HTTP 401 / WebSocket error with `source: identity` and
   `on-behalf-of exchange failed: <Entra error code or local label>` (`ingress_access_token_missing`,
   `obo_exchange_failed`). The token is held in the `current_user_token` **ContextVar** for the turn.
3. **Harness -> facade.** `harness/agent.py` `call_slot` reads that ContextVar and passes `user_token` through
   `ui_a2a.invoke_via_a2a` to `a2a_facade/client.py`, which adds `X-Delegated-Policy-Token`. The ContextVar is read in
   the harness only. The harness->facade hop is **plain in-cluster HTTP**: the token is not TLS-protected on that hop
   (stated in `a2a_facade/server.py`). That ContextVar reaches `call_slot` live is **UNVERIFIED** (the WebSocket path
   sets it before `asyncio.create_task`, which copies the context; `asyncio.to_thread` also copies it; unit-tested
   with mocks only).
4. **Facade.** `AuthMiddleware` keeps the facade's own bearer (`Authorization`) separate from the user token. Only the
   header's presence is logged (`user_token_present`). `ResponsesTarget` calls `responses.create(...,
   extra_headers={"x-client-policy-access-token": token})`.
5. **Foundry delivery.** The Microsoft doc states Foundry forwards `x-client-*` headers to the hosted container but not
   the caller's `Authorization` (SOURCE-VERIFIED: <https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/use-on-behalf-of-flow>,
   ms.date 2026-09-26). That it actually does so for this agent is **UNVERIFIED until the first live run**. The
   signature of a failure is `user_token_forwarded=false` in the UI (see section 6).
6. **Hosted agent.** `protocol_adapter.py` reads `context.client_headers.get("x-client-policy-access-token")`.
   SOURCE-VERIFIED in installed `azure-ai-agentserver-responses` 2.2.0 (`hosting/_endpoint_handler.py` ~line 628): the
   dict holds only lowercase keys of request headers starting with `x-client-`. The token is placed in the ADK
   **session state** (`state={"user_token": ...}`, `_run_agent_turn`). The tool functions take an ADK `tool_context`
   parameter (hidden from the model declaration; VERIFIED against google-adk 2.11.0 per the code comment in `agent.py`)
   and read `tool_context.state["user_token"]`. This is **session state, not a ContextVar**. That the live ADK runner
   hands the tool the same session state is **UNVERIFIED** (mock-tested only).
7. **Policy API** (`delegated_auth.py`, `services/policy_api/main.py`). Everything except `/healthz` is guarded. The
   token must be RS256, verified against Entra signing keys, with `aud` == `POLICY_API_AUDIENCE` (strict), issuer for the
   configured tenant (v2.0 or sts.windows.net form), `exp`/`nbf`/`tid`/`oid`/`scp` present, not an app token, `scp`
   containing `POLICY_API_SCOPE`, `azp`/`appid` in `POLICY_API_CLIENT_IDS`, then `oid` in `POLICY_API_AUTHORIZED_USER_IDS`.
   The actual `aud` value of an Entra v2 token for app B (GUID vs `api://` URI) is **UNVERIFIED**; the task prints the
   app B GUID as `TF_VAR_policy_api_audience`.

| Policy API result | Meaning |
|---|---|
| 200 | token verified, user allowed; body echoes `user_object_id` |
| 401 | missing/invalid token (`authentication_required`, `invalid_bearer`, `invalid_token`, `invalid_delegated_token`) |
| 403 | verified token but rejected: `user_not_authorized` (body echoes `user_object_id`), `insufficient_scope`, `untrusted_oauth_client` |
| 503 | signing keys unavailable/invalid |

Expected for the two test users (design, **not observed**): `8bbab162-0743-444c-b305-fed34bab43fb` -> 200;
`10870cbe-74ab-4c46-b5a8-8fcded26e615` -> 403 `user_not_authorized`; the same in Audit and Enforced, because
`get_servicing_policy` reaches an allowlisted host in both.

## 4. `x-ms-user-identity` is NOT sent

The Foundry doc says user identity can be sent with `x-ms-user-identity` and that this needs a custom
`UserIdentityImpersonation` data action (SOURCE-VERIFIED in the doc above). This repo sends no such header and does not
create that data action. Whether it is required for `x-client-*` forwarding is **UNVERIFIED**; the doc as read does not
say. If the first live run shows `user_token_forwarded=false`, this is the first thing to investigate. The policy API,
not Foundry, makes the identity decision from the user's own token.

## 5. Actor alias is not authorization

`actor_alias` in the UI is a display label (ingress header user name, or typed text in legacy mode). Nothing checks it
(`harness/chat.py`, `actor_context.py` docstring). The only identity decision the UI shows is the policy API's verdict on
the OBO token.

## 6. What the UI shows (`harness/chat.py` `_access_entry`, `harness/page.py`)

Derived only from the `get_servicing_policy` outcome, never from `send_to_external_processor`, never from the alias.

| Condition | UI status |
|---|---|
| `user_token_forwarded == false` | no evidence ("user token did not reach the tool") |
| HTTP 200 **and** `user_object_id` echoed by the policy API | `allowed` |
| HTTP 200, no `user_object_id` | no evidence (bare 200 never shows allowed) |
| HTTP 403 + error `user_not_authorized` | `denied` |
| HTTP 401 | `unauthenticated` |
| anything else / tool not attempted | no evidence |

The "Egress / containment" panel is separate and stays `inconclusive` without platform evidence.

### Known code defects found in this review (SOURCE-VERIFIED by reading; owner/engineer must fix, not docs)

1. **FIXED IN CODE (UNVERIFIED live): the `allowed` verdict was unreachable.** `invoke.outcome_from_record` used to copy
   `user_object_id` only when `http_status >= 400`. It now keeps a string `user_object_id` (bounded to 64 characters)
   at any status and `policy_error` only for >= 400. A test in `tests/unit/test_harness.py` runs a 200 record through
   `outcome_from_record` into the harness access logic and gets `allowed`.
2. **FIXED IN CODE (UNVERIFIED live): the harness container did not receive `HARNESS_OBO_*`.** `chat-agent:external-app`
   writes them into Secret `harness-oidc-config`, which only the oauth2-proxy deployment referenced. The harness
   deployment now has four explicit `env` entries (`secretKeyRef` name `harness-oidc-config`, key `HARNESS_OBO_*`,
   `optional: true`; no `envFrom`, so the proxy client secret and cookie secret stay out of the harness pod), and
   `external-app` / `external-app-down` run `rollout restart deployment/harness` because env is read at pod start.
   If the Secret exists with only some keys, `HarnessSettings` raises "must be all set or all unset" and the pod
   crash-loops (loud, intended). Original finding, kept for history: If so, `obo_enabled` is false and no token is forwarded (UI would show `user_token_forwarded` absent or
   false / policy API 401).
3. **FIXED IN CODE (UNVERIFIED live): the receipt KQL only matched denials.** The UI's receipt query now matches
   `authorization_decision` or `served`, so it can return the denial line or the served receipt (section 7). Not run.

## 7. Evidence fields (SOURCE-VERIFIED in code; ingestion unobserved)

- Tool result record: `user_token_forwarded` (bool); on HTTP >= 400 `result.error` and `result.user_object_id`; on 200
  `result` is the policy API's bounded body (at most 20 top-level keys), which includes `user_object_id` when the guard is on.
- App telemetry attribute: `demo.user_token_forwarded` on the `demo.tool_result` event. `user_object_id` is **not**
  emitted to app telemetry.
- Policy API stdout JSON receipts: served: `event=receipt`, `outcome=served`, `user_object_id`; denied/unavailable:
  `event=authorization_decision`, `outcome`, `auth_error`, `determination=identity_only`, and `user_object_id` only for
  403 `user_not_authorized`. Receipts carry no HTTP status and no `user_token_forwarded`.

Details: [telemetry-map.md](telemetry-map.md), [kql-queries.md](kql-queries.md) section 10.

## 8. Owner command order (read from the real tasks; none run)

Every step that builds, deploys or changes Entra needs owner approval. Never run `task` from an agent session.

1. **Build images so the new code ships.** `task build:all` (Azure ACR builds, billable) or the individual
   `build:foundry-agent`, `build:tool-apis`, `build:agent-bridge`, `build:chat-agent`. Each Dockerfile copies `src/`
   (policy API image copies `delegated_auth.py`). Which image carries what:
   hosted agent = `agent.py`, `protocol_adapter.py`, `tools.py`, `telemetry.py`; facade = `a2a_facade/*`; harness =
   `harness/*`, `ui_a2a.py`, `invoke.py`, `msal` (added to `Dockerfile.harness`); policy API = `services/policy_api/main.py`,
   `delegated_auth.py`.
2. **`uv lock`.** `msal` was added to `pyproject.toml` (extra `harness` and `dev`). `uv.lock` is tracked and **was not
   regenerated**. The images install from `pip` lines/`pyproject.toml`, not `uv.lock`, so this affects dev/test
   reproducibility; whether every Dockerfile ignores `uv.lock` was not checked (**UNVERIFIED**).
3. **`task app:deploy-external HOSTNAME=<fqdn> LETSENCRYPT_EMAIL=<email>`.** This runs `cloud:up` ->
   `deploy:app-components` -> `chat-agent:external-bootstrap`, and `external-bootstrap` itself runs `external-prereqs`
   -> `external-app` -> `external-up` -> `external-status`. **`external-app` is already inside it**; do not run
   `chat-agent:external-app` separately. `external-app` creates/updates app A, app B (`agent-boundary-policy-api`),
   scopes, requiredResourceAccess, tenant-wide consent, and the OIDC Secret, then **writes** the six
   `TF_VAR_policy_api_*` lines into `.env` (replacing any earlier ones).
4. **Before step 3, put `POLICY_API_AUTHORIZED_USER_IDS=8bbab162-0743-444c-b305-fed34bab43fb` in `.env`**, that user
   **only**; the task refuses to start without it. `10870cbe-74ab-4c46-b5a8-8fcded26e615` must be absent: absence from
   the list is what makes that user 403. Keep `ENDPOINT_IMAGE_TAG` equal to the policy API
   image tag, or `cloud:up` rolls the endpoints back to the placeholder (`.env.example`).
5. **`task cloud:up` (second pass), run by `app:deploy-external` as its last step in a new `task` process** so it
   reads the updated `.env`. Terraform reads the `TF_VAR_*` and adds the `POLICY_API_*` env to the policy API
   Container App. Until this pass the policy API stays in legacy (unauthenticated) mode because the cluster must exist
   before `external-app` can run. (SOURCE-VERIFIED in `infra/cloud/container-apps.tf`; not applied.)
6. **Roll out the new code** if it was built after the first pass: `task deploy:foundry-agent` (re-applies the harness
   deploy init container that publishes the agent versions from the ACR digest; whether a new version is created from a
   changed digest is **UNVERIFIED**), `task deploy:tool-apis`, `task agent-bridge:up`, `task chat-agent:up`
   (`deploy:agent-bridge` / `deploy:chat-agent` also create Secrets). Which exact rebuild/redeploy subset is minimal was
   not verified.
7. Sign in as each test user and run the harness; compare with section 6.

**Teardown:** `task chat-agent:external-app-down` (deletes app B, removes app A's scope and consent, resets
`OAUTH2_PROXY_SCOPE`, removes the `HARNESS_OBO_*` keys; app A is kept; deletes the `TF_VAR_policy_api_*` lines from
`.env`), then run
`task cloud:up` to return the policy API to legacy. `chat-agent:external-down` removes only ingress/oauth2-proxy and
does **not** undo the Entra changes.

**Standing-rule departure:** these tasks use the `az` CLI (`az ad`, `az rest` to Microsoft Graph). The squad rule is no
`az` in anything that ships; this is an exception made at the owner's explicit request.

## 9. Failure signatures (general Entra knowledge; **UNVERIFIED in this repo**)

| Symptom | Usual cause (UNVERIFIED) |
|---|---|
| harness 401 `on-behalf-of exchange failed: invalid_grant` / AADSTS65001 | consent for app A -> `policy.read` missing |
| AADSTS50013 / AADSTS70011 | assertion invalid, or scope not exposed / wrong scope string |
| AADSTS500133 | assertion expired |
| Browser 500 after login; oauth2-proxy log `failed to fetch claims from profile URL … Invalid audience` | **Observed 2026-10-20.** With the `api://<A>/access_as_user` scope the access token is for app A, so oauth2-proxy's Graph userinfo call is rejected. Fixed by `--skip-claims-from-profile-url=true` (flag exists in v7.7.1 docs; fix not yet confirmed live) |
| harness 401 `ingress_access_token_missing` | oauth2-proxy did not pass the access token (SOURCE: raised in `obo.py`) |
| policy API 401 | missing/invalid token, wrong `aud`/issuer (code names in section 3) |
| policy API 403 `user_not_authorized` | the signed-in `oid` is not in `AUTHORIZED_USER_IDS` (expected for the denied user) |
| UI no evidence + `user_token_forwarded=false` | header did not reach the tool: Foundry did not deliver it, or section 6 defect 2 |
| login loop / 502 / header missing | oauth2-proxy cookie or header size (UNVERIFIED; `proxy-buffer-size: 16k` is set) |

The Entra AADSTS names are not read from any document in this repo.

## 10. UNVERIFIED list

- Foundry delivers `x-client-policy-access-token` to the container; whether `x-ms-user-identity` / the custom data
  action is needed.
- OBO token `aud` is the app B appId GUID for v2.
- Graph PATCH of scopes, `requiredResourceAccess`, `oauth2PermissionGrants` behaves as the task assumes; service
  principal propagation delay.
- oauth2-proxy v7.7.1 flag behaviour and header/cookie size.
- ContextVar reaches `call_slot` live; ADK session state reaches tool tasks live.
- KQL in the UI and in kql-queries.md section 10 returns rows.
- Policy API stays legacy until the second `cloud:up`.
- `demo_ui.py` (two-button UI) still shows the old `status_from_http` badge (out of scope).
