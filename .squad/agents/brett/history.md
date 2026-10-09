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

### 2026-10-08 — Agent deployment module (`src/containment_demo/deploy.py`)

**The real SDK surface, verified by reading source, not docs.** `azure-ai-projects` is not
in this repo's `.venv`. The newest copy on this machine is **2.8.0** at
`/home/brian/code/foundry-infrastructure-design/src/hosted_agents/simple/.venv/lib/python3.14/site-packages/azure/ai/projects/`.
Everything below is recorded in `docs/compatibility.md` §B9a with line numbers:

- `AIProjectClient(endpoint, credential, allow_preview=True)` — `_client.py:40`.
  Default credential scope `https://ai.azure.com/.default` (`_configuration.py:57`), and
  `api_version` defaults to `"v1"`, *not* an explicit `2025-11-15-preview` string.
- `client.agents.create_version(name, definition=, description=, metadata=)` →
  `AgentVersionDetails` (`operations/_operations.py:5441`); `get_version` at `:5891`;
  `list_versions` at `:6042`.
- `HostedAgentDefinition(cpu=, memory=, rai_config=, environment_variables=,
  container_configuration=, protocol_versions=)` — `models/_models.py:12344`.
- `RaiConfig(rai_policy_name=...)` — `models/_models.py:16765`. Plain `rest_field` with no
  `name=` override, so the wire name is snake_case. **B4 confirmed in code.**
- `ContainerConfiguration(image=, registry_connection_id=)` — `models/_models.py:7230`.
- `ProtocolVersionRecord(protocol=, version=)` — `models/_models.py:16657`.
- `AgentVersionStatus`: creating / active / failed / deleting / deleted — `_enums.py:380`.

**Three places the SDK differs from the az CLI shape recorded in B9.** The CLI speaks
`2025-11-15-preview`; the SDK is what ships, so the SDK wins: the image is nested under
`container_configuration`, protocols are `protocol_versions` (not
`container_protocol_versions`), and **there is no container start operation at all** — no
`containers/default:start` equivalent on `AgentsOperations`. Readiness is polled via
`get_version(...).status`.

**Digest pinning.** `ContainerConfiguration.image` is an unvalidated `str`. The SDK does
none of the CLI's `_validate_image_tag` work, so a digest passes client-side and the
service assigns the version name. Server-side acceptance is still unverified and cannot be
verified from outside the VNet. The module requires a digest, has no tag fallback, and
raises `DigestRejectedError` with a STOP instruction.

**Packaging.** `azure-ai-projects` went in an optional `deploy` extra, not base
dependencies: it needs `openai>=3` and the agent image must not change because the deployer
gained a dependency. The agent image digest is the control. The SDK is imported lazily in
`build_client()` only, which is why `pytest tests/unit` needs no Azure package, no
credentials and no network — 124 passing, 1 skipped (the real-SDK model check, which
`importorskip`s).

**Pattern worth keeping:** the deployer verifies by read-back, never by assuming the write
landed. An Enforced agent with a silently-unattached policy looks exactly like a working
Enforced agent that allows everything — that is the most dangerous way this demo could
lie, so it is a loud `DriftError`.

### 2026-10-08 — Init-container entrypoint is now explicit absolute interpreter path, not bare `python`

Parker fixed a critical deployment defect: the init container's bare `python` command had no
access to the `azure-ai-projects` deployment stack (installed only in `/opt/deploy-venv`,
not system). The fix adds `var.agent_deploy_interpreter` (default `/opt/deploy-venv/bin/python`,
validated absolute path) to `infra/k8s/harness.tf`. Command is now
`[var.agent_deploy_interpreter, "-m", var.agent_deploy_module]`.

**Why absolute path, not PATH ordering:** PATH resolution would make the pod silently sensitive
to any later `ENV PATH` edit in the Dockerfile, and that failure would be indistinguishable
from a missing dependency. Absolute path forces the failure loud if someone moves the venv.

**Team caveat:** No mechanical check ties decisions.md, Dockerfile, and Terraform together.
If deploy module path, interpreter path, or venv path moves, all three must move together,
and that is caught only by reading or by apply.

**Commit:** b3c60a3

- **Digest-only validation is final.** `DEMO_AGENT_IMAGE` must be `repo@sha256:<64 hex>`. If service rejects it, the module raises `DigestRejectedError`, exits 3 with STOP, no tag fallback, no configuration to override this. Server-side acceptance is still unknown; first hosted run answers it.
- **Read-back verification is real.** After creating each version, the module reads it back and asserts the attached policy ARM id and image digest match exactly. Detects the silent failure (policy did not attach).
- **Idempotent on pod restart.** Version matching both image digest AND policy ARM id, not in terminal bad state, is reused. Existing versions never mutated (maintains auditability). A restart creates nothing and exits 0.
- **Only `DEMO_POLICY_MODE` differs between agents.** `assert_single_variable()` and `test_environment_differs_only_by_the_evidence_label()` enforce this. No hostname hint, allowlist, or "expected outcome" sneaks in via env var.
- **Timeouts are bounded and a timeout is a failure.** `DEMO_DEPLOY_TIMEOUT_SECONDS` (default 900) for status == "active". A version still "creating" at deadline is failure, not optimistic pass. An unprovisioned agent proves nothing.
- **The deployer venv is in the same image as the agent, not a separate image.** `/opt/deploy-venv` (install `.[deploy]` there), `/opt/deploy-venv/bin/python` (init container uses this). One image, one digest, two isolated dependency sets. Agent's dependencies untouched.
- **Parker's init-container contract is final.** Module path in `var.agent_deploy_module` (variables.tf), entrypoint command in `infra/k8s/harness.tf`, all `DEMO_*` env vars injected from Terraform outputs. If the module moves, tell Parker and he updates variables.tf.

