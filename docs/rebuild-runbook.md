# Rebuild runbook: deploy the whole environment end to end

Written 2026-10-09 from the Taskfiles and the tasks' own prerequisite checks.

**Status: clean rebuild attempted 2026-10-15; not yet verified end to end.** Infrastructure
creation exposed image/state/order failures, then hosted-agent provisioning failed until
an ACR private endpoint was added to Foundry's managed network (recovery below). Both
hosted versions subsequently reported `active`. The corrected Terraform has not yet been
tested through another full teardown/rebuild, nor has the aggregate application deployment
and containment verification completed on this environment.

Brian runs every step that changes Azure or the cluster. All commands run from the repo root.
Add `--yes` to any task that prompts when you are not on a terminal.

## What `cloud:up` covers, and what it does not

| Covered by Terraform (`infra/cloud`) | NOT covered: separate steps below |
| --- | --- |
| Resource group, VNet, ACR, Log Analytics, Container Apps environment and the two controlled endpoints | |
| Foundry account, project, both RAI policies, the `foundry-account-pe` and `acr-pe` managed-network rules and their permission grants | Container images (`build:<component>`, `build:all`) |
| The managed network (`AllowOnlyApprovedOutbound`) and its FQDN rules (only when `managed_network_isolation_mode` is `AllowOnlyApprovedOutbound`, the default) | Agent versions (published by `deploy:foundry-agent`) |
| AKS cluster, role grants for the apps identity, the evidence workbook | Applications and their Secrets (`deploy:<component>`, `deploy:all`) |
| | Agent model-access grants (included in `deploy:foundry-agent`) |

State is the local file `infra/cloud/terraform.tfstate`. Losing it orphans the environment.

## Single-tenant rebuild for issue #4 (owner-directed 2026-10-19)

The owner chose one tenant for Agent ID, Foundry, AKS and all supporting resources.
No cross-tenant integration is planned. The owner handles the old environment's teardown
and state removal and reported state removal complete. Azure teardown has not yet been
confirmed; the assistant has not performed or verified either operation. Complete teardown
before discarding its state. Do not point the old environment's state at the new subscription.

After the owner confirms teardown/state removal, configure the approved target in the
untracked `.env`:

```dotenv
ARM_TENANT_ID=REPLACE-approved-deployment-tenant-uuid
ARM_SUBSCRIPTION_ID=REPLACE-approved-deployment-subscription-uuid
```

Use the tenant in which the owner verified the Agent ID lifecycle and the subscription
selected for that tenant. Actual IDs stay in local configuration, not this runbook.
Sign in and select that subscription yourself:

```bash
az login --tenant <approved-tenant-id>
az account set --subscription <approved-subscription-id>
task cloud:target-check
```

The check is read-only: active tenant, subscription and Enabled state must match both
configured values. `cloud:plan`, `cloud:bootstrap` and `cloud:up` run it before provider
initialization or provisioning; it never changes login or chooses a fallback subscription.
It does not validate quota, regional feature availability, or prove old state was removed.

Review the fresh environment configuration before following Steps 1-5 below. Clear stale
`ENDPOINT_IMAGE_TAG` and old explicit image-digest overrides for this fresh registry;
use placeholder endpoints until its images are built. Do not reuse old resource URLs,
identity IDs or kubeconfig as new-environment inputs. The existing region is only a
configuration default, not verified availability in the new subscription.

This rebuild establishes the private containment baseline, not completion of issue #4.
Next prove the delegated Foundry bearer in the same tenant (I0), then implement the
owner-selected HTTPS/login architecture and downstream policy-token transport.
Public ingress, identity grants and enabling policy authentication need separate review.

## Steps

### 1. Infrastructure

| # | Command | Notes |
| --- | --- | --- |
| 1.1 | `task cloud:whoami` | Confirm subscription and tenant first. Read-only. |
| 1.2 | `task cloud:validate` | Local only. |
| 1.3 | `task cloud:plan` | Read the plan. Creates nothing. |
| 1.3a | `task cloud:bootstrap` | **Billable.** First environment only: creates the Foundry account and dependencies, then imports its platform-created managed network. This targeted apply is only the bootstrap; the full apply still follows. |
| 1.4 | `task cloud:up` | **Billable** (AKS). Leave `ENDPOINT_IMAGE_TAG` empty: the images do not exist yet, so the Container Apps run a placeholder (see `endpoint_image_tag` in `variables.tf`). |

