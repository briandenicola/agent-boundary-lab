# Session Log: Plan Re-gate and Taskfile Evidence Fixes

**Date:** 2026-10-08  
**Session:** Ripley re-gate + Coordinator evidence fixes

## Summary

Three evidence defects fixed in Taskfile and ARM read pipeline, plan re-gated against verified facts.

## Commits

### 4e0a335 — Stop treating a failed ARM read as a confirmed answer
- `az rest | jq` auto-upgrade chatter to stdout reached jq, which failed with an empty return
- Both read sites (app-insights-connection, policies) drew conclusions from empty string
- Fixed: internal `_arm-get` task refuses to return unless jq succeeds, reports failures loudly
- Tested: chatter + valid JSON passes, chatter alone fails, empty account now fails

### 87f3ed3 — Make .env actually reach terraform variables
- Included taskfiles declared overridable settings as `VAR: '{{default X .VAR}}'` in top-level env block
- This clobbered the value the root Taskfile loaded from .env via shell export
- Fixed: read from environment at point of use instead
- Tested: .env supplies value, inline override beats .env, bare defaults still apply

### a23ec2e — Look up account in one place, strip az chatter
- Five tasks repeated account lookup with exposed stdout capture vulnerability
- Moved to `tasks/Taskfile.arm.yml` with gated ARM reader
- Lookup now selects line beginning with `/subscriptions/` instead of trusting whole capture
- Bundled with `docs/PLAN.md` full re-write (seven decisions, three blockers clarified)

## Key Finding (Ripley)

Plan assumed `demo_run_id` reaches platform layer 2 (egress decisions) but never verified it. 
Marker travels in HTTP header; no SDK doc copies it into decision records. Q6 (OperationId propagation test) 
is now GATE 0 and must run first on the first hosted run. If it fails, the evidence model needs rework.
