# Session Log: Init Container, Tag Churn, Runbook

**Date:** 2026-10-08  
**Participants:** Parker (2 turns), Dallas (1 turn), Coordinator (cloud:plan validation)  

## Summary

Fixed two critical infrastructure defects exposed by live planning, and delivered Phase 7
verification framework with hard gates.

**Parker Turn 1:** Init container invoked bare `python` but deploy stack lives in isolated venv.
Fixed with absolute interpreter path in variable. Commit b3c60a3.

**Parker Turn 2:** `timestamp()` tag function marked all tagged resources for update on every plan,
destroying plan cleanliness and hiding true infrastructure changes. Removed it. Commit 64371ae.

**Dallas Turn 1:** Wrote `demo-runbook.md` and `evidence-template.md` with embedded rules: NOT
COLLECTED forces inconclusive, observation window is explicit constant, three-state signal model,
mandatory "what this run did NOT prove" section. Commits 1450235 and c3bc181.

**Coordinator:** Ran `task cloud:plan` which confirmed dotenv fix (both Container Apps now plan
to move onto real ACR images) and exposed the tag churn defect. Plan is now clean.

## Team Decisions Merged

- `parker-init-interpreter-absolute.md`
- `parker-no-plan-time-functions.md`
- `dallas-not-collected-and-bounded-window.md`

All three are now in `decisions.md` with no gaps.
