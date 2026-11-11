# Module 11: Teardown and rebuild

The steps live in the [deployment guide](../rebuild-runbook.md): [deploy](../rebuild-runbook.md#part-1-aks-and-foundry-demo) and [cleanup](../rebuild-runbook.md#cleanup). This module explains why they are ordered the way they are.

## What holds state

- **Terraform state** covers the Azure foundation. Don't delete it to get a clean result.
- **Cluster workloads** are plain manifests. They hold no Terraform state and disappear with the cluster.
- **Entra registrations, DNS and Microsoft 365 catalog entries** live outside the resource groups, so `cloud:down` doesn't remove them.
- **AKS** is the main cost. Foundry's managed network adds a managed firewall when FQDN rules exist, and isolation mode can't be reversed.

## Why the order matters

- Remove the OAuth extension before the shared helper it depends on.
- Remove external identity before the infrastructure, because it needs the cluster and registrations to clean up properly.
- `cloud:down` deletes every resource group tagged with the lab and clears local state without waiting for Azure. Anything that needed guarded cleanup must go first.
- Never touch the AKS node resource group.

## What changes on a rebuild

- A new cluster gets a new ingress load balancer, so the DNS A record must be updated or the certificate can't be issued.
- Secrets are regenerated, so saved browser logins need the new token.
- Images are tagged from git and never `latest`. Each build records its tag for the deploy tasks.
- The Foundry managed network is created with the account and imported into Terraform state by `cloud:bootstrap`. If an apply stops partway, `task cloud:network-import` repairs it.
- Hosted agents only start if the managed network can pull from ACR. That needs the `acr-pe` outbound rule, an approved connection, the Enterprise Network Connection Approver role at ACR scope and Reader on its resource group. [`managed-network.tf`](../../infra/cloud/managed-network.tf) declares all of it. If you created the endpoint by hand, run `task cloud:acr-network-import` before the next plan. Reference: <https://aka.ms/azureaipeapproval>.
- If `kubectl` uses a different Entra identity than Terraform, add its object ID to `TF_VAR_aks_operator_object_ids` in `.env`.

## Check yourself

1. Why does external identity cleanup run before `cloud:down`?
2. After a rebuild, what two things confirm the new environment is sound? (Both agent versions active on one digest; `cloud:plan` reports no changes.)

**Next:** [12 Troubleshooting](12-troubleshooting.md)
