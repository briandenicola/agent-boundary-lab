# Project Context

- **Owner:** briandenicola (Brian)
- **Project:** agent-boundary-lab — a demo proving that outbound network containment for an
  AI agent is enforced by the **Microsoft Foundry platform**, not by application code. A
  Python Google ADK agent with exactly two HTTP tools runs in a Foundry hosted-agent
  container. One tool calls an allowlisted hostname (expected success); the other calls a
  hostname deliberately omitted from the allowlist (expected platform denial). The same
  image digest is deployed twice, and the Audit vs Enforced RAI network egress policy is
  the **only** experimental variable.
- **Stack:** Python 3.12 (uv — **pip cannot install this project**), Google ADK 2.11,
  Terraform with the azapi provider for preview Foundry resources, Azure Foundry hosted
  agents, AKS, Container Apps, Azure Database for PostgreSQL, Dapr Workflow (Phases 8–9),
  pytest, go-task. Region canadacentral. Model gpt-5.4-mini.
- **Created:** 2026-10-08

## Core Context

Non-negotiable project rules (from `.github/copilot-instructions.md` — violating any of
these invalidates the demo):

- Both tools are **always registered**, in every mode. No conditional registration, no
  code-level hostname allowlist, no prompt-only refusal, no mode-specific branching.
- No arbitrary-URL tools. Destinations come from validated startup config.
- Never present an application check as platform enforcement. A bare HTTP 403, DNS error,
  timeout, model refusal, or missing log is **not** proof of containment. Classify HTTP /
  TLS / DNS / timeout failures separately. **Missing evidence is inconclusive, never a pass.**
- Do not invent SDK APIs, platform field names, or monitoring tables. Verify against
  primary references and record the access date. Preview feature unavailable → mark
  **blocked** and stop.
- Approval gate: generate code, tests, and deployment artifacts freely; get Brian's
  approval before creating billable resources, changing Azure policies, publishing images,
  or sending telemetry somewhere new.
- HTTP hygiene: TLS verification always on, explicit bounded timeouts, redirects disabled,
  no fallback destination.
- Synthetic data only. Label local runs as functional tests, not containment proof.

Brian's standing preferences:

- **He runs every `task` command himself.** Read-only `az` queries are fine. Never apply
  Terraform or create billable resources.
- **No `az` CLI in anything that ships.** Terraform or SDK only — that is what the client
  uses.
- Short, plain, actionable output. No hedging, no unsolicited caveats, no long recaps.
- Commit and push completed work after each feature.

## Current state (2026-10-08)

Deployed and working in canadacentral: Foundry account (inbound-private), AKS, ACR,
Postgres, both Container Apps serving real images, both RAI policies live and correct.
80 unit tests pass. Agent image built and digest known.

**Nothing is enforced yet — no agent version exists**, so neither policy is attached to
anything. That is the active blocker. See `docs/egress-control.md` for the full mechanism
and `docs/compatibility.md` §B9 for the deployment API.

## Learnings

<!-- Append new learnings below. Each entry is something lasting about the project. -->

## Learnings (2026-10-08 — PLAN.md re-gate)

### 2026-10-08 — init-container interpreter defect (Parker's action item)

`infra/k8s/harness.tf` runs `["python", "-m", var.agent_deploy_module]` but Dockerfile installs
`azure-ai-projects` only into `/opt/deploy-venv`. The pod fails with `ModuleNotFoundError` on
first run. Fix: use `["/opt/deploy-venv/bin/python", "-m", var.agent_deploy_module]`.
This is a Ripley/Brett observation, Phase 4 Blocker 1.