## Learnings — 2026-10-08, the 45-minute poller hang

**An SDK enum is not the service's contract.** `AgentVersionStatus`
(`azure/ai/projects/models/_enums.py:380`) declares creating/active/failed/deleting/deleted.
The live service also returns `running`; Brian's production deployer
(`briandenicola/banking-agent-foundry-orchestrator`, `src/agents/deployer/deploy.py:20-21`)
carries `READY_STATUSES = {"active","running"}` and
`PENDING_STATUSES = {"creating","starting","updating"}`. I derived `_TERMINAL_OK = "active"`
from the enum and from my own module docstring, and polled a healthy agent for 45 minutes.
**Consult Brian's repo before deriving Foundry hosted-agent behaviour from type definitions.**

**`str()` on a `(str, Enum)` SDK member returns the qualified name, not the value.**
Verified against azure-ai-projects 2.8.0 by deserialising each case: `"active"` becomes
`AgentVersionStatus.ACTIVE` whose `str()` is `'AgentVersionStatus.ACTIVE'`, so the old
`str(status).lower()` produced `'agentversionstatus.active'` — it could never match
`'active'`. Out-of-enum values (`"running"`, `"Running"`, `"weird-new-status"`) pass through
as plain `str`, unmangled, so `.value`-with-raw-fallback is correct for both cases. That is
`_normalise_status()`.

**A loop that logs nothing is indistinguishable from a loop that works.** ~270 HTTP 200s,
zero lines about what status came back. azure-core's `http_logging_policy` filled the log
with headers so the container looked healthy while saying nothing that mattered. We built
and applied an ACR role-assignment theory for a problem that did not exist. Log the thing
the decision is made on, every time, flushed.

**Prefer a bounded `for` over `while True` + a monotonic deadline.** Our deadline provably
did not fire and I could not establish why from code plus read-only cluster state
(`DEMO_DEPLOY_TIMEOUT_SECONDS` is not injected by `deploy/kustomize/base/deployment.yaml`,
so 900.0 was in effect; the deadline was computed once, not per iteration). Surviving
hypotheses: azure-core's default `retry_total=10` with `retry_backoff_max=120` blocking
inside a single `get_version` where a single-threaded loop cannot observe its deadline; or
wall-clock from pod start covering client construction and token acquisition, which are
outside the deadline. **Stated as unresolved, not guessed.** `attempts = ceil(timeout/poll)`
removes the whole failure class.

**Fakes must not be optimistic.** My `FakeAgentsOperations.get_version` defaulted to
`"active"` once its scripted statuses ran out, which would have let a test pass on an
unknown status. Status is now sticky; only versions the fake itself created auto-advance.

**Settings now:** timeout 900→120 (`le` 3600→600), poll 10→3, request timeout 60→15, new
`deploy_retry_total=2`. A timeout remains a FAILURE, never an optimistic pass.

Recorded in `docs/compatibility.md` B9c; B9b's status subsections annotated as superseded.
Decision: `.squad/decisions/inbox/brett-deploy-poller.md`.

### 2026-10-08 — Deploy poller debugging batch completed; status vocabulary and instrumentation fixed

