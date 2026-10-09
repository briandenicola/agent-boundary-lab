# Session Log — Squad Hired, Deployment Unblocked

**Date:** 2026-10-08  
**Requested By:** Brian  
**Status:** Complete

## Agents

- **Parker (Infra)** — 2 turns. Built `infra/k8s/` harness module, `infra/cloud/project-connections.tf` (App Insights connection), moved Container App images to Terraform. Outcome: complete, terraform validates.
- **Brett (Agent Dev)** — 1 turn. Built `src/containment_demo/deploy.py` + `tests/unit/test_deploy.py` (33 tests). Verified azure-ai-projects SDK surface, resolved openai dependency conflict with separate deploy venv. Outcome: complete.
- **Dallas (Verification)** — 2 turns. Built `scripts/verify_demo.py` Section A (now PASSING), receipt absence classifier, test suites. Found and fixed two defects. Outcome: complete, 164 tests passing.
- **Lambert (Telemetry)** — 1 turn. Created `docs/telemetry-map.md`, verified telemetry schema, found App Insights project connection blocker (now unblocked by Parker). Outcome: complete.

## Blockers Resolved

1. **App Insights connection:** Foundry project had zero connections; Layer 2 (platform egress decision) would emit nothing. **UNBLOCKED:** Parker added project connection in Terraform.
2. **Receipt retrievability:** A6 query blocked on table/field verification. **UNBLOCKED:** Lambert verified `ContainerAppConsoleLogs_CL` schema, Dallas implemented query.
3. **Deploy SDK dependency conflict:** `openai>=3` would drift agent's model stack. **RESOLVED:** separate `/opt/deploy-venv` inside image.

## New Blockers Identified

1. **Server-side digest acceptance:** SDK accepts client-side; service behavior unknown. **First hosted run will answer.** See compatibility.md B9a.
2. **RBAC assumption on `agents/versions` write:** `Cognitive Services User` role's `agents/write` wildcard presumed to cover versions (unverified). If 403 on init container, suspect this before federated credential.
3. **Correlation gap (Layer 1 ↔ Layer 2):** Platform not documented to copy run id into egress decision record. **Procedural control:** demo runs strictly serial with timestamps. **First post-deploy action:** run Q6 to test OperationId propagation.
4. **ACTION REQUIRED (Brian):** Add to `.env` before next `cloud:up`:
   ```
   ENDPOINT_IMAGE_TAG=latest
   ```

## Key Decisions Captured

- No `az` CLI in shipped code (tasks/ exempt); Terraform or SDK only. Enforced by `scripts/check_no_az.sh`.
- Two separately-named agents (containment-demo-audit / containment-demo-enforced), not versions.
- Digest pinning with no tag fallback; service refusal → STOP.
- One image tag for both endpoints (cannot drift apart).
- Missing evidence is inconclusive, never pass.
- Init-container contract: `["/opt/deploy-venv/bin/python", "-m", "containment_demo.deploy"]`, `DEMO_*` env vars, no `az`.

## Session Outcome

- Deployment infrastructure complete and validated
- Verification harness Section A now PASS
- All critical technical risks documented
- Readiness: infrastructure ready for hosted deployment; awaiting first run to answer server-side digest question
