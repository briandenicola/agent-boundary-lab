# Sections B and C judge a hosted run; they never invoke one

**Author:** Dallas | **Date:** 2026-10-09 | **Status:** implemented, offline-tested only

`verify_demo.py` sections B (audit) and C (enforced) are pure functions of retrieved
rows: egress decision rows (AppDependencies, NetworkEgressDecision) plus receipts, joined
on the run-... id in the path (`/policy/{id}`, `/ingest/{id}`, exact match). Input is
`--*-evidence JSON` or a live log query via `--*-called-at`; `queried_at` is read from the
clock and carried in every result.

- Enforced-denied PASS needs ALL of: Deny + enforcement Enforced row for the run id; no
  receiver receipt; query >= 180 s after the later of call and decision row; receipt log
  readable; no unattributed receipts in window; the permitted call's receipt for the same
  run retrieved in the same query (positive control). Receipt present = FAIL.
- Audit control PASS needs AuditWouldDeny (enforcement Audit) AND a receiver receipt.
  Hard Deny or Allow on the unapproved host in audit = FAIL (control invalid).
- No evidence, wrong run id, ui-... id, naive timestamps, unknown decision codes,
  disagreeing rows: INCONCLUSIVE. Local-labelled runs can never pass.
- Row field locations (Properties.decisionResultCode etc.) follow telemetry-map §0.6.3;
  the live KQL has not been executed. Enforced-mode App Insights egress may be denied
  (§0.10), so absent app rows are expected; decisions still arrive.
- Audit and enforced runs have different run ids: use `--audit-run-id` / `--enforced-run-id`.
