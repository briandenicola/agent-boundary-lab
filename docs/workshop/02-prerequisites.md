# Module 02 — Prerequisites

Before you create anything billable you need the right tools, the right Azure permissions, and a `.env` file that tells the Taskfiles which tenant and subscription they may touch. This module gets you to a green offline check with no Azure resources created.

## Objectives

1. Install the local toolchain and verify each tool.
2. Understand which Azure accounts, roles and quotas the lab needs.
3. Create `.env` from [.env.example](../../.env.example) and understand every variable group.
4. Pin the region (Sweden Central) and know why.
5. Run the offline checks (`task lint:*`) that need no Azure access.

## Concepts

| Term | Meaning |
| --- | --- |
| **Tenant** | Your organisation's **Microsoft Entra** directory (Entra ID, formerly Azure AD): the identity system holding users, groups and workload identities. |
| **Subscription** | The billing and quota boundary inside a tenant. Everything Terraform creates lands in one subscription. |
| **Resource group** | A folder-like container for Azure resources; the lab creates one ([locals.tf lines 70–75](../../infra/cloud/locals.tf)). |
| **RBAC role assignment** | A grant of a role (e.g. `AcrPull`) to a principal at a scope. Most lab "permissions" are role assignments. |
| **Managed identity** | A workload identity Azure issues and rotates. The lab uses *user-assigned* ones plus the system-assigned identities of the Foundry account, project and AKS cluster. No client secrets. |
| **Quota** | A per-subscription, per-region cap (e.g. vCPUs, model capacity). A deploy can fail on quota even with correct permissions. |
| **Task** | [Task](https://taskfile.dev), a YAML task runner. All lab commands are `task <namespace>:<target>`. |
| **Terraform / AzAPI** | Infrastructure as code. The `azapi` provider is used for preview Foundry resources that the `azurerm` provider cannot express ([providers.tf](../../infra/cloud/providers.tf)). |

## Walkthrough

### 1. Install tools

| Tool | Used for | Evidence in repo |
| --- | --- | --- |
| [Task](https://taskfile.dev) | Every lab command | [Taskfile.yml](../../Taskfile.yml) |
| Azure CLI (`az`) | Sign-in, target check, ACR builds, tenant/subscription selection | `target-check` in [Taskfile.cloud.yml](../../tasks/Taskfile.cloud.yml) |
| Terraform `>= 1.0` | Provision infra | [providers.tf line 10](../../infra/cloud/providers.tf) |
| Python 3.12 and [`uv`](https://docs.astral.sh/uv/) | Local venv, unit tests | `requires-python = ">=3.12,<3.13"` in [pyproject.toml](../../pyproject.toml); `venv` in [Taskfile.lint.yml](../../tasks/Taskfile.lint.yml) |
| `kubectl`, `kubelogin` | AKS access (Entra-authenticated) | `_require-kubectl`, `_require-kubelogin` in [Taskfile.cloud.yml](../../tasks/Taskfile.cloud.yml) |
| `jq` | Task scripts parse JSON | `target-check`, `lint:tasks` |
| `kustomize` | Offline manifest check (`lint:manifests`); also renders the external ingress (`chat-agent:external-render`) | [Taskfile.lint.yml line 98](../../tasks/Taskfile.lint.yml), [Taskfile.harness.yml](../../tasks/Taskfile.harness.yml) |
| `helm` | Installs ingress-nginx and cert-manager for the external harness (Module 07) | `external-prereqs` in [Taskfile.harness.yml](../../tasks/Taskfile.harness.yml) |
| `openssl` | Generates the oauth2-proxy cookie secret | `external-app` in [Taskfile.harness.yml](../../tasks/Taskfile.harness.yml) |
| `dig` or `nslookup` | Verifies your DNS record before requesting a certificate | Module 07 |

Docker is **not** required: images are built inside Azure Container Registry (`task build:*`, "no local Docker" per [rebuild-runbook.md](../rebuild-runbook.md)).

```bash
task --version && az version -o tsv --query '"azure-cli"' && terraform version | head -1
uv --version && kubectl version --client | head -1 && kubelogin --version | head -1
jq --version && kustomize version
```

Exact pinned versions of the Python stack (ADK, agentserver, LiteLLM) are in [compatibility.md](../compatibility.md); `uv.lock` pins the resolution.

### 2. Accounts and permissions

| Need | Why | Source |
| --- | --- | --- |
| An Azure subscription you are explicitly approved to bill | Cloud tasks refuse to run without `ARM_TENANT_ID`/`ARM_SUBSCRIPTION_ID` | `target-check` |
| Rights to create resources **and** role assignments in it | Terraform declares 17 `azurerm_role_assignment` blocks (identity.tf, acr.tf, aks.tf, managed-network.tf, demo-ui-identity.tf). Contributor alone cannot write role assignments; an Owner or User Access Administrator-capable role is the usual answer. *(Inference from the resources, not a tested minimum.)* | [identity.tf](../../infra/cloud/identity.tf) |
| Quota for the model | `gpt-5.4-mini` / `2026-03-17` / `GlobalStandard`, capacity 30 | [model-deployments.tf](../../infra/cloud/model-deployments.tf), [variables.tf](../../infra/cloud/variables.tf) |
| vCPU quota for AKS nodes | Default `Standard_D4as_v7`, 2 nodes, autoscale to 4 | [aks.tf lines 58–69](../../infra/cloud/aks.tf) |
| Access to Foundry hosted agents and the preview egress API in the region | Preview features; if unavailable mark work **BLOCKED** | [egress-control.md](../egress-control.md) |

The Terraform caller automatically receives AKS cluster admin, ACR push and Foundry user roles ([aks.tf lines 111–121](../../infra/cloud/aks.tf), [acr.tf lines 92–97](../../infra/cloud/acr.tf), [identity.tf lines 111–126](../../infra/cloud/identity.tf)). Extra operators go in `TF_VAR_aks_operator_object_ids`.

For the external, Entra-protected harness (Module 07) you also need:

| Need | Why | Source |
| --- | --- | --- |
| **A public domain you control** and rights to create one DNS record in it | The harness is served at `https://<fqdn>`; you point an `A` record at the cluster's public IP. The lab does not create DNS for you. | [Module 07](07-external-access.md) |
| An email address for Let's Encrypt | Passed as `LETSENCRYPT_EMAIL`; used for the ACME account and expiry notices | [clusterissuer.yaml](../../deploy/kustomize/harness-external/clusterissuer.yaml) |
| Inbound **TCP 80 and 443** reachable from the internet to the AKS public load balancer | 443 serves the harness; 80 is required for the Let's Encrypt HTTP-01 challenge | [clusterissuer.yaml](../../deploy/kustomize/harness-external/clusterissuer.yaml) (`http01` solver) |
| Rights to create an **app registration and service principal** in the tenant | `external-app` runs `az ad app create` / `az ad sp create`. *(Inference: Application Developer or equivalent; not a tested minimum.)* | `external-app` in [Taskfile.harness.yml](../../tasks/Taskfile.harness.yml) |
| At least two Entra test users in the same tenant | One allowed user and one denied user for the demo (Module 04, Module 09) | [04-identity.md](04-identity.md) |

Sign in and select the target:

```bash
az login --tenant <your-tenant-id>
az account set --subscription <your-subscription-id>
```

### 3. Create `.env`

```bash
cp .env.example .env
```

The root Taskfile loads it (`dotenv: ['.env']` in [Taskfile.yml](../../Taskfile.yml)). **Placeholders only in git; `.env` is yours.** Variable groups:

| Group | Variables | Explanation |
| --- | --- | --- |
| **Operator target** | `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` | Required before `cloud:plan`/`bootstrap`/`up`. `task cloud:target-check` compares them with `az account show` and aborts on mismatch. Set these first. |
| **AKS operators** | `TF_VAR_aks_operator_object_ids` | Optional JSON array of Entra **object IDs** (not app/client IDs) for extra cluster admins. |
| **Business destinations** | `DEMO_POLICY_API_URL`, `DEMO_TEST_RECEIVER_URL` | Two distinct `https` hosts. The policy API host is allowlisted; the receiver is not. After Module 03 these are Terraform outputs; placeholders are fine until then. |
| **HTTP behaviour** | `DEMO_HTTP_TIMEOUT_SECONDS` | Bounded tool timeout (default 10). |
| **Evidence label** | `DEMO_POLICY_MODE` (`local`\|`audit`\|`enforced`), `DEMO_DEMO_RUN_ID` | Labels only: nothing in the app branches on it. The run id correlates agent, platform and endpoint evidence. |
| **Model** | `DEMO_MODEL_DEPLOYMENT`, `DEMO_AZURE_OPENAI_ENDPOINT`, `DEMO_AZURE_OPENAI_API_VERSION` | Deployment name must match Terraform `var.model_name`. |
| **Diagnostics** | `DEMO_DIAGNOSTICS_ENABLED`, `DEMO_DIAGNOSTICS_TOKEN` | Authenticated route that reuses the same two tools. Token must be ≥16 chars; there is no unauthenticated mode. Terraform generates one ([random.tf lines 41–44](../../infra/cloud/random.tf)). |
| **Telemetry** | `APPLICATIONINSIGHTS_CONNECTION_STRING` | Only outside the hosted runtime. |
| **Agent deploy** | `DEMO_FOUNDRY_ACCOUNT_NAME`, `DEMO_FOUNDRY_PROJECT_NAME`, `DEMO_AGENT_IMAGE`, `DEMO_AGENT_NAME_AUDIT/ENFORCED`, `DEMO_RAI_POLICY_AUDIT_ID`, `DEMO_RAI_POLICY_ENFORCED_ID`, `DEMO_AGENT_*`, `DEMO_DEPLOY_*` | Read only by the in-VNet deploy job. Image must be a **digest**, policy ids must be full ARM ids. All come from Terraform outputs ([outputs.tf](../../infra/cloud/outputs.tf)). |
| **Image tags** | `IMAGE_TAG`, `ENDPOINT_IMAGE_TAG`, `*_IMAGE_TAG` | Leave `ENDPOINT_IMAGE_TAG` **unset** until `task build:tool-apis` has pushed the images; set it afterwards or `cloud:up` rolls the endpoints back to a placeholder. |
| **External harness** | `LETSENCRYPT_EMAIL`, `TENANT_ID`, `OIDC_APP_NAME`, `ROTATE_OIDC_SECRET` | Read by `external-*` tasks and `app:deploy-external`. `TENANT_ID` defaults to the `az` tenant; `OIDC_APP_NAME` defaults to `agent-boundary-harness-oidc`; `ROTATE_OIDC_SECRET=1` issues a new client secret on the next run. |
| **External hostname** | `HOSTNAME` (Task variable) | **Pass it on the command line**: `task app:deploy-external HOSTNAME=<fqdn> LETSENCRYPT_EMAIL=<email>`. `.env.example` also lists `EXTERNAL_HOSTNAME`, but no task reads it today. |
| **Diagnostics links** | `HARNESS_WORKBOOK_URL`, `HARNESS_LOGS_URL`, `HARNESS_APPINSIGHTS_URL` | Optional deep links shown in the harness UI. Applied by `task chat-agent:secret` ([Module 06](06-build-and-deploy.md)). |
| **Opt-in identity probe (issue #4)** | `IDENTITY_*`, `POLICY_API_*` | Commented out; the I0 probe is not required for the external demo. See [identity-probe.md](../identity-probe.md). |

Never put real secrets in `.env.example`; runtime credentials use managed identity. Synthetic data only.

### 4. Region

The root Taskfile sets `DEFAULT_REGION: swedencentral` ([Taskfile.yml line 15](../../Taskfile.yml)) and Terraform `var.region` defaults to the same ([variables.tf line 15](../../infra/cloud/variables.tf)). Use the tasks without a region argument. Sweden Central was chosen by the owner for the rebuild; eligibility checks (VM size, hosted-agent availability, model quota) and their limits are in [rebuild-runbook.md](../rebuild-runbook.md#sweden-central-rebuild-defaults-approved-2026-10-19). Those checks show **advertised** support, not live capacity.

### 5. Offline verification (no Azure)

```bash
task lint:venv
task lint:test
task lint:terraform
task lint:cloud
task lint:tasks
```

`lint:venv` builds `.venv` with `uv`; `lint:test` runs `tests/unit` with no credentials or network; `lint:terraform` runs `terraform fmt -check` and `validate` with `-backend=false` ([Taskfile.lint.yml lines 70–82](../../tasks/Taskfile.lint.yml)). `lint:all` bundles the local checks.

```bash
task cloud:target-check      # after az login; read-only
```

```text
Azure CLI matches the configured deployment tenant and subscription.
```

## Code tour

| Read | Why |
| --- | --- |
| [Taskfile.yml](../../Taskfile.yml) | Namespaces, `dotenv`, default region |
| [Taskfile.cloud.yml lines 47–67](../../tasks/Taskfile.cloud.yml) | `whoami` and `target-check` |
| [settings.py](../../src/containment_demo/settings.py) | `DEMO_` prefix, validators for distinct HTTPS hosts and the diagnostics token |
| [variables.tf](../../infra/cloud/variables.tf) | Every Terraform input and default |
| [providers.tf](../../infra/cloud/providers.tf) | Provider pins; `ARM_*` env vars select the target |

## Checkpoint

1. What stops `task cloud:up` from deploying into the wrong subscription?
2. Why must `DEMO_AGENT_IMAGE` be a digest?
3. Why is `ENDPOINT_IMAGE_TAG` left unset on the first apply?
4. Does a green `task lint:terraform` show the Foundry preview API accepts your configuration?
5. Do you need Docker locally?
6. Which two things must you own before the external harness can work, besides the Azure subscription?

<details><summary>Answers</summary>

1. `cloud:target-check` compares `ARM_TENANT_ID`/`ARM_SUBSCRIPTION_ID` with the Azure CLI and fails on mismatch.
2. A tag can be repointed, making the image a second variable.
3. The images do not exist in ACR yet; a placeholder image runs first.
4. No; it validates syntax offline, not service acceptance.
5. No; ACR builds the images.
6. A public domain where you can create an `A` record, and Entra rights to create an app registration (plus open ports 80/443 for the certificate challenge).

</details>

**Next:** [Module 03 — Infrastructure](03-infrastructure.md) · **Previous:** [Module 01](01-architecture.md)
