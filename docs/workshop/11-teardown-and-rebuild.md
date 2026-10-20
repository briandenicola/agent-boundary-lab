# Module 11: Teardown and rebuild

**Duration:** about 45 minutes of hands-on time (infrastructure creation and deletion add long unattended waits)

## Objectives

- Tear the environment down safely and in the right order.
- Rebuild from scratch with the exact task sequence, including identity and external ingress.
- Recover the two known first-apply gaps: the managed network import and the ACR managed-network private endpoint.

## Concepts

- **The owner runs every apply and destroy.** Create billable resources and delete environments only with approval. Never touch a production or mixed-purpose RAI policy.
- The AKS cluster is the expensive component. The Foundry managed network, when FQDN rules exist, adds a billable managed firewall (Standard). Isolation mode is one-way.
- PostgreSQL is gated off by default (`enable_state_store = false`).
- Cluster workloads are manifests applied with `kubectl`; they hold no Terraform state and die with the cluster.
- Never delete Terraform state to manufacture a clean result.

## Walkthrough: teardown

Order matters: remove identity objects before the cloud.

| Command | Removes | Leaves behind |
| --- | --- | --- |
| `task foundry-agent:down` | Publishing helper and its whole namespace (chat agent, model server, bridges, UI, Secrets). Prompts first. | The cluster; **already published agent versions stay published** |
| `task identity:destroy` | Probe Job/Secret/ConfigMap/SA, journaled Graph identities, federation, consent, then dedicated identity Terraform/RBAC. No prompt, guarded by journal and context checks | tfvars, redacted evidence, local state, operator-client consent |
| `task app:reset` | `foundry-agent:down` then `identity:destroy` | as above |
| `task chat-agent:external-down` | External ingress and oauth2-proxy; harness returns to legacy token auth | cert-manager, ingress-nginx |
| `task cloud:down` | **Everything** in the demo resource groups, and local Terraform state. Prompts first | kubeconfig entries, `.env`, evidence |

```bash
task identity:destroy
task app:reset            # or foundry-agent:down alone
task cloud:down           # destructive; owner only
```

