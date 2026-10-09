# AcrPull for the Foundry PROJECT identity (proposed, not applied)

**By:** Parker, 2026-10-09

- Evidence: `containment-demo-audit:4` get_version = failed, ImageError, "Verify the
  workspace managed identity has AcrPull". AcrPull on the registry is held by 3 principals
  incl. the account identity but not the project identity. The reference repo grants it to
  the project identity.
- Added `azurerm_role_assignment.foundry_project_acr_pull` (acr.tf), principal
  `azapi_resource.project.output.identity.principalId`; the project now exports
  `identity.principalId`. No hardcoded GUID. Plan: 1 to add, 1 to change (export list
  only), 0 to destroy.
- **Account grant: KEPT.** Already applied, harmless, registry-scoped; removing it is a
  change on a theory. Prune it after a version pulls with only the project grant — that is
  the experiment that shows whether it was ever needed.
- **Status: STRONGLY INDICATED, UNVERIFIED** until a version reaches a pulled/running state.
- Record corrected: the 2026-10-08 DISPROVEN label overreached. The poller bug was real AND
  a pull permission is required; `active` is reported at acceptance, before the pull.
- Version LIST showed v4 ACTIVE while get_version showed FAILED: list status is not a
  readiness signal.