- **`Cognitive Services User` is sufficient for agent writes — verified, with one gap.**
  `az provider operation show -n Microsoft.CognitiveServices` registers
  `Microsoft.CognitiveServices/accounts/AIServices/agents/write`. The role's dataActions
  are the single wildcard `Microsoft.CognitiveServices/*`, and its notDataActions exclude
  only `agents/endpoints/UserIdentityImpersonation/action` and two fine-tune deployment
  writes. So the wildcard covers it. **UNVERIFIED:** no primary source states the role
  *required* to create an agent **version**; `agents/versions` is not separately
  registered, so version writes are assumed to authorise under `agents/write`. A 403 from
  the deploy init container should be suspected here before the federated credential.
- **The kubernetes provider cannot live in `infra/cloud`.** Its `host` and
  `cluster_ca_certificate` are unknown at plan time on a clean state, which breaks
  `task cloud:plan` — the one moment a plan is most worth reading. Cluster contents went
  into a separate root module, `infra/k8s`, reading `infra/cloud`'s local state through
  `terraform_remote_state`.
- **An init container shares its pod's ServiceAccount, and a ServiceAccount carries
  exactly one `azure.workload.identity/client-id`.** So the whole harness pod runs as the
  deployer identity. When the A2A loop lands it will need Foundry Agent Consumer to
  *invoke*; either grant it to the same identity or split the deploy into its own pod.
  There is no second annotation.
- **`azure.workload.identity/use: "true"` is a pod LABEL, not an annotation.** As an
  annotation the webhook does not mutate the pod, no token is projected, and
  `DefaultAzureCredential` silently falls through to something else.
- **The uncommitted identity work had a real bug.** `outputs.tf` built the RAI policy IDs
  from `var.rai_policy_audit_name` / `var.rai_policy_enforced_name`, which are *outputs*,
  not variables — `terraform validate` was the only thing that caught it. Both now take
  `azapi_resource.rai_policy_*.id` directly. Stop assembling ARM IDs by hand.
- **The deploy module contract is real, not assumed.** `src/containment_demo/deploy.py`
  exposes `main()` under a `__main__` guard, takes no arguments, and reads everything from
  `DEMO_`-prefixed environment. `python -m containment_demo.deploy` is the init container
  command. Its `DeploySettings` field names were read from the file, not guessed.
- **`kubelogin` is the cost of `local_account_disabled = true`.** There is no admin
  kubeconfig to borrow, so terraform authenticates to the API server through it. That is
  operator auth, equivalent to the ambient `az login` the azurerm provider already needs;
  nothing inside a container uses a CLI.

### 2026-10-08 — App Insights project connection, Container App images into Terraform

- **The AppInsights project connection schema is fully verified, and the decisive source
  is the CONSUMER, not the ARM schema.** `Microsoft.CognitiveServices/accounts/projects/
  connections@2026-05-15-preview`, `category: "AppInsights"`, `authType: "ApiKey"`,
  `credentials: { key: <connection string> }`. The "API key" is the Application Insights
  **connection string** — not an instrumentation key, not a resource id. Settled by
  `azure/ai/projects/operations/_patch_telemetry.py`, which rejects anything that is not
  `ApiKeyCredentials` and reads `credentials.key`. Recorded as compatibility.md §C5.
- **An `AAD` connection here would have applied cleanly and silently done nothing.** ARM
  accepts it; the consumer raises `ValueError` and never resolves a connection string.
  Getting the category right is not sufficient. `cloud:app-insights-connection` therefore
  checks the auth type too, not just existence.
- **At most one AppInsights connection per project.** Stated in the same SDK file. One
  resource, no `count`.
- **The connection is a child of the PROJECT.** There is a parallel account-scoped
  connections path (`accounts/{a}/connections`); the telemetry lookup does not read it.
- **`sensitive_body` on `azapi_resource` is how a credential goes into an azapi body.**
  Plain `body` renders in plan output.
- **Out-of-band `az containerapp update --image` was worse than the az rule suggests.**
  Terraform owned the apps but not what they ran, held apart by `ignore_changes` on the
  image. Removing that and making the image a variable fixed a real bug for free: the
  task rebuilt the app name by concatenation, and Container App names truncate at 32
  characters, so it addressed `humble-phoenix-46689-policy-api` when the app is
  `humble-phoenix-466-policy-api`.
