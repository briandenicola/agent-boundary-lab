# Project Context

- **Project:** agent-boundary-lab
- **Created:** 2026-10-07

## Core Context

Agent Scribe initialized and ready for work.

## Recent Updates

📌 Team initialized on 2026-10-07

### 2026-10-08 — Orchestration and decision consolidation for kustomize migration batch

- **Created orchestration logs** for Parker (kustomize migration), Coordinator (two defect fixes), Ripley (PLAN.md corrections), Dallas (pre-flight gate documentation)
- **Created session log** 2026-10-08T18:32:44Z-kustomize-migration.md with batch summary
- **Merged three inbox decisions** into `decisions.md`:
  - "Cluster Context Is a Pre-Flight Gate, Not an Assumption" (Dallas)
  - "A Harness Dry Run Is Not Containment Evidence" (Dallas)
  - "Kubernetes workloads move from terraform to kubectl + kustomize" (Parker/Brian/Coordinator)
- **Added Decision #30:** "Every `az` Read Routes Through `tasks/Taskfile.arm.yml`" — Azure CLI output parsing bug found four times; encapsulate all `az` reads with filtering to keep this defect class local to one file
- **Updated agent history.md files:** Parker, Dallas, Ripley with recent work and learnings
- **Deleted inbox files** (gitignored, not part of any branch): dallas-cluster-context-preflight.md, parker-k8s-leaves-terraform.md, ripley-cluster-workloads-not-terraform.md

## Learnings

- **Decisions must be merged from inbox immediately.** Gitignored inbox files are lost permanently if not merged before checkout.
- **Orchestration logs create a permanent record** of agent spawning, rationale, and outcome. One file per spawn; never delete or edit past entries.
- **Session logs are brief summaries** of a batch run; they capture the "what happened and why" in one place, distinct from the detailed agent decisions.