**The managed network is part of `cloud:up`.** `azapi_resource.managed_network` declares
`managednetworks/default` with `isolationMode = AllowOnlyApprovedOutbound` (the default of
`managed_network_isolation_mode`), so there is no separate flip step. The three FQDN rules depend
on it. Isolation mode is one-way, and the FQDN rules create the billable managed firewall
(Standard). The resource retries on `TransientError` and "ongoing operation" (both seen on
2026-10-09).

**Observed failure (2026-10-15, owner-provided apply output):** Azure creates
`managednetworks/default` with the account. AzAPI refuses to create it again and requires an
import. Re-running the same apply does not fix missing state ownership. `cloud:bootstrap`
handles that first-account boundary; `cloud:network-import` repairs an existing partial apply
without changing Azure. Both derive the account from this local Terraform state, not a
tag-based search or a hardcoded resource ID.

**Recovery implementation; owner reported `cloud:up` succeeded on 2026-10-15:** account child resources now share an AzAPI account
lock and retry the observed operation-in-progress messages. The project also waits for the
AzureRM model deployment, which does not participate in AzAPI locks. Authentication, schema
errors, and unrelated conflicts are not retried by this custom rule. The existing managed
network `TransientError` retry remains. A full rebuild with these changes is still untested.
`task cloud:network-probe` remains a manual fallback PATCH, not a substitute for importing
the managed network. To opt out of approved-only isolation, set
`TF_VAR_managed_network_isolation_mode=AllowInternetOutbound` before the first apply.

### Recover the reported partial apply

Keep the existing state and resources. Run from the repo root, one command at a time:

```bash
task lint:cloud
task cloud:network-import
IMAGE_TAG=5f24f8e task build:tool-apis
task cloud:plan
task cloud:up
```

The build publishes both missing endpoint images into the ACR recorded by this state.
Keep `ENDPOINT_IMAGE_TAG=5f24f8e` for the plan and apply; if choosing another tag, build that
tag and set `ENDPOINT_IMAGE_TAG` to match. Do not clear the tag on an already functioning
environment: that explicitly selects placeholder images.

`cloud:up` and `deploy:tool-apis` check both requested image tags before starting
their apply. An unreadable registry, missing image, or invalid digest response stops the
task rather than deploying a fallback. An empty endpoint tag is allowed only as the
explicit placeholder selection. `cloud:up`, `cloud:network-up`, and
`deploy:tool-apis` also stop if the default managed network has not been imported.

The shared preflights resolve Terraform's directory as `{{.ROOT_DIR}}/infra/cloud`, not
relative to the included Taskfile's working directory or an inherited `CLOUD_DIR`. A
`chdir ./infra/cloud: no such file or directory` failure in the old preflight is a local
path-resolution error, not evidence that the Azure environment needs bootstrapping.

The `parent_id` deprecation warnings on federated credentials are separate from these
failures; this recovery does not change those credentials.

Provider references checked **2026-10-15** (configuration guidance, not deployed evidence):