- **Empty-string-means-placeholder is the only honest way to seed a Container App.** The
  images do not exist in ACR on a first apply, so terraform cannot point at them. The tag
  lives in `.env` (the root Taskfile already dotenv-loads it) so it persists across
  applies instead of hiding in state.
- **One tag for both endpoints, not two image references.** Both come out of one
  `services/Dockerfile` in one build. The policy API's success is only a usable control
  for the receiver's silence if the two cannot drift apart, and a single tag makes that
  divergence impossible to express.
- **Brett's deployment contract is final; do not change module path or env vars without telling him.** The init container reads `var.agent_deploy_module` from variables.tf; if it moves, the pod fails with `ModuleNotFoundError`.
- **RBAC assumption on `agents/versions` write is unverified.** If init container gets 403 on `create_version`, suspect this before the federated credential. See decisions.md §8.
- **The deploy SDK's openai>=3 dependency had to be isolated in a separate venv.** Without it, the SDK drags the agent's own model stack sideways (litellm 1.104→1.83, openai 2.54→3.26), which is an uncontrolled variable in the thing under test. The image digest is the experiment; dependencies on the agent's side must not drift.

### 2026-10-08 — the init container was running the wrong interpreter

- **The decision record said `/opt/deploy-venv/bin/python`; `harness.tf` said `python`.**
  Ripley caught it during the PLAN re-gate. The defect was real: the Dockerfile installs
  the agent stack with `uv pip install --system` and the deploy extra only into
  `/opt/deploy-venv`, and that venv is never activated and never added to PATH. A bare
  `python` resolves to the system interpreter, so the deploy would have died at import
  time with `ModuleNotFoundError: azure.ai.projects` — after the pod had already pulled
  the image and proven workload identity, which is the most misleading possible place to
  fail.
- **A decision record is not an artifact.** This one was written, agreed, quoted in two
  places in `decisions.md`, and still did not match the Terraform. Nothing mechanical
  connected the two. `terraform validate` cannot see it, and the unit suite does not
  render the pod spec. The only check that would have caught it is actually running the
  init container, which costs an apply.
- **The interpreter is now `var.agent_deploy_interpreter`, defaulting to the absolute
  path, with a validation that it starts with `/`.** Absolute over PATH ordering on
  purpose: PATH resolution would also make the pod silently sensitive to any future
  `ENV PATH` edit in the Dockerfile, and that failure would look identical to a missing
  dependency.

### 2026-10-08 — `timestamp()` in tags destroyed plan cleanliness

- **`DeployedOn = timestamp()` made every plan permanently dirty.** `timestamp()`
  re-evaluates at plan time, so the whole tag map went unknown and every tagged resource
  was marked for in-place update. Live plan: 24 changes, 22 of them tag-only churn.
  Confirmed in both `infra/cloud/locals.tf` and `infra/spike/locals.tf`.
- **Plan cleanliness IS the drift control for this demo.** The claim is that the RAI
  policy is the only variable between the Audit and the Enforced run, and the only
  mechanical way to show it is `No changes.` between them. A tag that always drifts does
  not just add noise, it removes the evidence. Treat a non-empty plan on an unchanged
  configuration as a defect.
- **It also re-PUT the preview Foundry account on every apply to rewrite a string.** The
  one resource we know silently drops configuration was being touched for no reason, and
  `foundry_endpoint` went to (known after apply) with it.
- **Removed the tag rather than stabilising it.** Nothing read it — not tasks, not
  scripts, not any KQL. `Application` and `AppName` ARE read (`arm:_account-id` and the
  teardown targets look resource groups up by `Application`), so those stay. Deploy time
  is already in ARM metadata and in git.
- **Rule for this repo:** no plan-time-varying function — `timestamp()`, `uuid()`,
  `bcrypt()` — in any attribute of a persistent resource. Recorded as compatibility.md §C6.
