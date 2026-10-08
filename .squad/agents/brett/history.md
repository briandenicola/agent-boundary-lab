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