- [AzAPI resource: locks, retry, import](https://registry.terraform.io/providers/Azure/azapi/latest/docs/resources/resource).
- [AzAPI 2.13.0 source documentation](https://github.com/Azure/terraform-provider-azapi/blob/v2.13.0/docs/resources/resource.md).

### 2. Check the managed network

| # | Command | Notes |
| --- | --- | --- |
| 2.1 | `task cloud:plan` | Must report no changes after `cloud:up`. |
| 2.2 | Read back `managednetworks/default` | `isolationMode` must read `AllowOnlyApprovedOutbound`; trust the readback over any timeout message. |
| 2.3 | Check the `foundry-account-pe` and `acr-pe` outbound rules | Both must be `Active`; ACR must show the managed-network private-endpoint connection `Approved`. The ACR endpoint in our AKS VNet is a different connection. |

### Recover the ACR managed-network gap observed 2026-10-15

**Observed:** Audit versions 1-4 failed with generic `ProvisioningError`; the publisher
repeatedly timed out while versions were `creating`. AKS pulled the same image and reached
Foundry through its private endpoint, but Foundry's separate approved-only managed network
had no registry private endpoint or explicit registry allow rule. The original working
agents were provisioned before outbound isolation was tightened; that sequence did not
exercise this cold-start configuration.

With owner approval, the following were created using Azure CLI:

- Account managed identity: **Azure AI Enterprise Network Connection Approver** at ACR scope.
- Same identity: **Reader** at the registry's resource-group scope. Endpoint creation was
  still rejected without this ACR-specific prerequisite.
- `acr-pe`: managed-network `PrivateEndpoint` rule targeting this ACR's `registry`
  subresource. This is not another endpoint in the AKS VNet.

At **2026-10-15 22:34:50 UTC**, the rule read `Active` and the ACR connection `Approved`.
After restarting only the existing publisher pod, Audit v5 read `active`; Enforced v1 was
created at 22:35:54 UTC and became `active` after 36.8 seconds. SDK GETs confirmed both used
`sha256:1952a5b88a52eb124a81593a3fa451ee5a7dca032ead60d7627b3d5eee359370` and their
unchanged Audit/Enforced RAI policies. No image rebuild, RAI change, or timeout increase
was used. This verifies provisioning recovery, **not** tool execution or containment.

The endpoint and grants are now declared in `managed-network.tf`; a fresh environment
creates them during `cloud:up`. The endpoint depends on both grants and narrowly retries
the observed RBAC-propagation error. `network-plan`/`network-up` include both managed
private endpoints and their prerequisite grants.

**For the environment repaired manually above, import before any plan/apply/deployment:**

```bash
task cloud:acr-network-import
task cloud:plan
```

The import changes **local Terraform state only**. It derives the account, registry and
resource group from that state, discovers the existing grants for that account identity,
and skips resources already managed. It creates no Azure resources or grants. If the
endpoint/grants do not exist, do not use this recovery import; review `cloud:plan` for
their normal creation instead. Do not blindly apply unrelated policy drift. Until the
import runs, the successful manual changes are still outside Terraform state.

Approval prerequisite reference, accessed **2026-10-15**:
[the guide linked by Azure's actual creation error](https://aka.ms/azureaipeapproval),
section "Approval of private endpoints" (including the ACR resource-group Reader note).

### 3. Cluster access

| # | Command | Notes |
| --- | --- | --- |
| 3.1 | `task cloud:kubeconfig` | Run it even if `kubectl` already works. Then confirm you are on OUR cluster: see `demo-runbook.md` §3.0 (P0a to P0c). |

### 4. Images (built in ACR, no local Docker)

```bash
task build:all
```

This builds **seven images**, deploying nothing. All builds run in ACR and incur build
cost. The model-server build retains its confirmation prompt for the large image.
If all images were already built with the old commands, **skip this step**.

Image tag behaviour is unchanged. `IMAGE_TAG` selects the foundry-agent and tool-apis tag;
`A2A_IMAGE_TAG` selects agent-bridge, `HARNESS_IMAGE_TAG` selects chat-agent,
`LOCAL_MODEL_IMAGE_TAG` selects model-server and `UI_IMAGE_TAG` selects test-ui. Each defaults
independently to `latest`. Keep the same values for build and deploy. An explicit
`*_IMAGE_DIGEST` deployment pin takes precedence over tag lookup. Both Foundry versions
always receive one identical digest. Command changes do not rename images or resources.

### 5. Deploy applications

Validate the new command wiring locally first, then deploy:

```bash
task lint:tasks
task deploy:all
```

`deploy:all` requires completed infrastructure and the kubeconfig context named for the
Terraform AKS cluster. It does **not** call `cloud:up` or any build. Existing prompts remain;
`--yes` explicitly accepts them for noninteractive use. The sequence is:

| Order | Build command | Deploy command | Meaning and dependencies |
| --- | --- | --- | --- |
| 1 | `build:tool-apis` | `deploy:tool-apis` | Policy API and test receiver on Container Apps. Check image availability, plan Terraform, allow only updates to these two existing apps, apply that saved plan, check health. |
| 2 | `build:foundry-agent` | `deploy:foundry-agent` | Publish both same-digest Foundry versions through the AKS helper; wait up to 600 s for its rollout, then grant both agent identities model access. |
| 3 | `build:model-server` | `deploy:model-server` | Deploy the CPU Qwen/llama.cpp server. First start loads a roughly 2 GB model. |
| 4 | `build:test-ui` | `deploy:test-ui` | Create/preserve the bridge and UI Secrets **before** applying the two-button page and its shared `demo-ui` ServiceAccount. |
| 5 | `build:agent-bridge` | `deploy:agent-bridge` | Deploy both A2A-to-Responses bridge slots; requires the test UI's ServiceAccount. |
| 6 | `build:chat-agent` | `deploy:chat-agent` | Create/preserve its Secret and deploy browser chat plus the agent loop; requires the model Service and bridge. |

Prefix commands in the table with `task`. Each AKS deploy ensures the namespace exists.
Individual deploy commands prepare their own Secrets, but do not automatically deploy other
components. On a fresh cluster, follow the table order or use `deploy:all`.
Existing Secrets are preserved unless `ROTATE=1` is explicitly set.

The `agent-harness` Deployment is the **Foundry publishing helper**, not the `chat-agent`.
Its init container publishes versions; its main container sleeps. `harness` remains the
underlying Kubernetes name of the actual chat service. These resources are not renamed.
`task foundry-agent:status` shows the publisher logs. A successful init means versions were
accepted, **not** that containment was proven.

Keep `ENDPOINT_IMAGE_TAG` in `.env` equal to the tool API `IMAGE_TAG` after deployment, so a
later `cloud:up` does not roll them back. If `deploy:tool-apis` detects infrastructure drift,
it stops **without applying**. Review `task cloud:plan` and reconcile that separately.

### 6. Access and compatibility notes

`deploy:foundry-agent` includes the existing `cloud:agent-access-up` operation, after the
publisher is ready. It grants Cognitive Services OpenAI User to both agent identities at
the same scope. These are workload model-access grants, **not** the user OBO extension in
#4. That identity extension remains planning-only.

**UNVERIFIED:** whether newly granted model access needs propagation time, a restart or a
new version. A successful grant alone does not prove a model call succeeds (B9f).

Old commands remain compatibility aliases: `build:agent`, `build:services`,
`build:agent-digest`, `build:deploy-endpoints`, and the `a2a`, `harness`, `local-model`
and `ui` namespaces. Use `build:<component>` / `deploy:<component>` for new instructions.
Low-level legacy `*:up` commands retain their original prerequisite checks; the new
`deploy:*` commands add Secret preparation and sequencing.

### 7. Verify

```
task test-ui:verify
task agent-bridge:verify
task chat-agent:verify
task agent-bridge:send SLOT=audit          # expect get_servicing_policy 200 and send_to_external_processor 202
task agent-bridge:send SLOT=enforced       # expect 200, and the second tool 403
```

Wait at least 3 minutes, then confirm with the platform evidence (the `run-…` id and the UTC time of each call come from the `agent-bridge:send` output):

```
.venv/bin/python scripts/verify_demo.py --section b --audit-run-id <run-…> --audit-called-at <UTC ISO>
.venv/bin/python scripts/verify_demo.py --section c --enforced-run-id <run-…> --enforced-called-at <UTC ISO>
```

Exit 0 is PASS, 1 FAIL, 2 INCONCLUSIVE. Then re-check `task cloud:plan` shows no changes.

## Known rough edges

- **Aggregate deployment is not yet run end to end.** The 2026-10-15 clean attempt recovered
  hosted-agent provisioning after adding the missing managed-network ACR path. A complete
  teardown/rebuild of the corrected configuration and a containment result remain unverified.
- **`cloud:plan` showed the two RAI policies updating in place on 2026-10-10** (contentFilters),
  with no policy change on our side; `task cloud:policies` showed them still identical apart from
  `egressPolicy.mode`. Unexplained. Read the plan before any `cloud:up`; do not apply it blind.
- **Secrets** are created by `*:secret` and never stored in the repo; a rebuild makes new ones.
  Anything holding an old token (a saved browser login) must use the new one.
- **Tear-down** is `docs/demo-runbook.md` §12. `task cloud:down` deletes everything the module
  created and the local state.
