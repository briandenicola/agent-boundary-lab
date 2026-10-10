# Rebuild runbook: deploy the whole environment end to end

Written 2026-10-09 from the Taskfiles and the tasks' own prerequisite checks.

**Status: NOT TESTED as one run.** No full teardown and rebuild has ever been executed. Every
step below exists and has been run on its own at some point, but the sequence as a whole, the
timings, and the steps marked **UNVERIFIED** have not. Do not promise a rebuild time. Record
what really happens the first time and correct this page.

Brian runs every step that changes Azure or the cluster. All commands run from the repo root.
Add `--yes` to any task that prompts when you are not on a terminal.

## What `cloud:up` covers, and what it does not

| Covered by Terraform (`infra/cloud`) | NOT covered: separate steps below |
| --- | --- |
| Resource group, VNet, ACR, Log Analytics, Container Apps environment and the two controlled endpoints | The Foundry managed-network **flip** to `AllowOnlyApprovedOutbound` (`task cloud:network-probe`, one PATCH) |
| Foundry account, project, both RAI policies, the `foundry-account-pe` rule | Container images (every `*:build` task) |
| The managed-network FQDN rules (only when `managed_network_isolation_mode` is `AllowOnlyApprovedOutbound`, the default) | Agent versions (published by the harness pod's init container) |
| AKS cluster, role grants for the apps identity, the evidence workbook | Cluster workloads and their secrets (`*:up`, `*:secret`) |
| | The model-access role grant for the two agent identities (`cloud:agent-access-up`) |

State is the local file `infra/cloud/terraform.tfstate`. Losing it orphans the environment.

## Steps

### 1. Infrastructure

| # | Command | Notes |
| --- | --- | --- |
| 1.1 | `task cloud:whoami` | Confirm subscription and tenant first. Read-only. |
| 1.2 | `task cloud:validate` | Local only. |
| 1.3 | `task cloud:plan` | Read the plan. Creates nothing. |
| 1.4 | `task cloud:up` | **Billable** (AKS). Leave `ENDPOINT_IMAGE_TAG` empty: the images do not exist yet, so the Container Apps run a placeholder (see `endpoint_image_tag` in `variables.tf`). |

**UNVERIFIED: managed-network ordering on a fresh account.** The FQDN rules are created by
`cloud:up` while the network is still `AllowInternetOutbound` (the platform's default), and
the flip happens afterwards. Whether ARM accepts FQDN rules before the flip is not known.
Also: on 2026-10-09 creating the three rules in parallel failed with `Conflict` ("has an
ongoing operation running"), and one at a time (`-parallelism=1`) worked. If `cloud:up` hits
that, run `TF_EXTRA='-parallelism=1' task cloud:network-up`, then `cloud:up` again. If ARM
refuses the rules before the flip, set `TF_VAR_managed_network_isolation_mode=AllowInternetOutbound`
for the first `cloud:up`, flip in step 2, then run `cloud:up` again without it.

### 2. Managed network flip (ONE-WAY)

| # | Command | Notes |
| --- | --- | --- |
| 2.1 | `task cloud:network-probe` | One PATCH to `managednetworks/default`. It may print a `TransientError` timeout while the change still lands (it did on 2026-10-09). **Trust the readback it prints**, not the error: `isolationMode` must read `AllowOnlyApprovedOutbound`. |
| 2.2 | `task cloud:network-plan` then `task cloud:network-up` | Creates the FQDN rules and so the billable managed firewall (Standard; cannot change later). Skip if `cloud:up` already created them. Finish with `task cloud:plan`: it must report no changes. |

Going back to `AllowInternetOutbound` means redeploying the account.

### 3. Cluster access

| # | Command | Notes |
| --- | --- | --- |
| 3.1 | `task cloud:kubeconfig` | Run it even if `kubectl` already works. Then confirm you are on OUR cluster: see `demo-runbook.md` §3.0 (P0a to P0c). |

### 4. Images (built in ACR, no local Docker)

Run all of them; none prompts. After the two endpoint images exist, point the Container Apps at them.

```
task build:services            # the two controlled-endpoint images
task build:deploy-endpoints    # CHANGES AZURE: terraform applies the real image tag (prompts)
task build:check-endpoints     # both /healthz answer
task build:agent               # the agent image
task build:agent-digest        # record it: BOTH agent versions must pin this one digest
task a2a:build
task ui:build
task harness:build
task local-model:build
```

### 5. Cluster workloads (each prompts)

Order matters. The tasks refuse to run when a prerequisite is missing, and name it.

| # | Command | Why this position |
| --- | --- | --- |
| 5.1 | `task local-model:up` | The harness refuses to start without the `local-model` service. First start loads a ~2 GB model; allow 1 to 2 minutes. |
| 5.2 | `task ui:secret`, `task ui:up` | `ui:up` creates the `demo-ui` ServiceAccount that the facades reuse. |
| 5.3 | `task a2a:secret`, `task a2a:up` | Needs the `demo-ui` ServiceAccount. The UI and the harness both need `a2a-facade-config`. |
| 5.4 | `task harness:secret`, `task harness:up` | Needs `local-model` and the facade secret. |
| 5.5 | `task cloud:harness-plan`, then `task cloud:harness-up` | Applies the agent harness pod. **Its init container publishes BOTH agent versions**, so this is the step that attaches the two RAI policies to agents. Until it has run, the policies are attached to nothing. |
| 5.6 | `task cloud:harness-status` | The init container must have exited 0. Exit 0 means a version was accepted, not that the policy is enforcing. |

### 6. Agent identity access

| # | Command | Notes |
| --- | --- | --- |
| 6.1 | `task cloud:agent-access-plan`, then `task cloud:agent-access-up` | Grants model access to the two agent identities. It fails with "expected exactly 1 agent identity" until step 5.5 has created the versions. Run it after 5.5, not before. |

**UNVERIFIED:** whether the agents need a restart or a new version after this grant. Until it
is granted the model call fails with a role error (`compatibility.md` B9f).

### 7. Verify

```
task ui:verify
task a2a:verify
task harness:verify
task a2a:send SLOT=audit          # expect get_servicing_policy 200 and send_to_external_processor 202
task a2a:send SLOT=enforced       # expect 200, and the second tool 403
```

Wait at least 3 minutes, then confirm with the platform evidence (the `run-…` id and the UTC time of each call come from the `a2a:send` output):

```
.venv/bin/python scripts/verify_demo.py --section b --audit-run-id <run-…> --audit-called-at <UTC ISO>
.venv/bin/python scripts/verify_demo.py --section c --enforced-run-id <run-…> --enforced-called-at <UTC ISO>
```

Exit 0 is PASS, 1 FAIL, 2 INCONCLUSIVE. Then re-check `task cloud:plan` shows no changes.

## Known rough edges

- **No single "everything" task.** The order above is a human sequence, not automated.
- **The managed-network flip is outside Terraform** (`azapi_update_resource` could not read the
  resource although a plain GET works), so it is a manual step every rebuild.
- **Secrets** are created by `*:secret` and never stored in the repo; a rebuild makes new ones.
  Anything holding an old token (a saved browser login) must use the new one.
- **Tear-down** is `docs/demo-runbook.md` §12. `task cloud:down` deletes everything the module
  created and the local state.
