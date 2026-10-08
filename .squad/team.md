# Squad Team

> agent-boundary-lab

## Coordinator

| Name | Role | Notes |
|------|------|-------|
| Squad | Coordinator | Routes work, enforces handoffs and reviewer gates. |

## Members

| Name | Role | Charter | Status |
|------|------|---------|--------|
| Ripley | 🏗️ Lead | `.squad/agents/ripley/charter.md` | Active |
| Parker | ⚙️ Infrastructure / Platform | `.squad/agents/parker/charter.md` | Active |
| Brett | 🔧 Agent Developer | `.squad/agents/brett/charter.md` | Active |
| Dallas | 🧪 Verification | `.squad/agents/dallas/charter.md` | Active |
| Lambert | 📊 Telemetry / Evidence | `.squad/agents/lambert/charter.md` | Active |
| Scribe | 📋 Session Logger | `.squad/agents/scribe/charter.md` | Active (silent) |
| Ralph | 🔄 Work Monitor | `.squad/agents/ralph/charter.md` | Monitor |

## Project Context

- **Project:** agent-boundary-lab
- **Owner:** briandenicola (Brian)
- **Created:** 2026-10-07
- **Team cast:** 2026-10-08

**What it is:** a demo proving that outbound network containment for an AI agent is
enforced by the Microsoft Foundry platform, not by application code. A Python Google ADK
agent with exactly two HTTP tools runs in a Foundry hosted-agent container. One tool calls
an allowlisted hostname (expected success); the other calls a hostname deliberately omitted
from the allowlist (expected platform denial). The same image digest is deployed twice, and
the Audit vs Enforced RAI network egress policy is the only experimental variable.

**Stack:** Python 3.12 (uv, not pip), Google ADK 2.11, Terraform + azapi, Azure Foundry
hosted agents, AKS, Container Apps, PostgreSQL, Dapr Workflow (Phases 8-9), pytest,
go-task. Region canadacentral.

**Key documents:**

| Document | Purpose |
|---|---|
| `docs/README.md` | Scope, architecture, acceptance criteria |
| `docs/PLAN.md` | Phased implementation plan - the unit of work |
| `docs/compatibility.md` | The verified-facts record. If a platform claim is not here with a source, it is not a fact. |
| `docs/egress-control.md` | In-depth reference on how Foundry restricts outbound tool calls |

## Standing Rules

- Brian runs every `task` command himself. Agents never apply Terraform, never create
  billable resources, never publish images. Read-only `az` queries are fine.
- **No `az` CLI in anything that ships.** Terraform or SDK only.
- Both tools are always registered, unconditionally, in every mode.
- Missing evidence is inconclusive, never a pass.
- Never invent an SDK API, platform field name, or monitoring table.
