# Copilot instructions — agent-boundary-lab

## What this repository currently is

A deployed Azure demo with a tested Foundry egress/identity baseline and an isolated
ACS governance track. `docs/README.md` is the documentation index, and
`docs/PLAN.md` describes current delivery work. Source, Terraform, Taskfiles and
offline tests are implemented; do not restart the original scaffold phases.

Read both documents before generating code. Preserve the tested baseline while
implementing the current plan; verify new platform contracts before using them.

## Build, test, and lint

Use existing Task targets and record runtime contracts in `docs/compatibility.md`.
The owner runs builds, deployments, hosted calls and teardown.

- Python packaging via `pyproject.toml` with dependency locking.
- Tests via `pytest`, split into `tests/unit/` and `tests/integration/`
  (plus `tests/workflow/` for Phases 8–9).
- Single test: `pytest tests/unit/test_tools.py::test_both_tools_registered`
- Single file: `pytest tests/unit/test_tools.py`
- Unit suite only (no network, no Azure): `pytest tests/unit`
- Container image: `docker build .` from the repo root using the Dockerfile.
- Demo verification harness: `python scripts/verify_demo.py` — must report
  pass / fail / **inconclusive**, and must label local runs separately from
  hosted runs.

Keep integration and hosted tests opt-in; never make the default test command
require Azure credentials or billable resources.

## Architecture (the big picture)

Three independently observable layers prove one claim: outbound network
containment is enforced by the **platform**, not the application.

1. **Agent** — a Python Google ADK agent with *exactly two* business tools,
   wrapped by a Foundry protocol adapter (Responses preferred, Invocations
   otherwise) and run inside a Foundry hosted-agent container.
   - `get_servicing_policy` → an allowlisted HTTPS hostname (expected success).
   - `send_to_external_processor` → a hostname deliberately **omitted** from the
     allowlist (expected platform denial).
2. **Policy** — account-level RAI policy resources, one Audit and one Enforced,
   with network default-deny plus an exact-host allow rule. The same image digest
   is deployed to both agent versions; the policy is the only experimental
   variable.
3. **Evidence** — application/tool traces, platform egress decisions, and
   receipt logs at the two controlled APIs, correlated by `demo_run_id` and
   trace ID. `docs/telemetry-map.md` records the *real* field names found during
   validation.

Phases 8–9 add a Python **Dapr Workflow** app on AKS (persistent state store,
PostgreSQL candidate) that invokes the unchanged Foundry agent from activities,
waits on an authenticated approval event with a durable deadline, and survives a
workflow-pod restart. Azure Durable Task Scheduler and its SDK are explicitly
**not** dependencies. Phase 10 (messaging bridge, OpenShift/local portability)
stays deferred.

## Non-negotiable conventions

These are the point of the repository; violating them invalidates the demo.

- **Both tools are always registered**, in every mode. No conditional
  registration, no code-level hostname allowlist, no prompt-only refusal, no
  mode-specific branching inside tool implementations.
- **No arbitrary-URL tools.** Destinations come from validated startup config.
  The authenticated diagnostic route reuses the same two tool implementations and
  is not a third business tool.
- **Never present an application check as platform enforcement.** A bare HTTP
  403, DNS error, timeout, model refusal, or missing log is not proof of
  containment. Classify HTTP / TLS / DNS / timeout failures separately. Missing
  evidence is **inconclusive**, never a pass.
- **Do not invent SDK APIs, platform field names, or monitoring tables.** Verify
  against the primary references listed in `docs/README.md`, and record the access
  date. If a preview feature is unavailable, mark that work **blocked** and stop.
- **Approval gate:** generate code, tests, and deployment artifacts freely; get
  owner approval before creating billable resources, changing Azure policies,
  publishing images, or sending telemetry to a new destination. Never modify an
  existing production or mixed-purpose RAI policy.
- **HTTP hygiene:** TLS verification always on, explicit bounded timeouts,
  redirects disabled, no fallback destination. One tool's failure must not
  suppress the other's result.
- **Synthetic data only.** No customer records or credentials. Prompt, response,
  payload, and authorization-header capture stays disabled in telemetry. Commit
  `.env.example` with placeholders only; use managed identity for credentials.
- **Label honestly.** Local runs are functional tests, not containment proof.
  Keep tested results, proposed behavior, and preview capability clearly
  separated in docs and reports.

## Repository layout

Keep the existing layout:
`src/containment_demo/` (agent, tools, protocol_adapter, diagnostics, telemetry,
settings), `src/services/policy_api/` and `src/services/test_receiver/`, `infra/`,
`scripts/`, `tests/`, and the `docs/` deliverables (`compatibility.md`,
`demo-runbook.md`, `telemetry-map.md`).

Note that `README.md` and `PLAN.md` currently live under `docs/`, while the plan
text refers to them at the repo root — resolve paths against the actual files in
`docs/`.
