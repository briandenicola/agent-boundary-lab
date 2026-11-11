# 02: Prerequisites

Follow [Before you start](../rebuild-runbook.md#before-you-start) in the deployment
guide for the tool list, Azure access, sign-in, and `.env` setup.

## What the configuration means

| Setting | Purpose |
| --- | --- |
| `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` | Select the Azure directory and billing boundary |
| `POLICY_API_AUTHORIZED_USER_IDS` | Entra object IDs allowed to retrieve policy |
| `TF_VAR_aks_operator_object_ids` | Optional additional cluster operators |
| `HOSTNAME` | Task argument for the public harness URL |
| Image overrides | Leave unset for a fresh environment; builds record their tags |

Task loads `.env` automatically. The file is untracked; commit only placeholders
in `.env.example`. The default region is **Sweden Central**.

Deployment tasks get generated resource names, API URLs, and runtime settings
from Terraform. You do not need to fill every example variable by hand.

## Permissions

Azure resource creation and role assignments are separate permissions.
Contributor alone cannot create role assignments. Entra app registrations and
consent also need directory permissions.

Check model and AKS quota before deployment. Availability in a region does not
guarantee capacity in your subscription. No local Docker daemon is required;
images build in ACR.

## Offline checks

```bash
task lint:venv
task lint:test
task lint:all
```

These are local checks, not Azure deployment or containment tests.
[Dependency contracts](../compatibility.md#runtime)

**Next:** [03: Infrastructure](03-infrastructure.md)