- **Orchestration log created: 2026-10-08T19:35:42Z-brett.md**
- **Session log 2026-10-08T19:51:57Z-deploy-poller-debugging.md documents the batch**
- **Root cause:** Incomplete SDK enum + `str(Enum).lower()` stringification bug + silent polling loop.
  - `AgentVersionStatus` missing `running` (also `starting`, `updating` per Brian's production deployer at `briandenicola/banking-agent-foundry-orchestrator`)
  - `str(status).lower()` on enum mixin → `'agentversionstatus.active'` (never equals `'active'`)
  - Poll loop logged nothing; 270 HTTP 200s with zero status output made healthy and hung systems byte-identical
- **Lesson for repo:** This repo's own evidence rule (missing evidence = INCONCLUSIVE, never signal) applies to debugging the demo itself. Polling without logging observability is a defect, not a clue.
- **Decisions merged into .squad/decisions.md:**
  - "Verify Status Vocabularies Against Running Service, Not SDK Enums" (Brett)
  - Includes status sets with sources, bounded iteration, comprehensive logging, BrianDenicola's production deployer as primary reference
- **Unit tests:** `tests/unit/test_deploy.py` covers all pollin scenarios including the original stringification bug as tamper test
- **Next:** First invocation closes GATE 0 with Q0 query; both agents run and emit telemetry


## Learnings — 2026-10-08, the un-awaited entry point

**`context.get_input_text()` is `async def`.** Verified against the installed
azure-ai-agentserver-responses 2.2.0: all four `ResponseContext` variants
(`_response_context`, `hosting._endpoint_handler`, `hosting._execution_context`,
`hosting._routing`) report `coroutine=True`, signature
`(self, *, resolve_references: bool = True) -> str`. `protocol_adapter.py:70` dropped the
`await`, so `user_text` was a coroutine object. The model never saw the prompt and
**neither business tool could be reached on the deployed digest.** Every invocation result
from that digest is inconclusive — no egress was ever attempted.

**The entry point had zero tests, and that is why it shipped.** `tests/unit/` covered the
tools thoroughly and covered the function that calls the tools not at all. Coverage had
been allocated by what was easy to test offline rather than by what is fatal if wrong.
`tests/unit/test_protocol_adapter.py` now exists: handler registration, the await, the
host-before-agent ordering, no collision with `PLATFORM_ROUTES`, the cancellation contract,
and the diagnostics wiring.

**A lazily imported SDK boundary is a hazard class.** `build_host` imports the SDK inside
the function (deliberately — the host must configure OpenTelemetry before ADK imports), so
there is no import-time signature for mypy, ruff or a reader to check the call against.
`context: Any` means the type checker sees nothing. Only a test with an `async def`
stand-in catches it. **A fake must match the real object's async-ness, and that match must
itself be asserted** — `test_the_fake_context_matches_the_real_sdk_shape` does that, because
a sync fake would make the regression test worthless.

**Offline technique worth reusing:** `monkeypatch.setitem(sys.modules, "a.b.c", fake)`.
`sys.modules` is consulted for the full dotted name before parent packages are imported, so
the real `azure.ai.agentserver.responses` and `google.adk` are never loaded. No Azure
package, no credentials, no network.

**Same root cause as the deploy poller, two days running.** That one trusted an SDK enum
over a running service; this one trusted an SDK signature that was never read. Where SDK
behaviour drives correctness, verify it against the installed package or a running service
and pin the verification in a test.

**Watch the working tree.** My first application of the `await` fix was reverted under me
mid-session (other agents are editing in parallel). The new tests caught it immediately,
which is the point — but re-grep the file after editing when others are active.

Tamper results: removing the `await` failed `test_handler_passes_a_real_str_to_the_agent_turn`
and `test_get_input_text_is_actually_called`; making cancellation raise failed all three
cancellation tests; registering diagnostics unconditionally failed
`test_route_is_not_registered_when_disabled`; re-implementing a tool in `_RUNNERS` failed
`test_diagnostics_reuses_the_two_tool_implementations`; the no-op control stayed green.

Decision: `.squad/decisions/inbox/brett-adapter-await.md`. 244 unit tests pass, lint green.
**Both agent versions need a rebuild and redeploy — the digest changes.**

## Learnings: demo UI (issue #1)
- Built `demo_ui.py` + `tests/unit/test_demo_ui.py` (19 tests). Tamper-tested six guards: auth (test_run_requires_auth), slot allowlist (test_unknown_slot_rejected), no-pass determination, our-call label, CSRF header, no-secret logging; each broke exactly its test.
- The UI needs the SDK (lazy import in invoke) so it cannot run in the agent image; added `demo-ui` extra.
- `lint:manifests` only builds deploy/kustomize/base; the demo-ui dir is dry-run-validated by hand only.

## Learnings: demo UI deploy
- Included Taskfile tasks run with dir = the included file's dir; pass `{{.ROOT_DIR}}`-absolute paths. Task's shell lacks `$!`; use `timeout`.
- Parker's client id output: `demo_ui_identity_client_id`. Tamper-tested: leftover-placeholder guard, bad-digest guard.

## Learnings: A2A spike
- `AgentsOperations.update_details` (azure-ai-projects 2.8.0 operations/_operations.py:6144) merge-patches agent_endpoint + agent_card on the AGENT. a2a-sdk is not installed locally; reference repo has no A2A. Hosted-container support remains UNKNOWN.

## Learnings: route paths
- Test fixtures must use the deployed config shape; full-path fixtures hid a base-URL-vs-route mismatch.

## Learnings (capture-off)
- ADK `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS` defaults ON (google/adk/telemetry/context.py:132-136); drives gcp.vertex.agent.* content attrs (tracing.py:319-358). Now forced off in protocol_adapter.main().

- GATE 0 run-id-in-path: tools._endpoint(base, path, run_id) + services /policy/{run_id}, /ingest/{run_id}; respx accepts compiled regex as URL (query string appended, so allow (\?.*)?$).

- Demo UI: ToolOutcome.tool_run_id from the tool record; UI view fields ui_run_id vs tool_run_ids.

- a2a spike runs via kubectl exec in harness pod, deploy-venv; tasks cloud:a2a-card/-enable/-send.