Notes from the code (verify them before relying on them): `cloud:down` in [`tasks/Taskfile.cloud.yml`](../../tasks/Taskfile.cloud.yml#L949-L962) deletes resource groups found by the demo's `Application` tag with `--no-wait` and removes local Terraform state files. It does **not** itself call `identity:destroy`, so run that first. [`../demo-runbook.md`](../demo-runbook.md) §12 describes a stricter `app:down` flow; that task is not defined in the current Taskfiles, so do not invent it. Record in the evidence template whether the environment was left up and why.

For a lighter cleanup of the probe only: `task identity:down` and `task identity:setup-down` (see [`../identity-probe.md`](../identity-probe.md)).

## Walkthrough: rebuild from scratch

Full source: [`../rebuild-runbook.md`](../rebuild-runbook.md). Status caveat from that document: a clean rebuild was attempted on 2026-10-15 and the corrected Terraform is **not yet verified end to end**. Treat this sequence as the documented procedure, not a proven one.

### 1. Infrastructure

```bash
task cloud:whoami         # confirm subscription and tenant
task cloud:validate       # local only
task cloud:plan           # read it; creates nothing
task cloud:bootstrap      # BILLABLE, first environment only: Foundry account, then imports its managed network
task cloud:up             # BILLABLE: leave ENDPOINT_IMAGE_TAG empty (placeholder images)
task cloud:plan           # must now report no changes
```

If the apply stopped part way: `task cloud:network-import` repairs state ownership of the managed network without changing Azure.

### 2. Managed network and ACR approvals

The Foundry account has its own approved-outbound managed network, separate from the AKS VNet. Hosted agents cold-start only if the managed network can pull from ACR.

1. Read back `managednetworks/default`: `isolationMode` must be `AllowOnlyApprovedOutbound`.
2. The `foundry-account-pe` and `acr-pe` outbound rules must be `Active`, and the ACR connection `Approved`.
3. The account identity needs **Azure AI Enterprise Network Connection Approver** at ACR scope and **Reader** on the registry's resource group. These grants and the `acr-pe` endpoint are now declared in [`managed-network.tf`](../../infra/cloud/managed-network.tf), so a fresh `cloud:up` creates them.
4. If you repaired the endpoint manually in an existing environment, adopt it into state (local only, creates nothing in Azure):

```bash
task cloud:acr-network-import
task cloud:plan
```

Symptom if missing: agent versions fail with generic `ProvisioningError` and the publisher times out ([Module 12](12-troubleshooting.md)). Reference: <https://aka.ms/azureaipeapproval>.

### 3. Cluster access

```bash
task cloud:kubeconfig
```

Confirm you are on **your** cluster before applying anything (P0a to P0c in [`../demo-runbook.md`](../demo-runbook.md)). If kubectl uses a different Entra identity than the Terraform caller, add its object id to the untracked `.env`:

```dotenv
TF_VAR_aks_operator_object_ids='["REPLACE-approved-operator-object-uuid"]'
```

Then `task lint:cloud`, `task cloud:plan`, `task cloud:up`.

### 4. Build images in ACR (no local Docker)

```bash
task build:all           # seven images; builds in Azure and costs money
```

Keep `IMAGE_TAG` and `ENDPOINT_IMAGE_TAG` consistent between build and deploy. After the tool APIs are built and deployed, keep `ENDPOINT_IMAGE_TAG` equal to that tag so a later `cloud:up` does not roll them back.

### 5. Deploy applications (app:deploy from scratch)

Either individual steps or the aggregate:

```bash
task lint:tasks
task deploy:all          # tool APIs, Foundry agent versions, model server, UI, bridge, chat agent
```

Equivalent one-shot combos in [`tasks/Taskfile.app.yml`](../../tasks/Taskfile.app.yml#L14-L30):

```bash
task app:deploy                                                   # cloud:up + deploy:app-components
task app:deploy-external HOSTNAME=<fqdn> LETSENCRYPT_EMAIL=<ops-email>   # from scratch, plus external HTTPS + Entra login
```

Order if you go step by step: `deploy:tool-apis`, `deploy:foundry-agent`, `deploy:model-server`, `deploy:test-ui`, `deploy:agent-bridge`, `deploy:chat-agent`. `deploy:*` has no confirmation prompts. Existing Secrets are kept unless `ROTATE=1`, so a rebuild creates new tokens and any saved browser login must use the new one.

### 6. Identity

```bash
task identity:validate    # strict offline preflight, no sign-ins
task identity:up          # rerunnable: setup journal, both test users, probe
task identity:status      # latest redacted result
```

Graph operator sign-in and consent stay interactive.

### 7. External harness (DNS, certificate, Entra login)

If you did not use `app:deploy-external`, run `chat-agent:external-prereqs`, create or **update the DNS `A` record** to the new ingress-nginx public IP, then `chat-agent:external-bootstrap` ([Module 07](07-external-access.md)). A rebuild creates a new load balancer, so the old record points nowhere and the certificate cannot be issued until it is updated.

### 8. Verify

```bash
task app:status
task test-ui:verify
task agent-bridge:verify
task chat-agent:verify
task agent-bridge:send SLOT=audit      # expect get_servicing_policy 200, send_to_external_processor 202
task agent-bridge:send SLOT=enforced   # expect 200 and the second tool 403
```

Wait 3 minutes, then run `scripts/verify_demo.py` sections B and C ([Module 09](09-run-and-verify.md)). Finish with `task cloud:plan` reporting no changes. Regional eligibility (Sweden Central is the owner-approved target) is covered in the runbook.

## Code tour

| What | Where |
| --- | --- |
| Rebuild steps and recoveries | [`../rebuild-runbook.md`](../rebuild-runbook.md) |
| bootstrap / network-import / acr-network-import | [`tasks/Taskfile.cloud.yml` L129-L200](../../tasks/Taskfile.cloud.yml#L129-L200) |
| Managed network and ACR endpoint | [`infra/cloud/managed-network.tf`](../../infra/cloud/managed-network.tf) |
| Deployment sequencing | [`tasks/Taskfile.deploy.yml` L11-L110](../../tasks/Taskfile.deploy.yml#L11-L110) |
| Teardown | [`tasks/Taskfile.cloud.yml` L949-L962](../../tasks/Taskfile.cloud.yml#L949-L962), [`tasks/Taskfile.identity.yml` L44](../../tasks/Taskfile.identity.yml#L44) |

## Checkpoint

- [ ] You can explain why `identity:destroy` runs before `cloud:down`.
- [ ] After a rebuild, both agent versions are `active` with one digest and `cloud:plan` is clean.
- [ ] Both verifier sections returned PASS or an honest INCONCLUSIVE with a reason.

**Next:** [Module 12: Troubleshooting](12-troubleshooting.md)
