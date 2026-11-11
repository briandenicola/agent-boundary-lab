# Azure deployment guide

[Documentation](README.md) | [Run the demo](demo-runbook.md) | [Architecture](architecture-as-built.md)

This guide gets both parts of the repo running in Azure:

| Demo | What you deploy | Where you use it |
| --- | --- | --- |
| **Identity and network containment** | Two Foundry agents, two Container Apps APIs, and an AKS browser harness | Your own HTTPS website |
| **ACS governance and Copilot** | Separate governed agents, an OAuth-enabled policy service, and a Copilot publication | Microsoft 365 Copilot |

Both use the same Azure foundation. Deploy the first part before adding the second.
Terraform creates the infrastructure; Task builds images in Azure Container
Registry and deploys the applications. You do not need Docker locally.

Already deployed? Skip to [updating an existing environment](#updating-an-existing-environment).
For prompts and evidence checks, use the [demo runbook](demo-runbook.md).

## Before you start

Use Linux x86_64, or an equivalent WSL environment, with these tools installed:

`git`, `az`, `terraform`, `task`, Python 3.12, `uv`, `kubectl`, `kubelogin`,
`kustomize`, `helm`, `jq`, `curl`, and `openssl`.

You also need:

- An Azure subscription with permission to create resources and assign roles.
- Entra permissions to create app registrations and grant the required consent.
- Foundry hosted-agent access and model/AKS quota in **Sweden Central**, the default region.
- A public hostname you control, an email for Let's Encrypt, and two synthetic
  Entra users: one allowed to read policy and one not allowed.
- Microsoft 365 Copilot access and permission to publish a **Just you** agent for part 2.

AKS, Foundry, the managed firewall, model calls, and ACR builds incur charges.
Run all commands from the repository root.

### Configure your environment

```bash
git clone https://github.com/briandenicola/agent-boundary-lab.git
cd agent-boundary-lab
cp .env.example .env
```

In `.env`, set:

```dotenv
ARM_TENANT_ID=<your-tenant-id>
ARM_SUBSCRIPTION_ID=<your-subscription-id>
POLICY_API_AUTHORIZED_USER_IDS=<allowed-test-user-object-id>
```

Use the user's Entra **object ID**, not a client ID. Leave the denied user out.
On a fresh deployment, leave image-tag and image-digest overrides unset.
Task reads `.env` automatically; deployment tasks obtain resource URLs and
runtime settings from Terraform.

```bash
az login --tenant <your-tenant-id>
az account set --subscription <your-subscription-id>
task cloud:target-check
task copilot-toolbox:prepare
```

The last command installs the locked Python dependencies and pinned OPA binary
used by the governance tools.

## Part 1: AKS and Foundry demo

### 1. Create the Azure foundation

```bash
task cloud:plan
# Review the plan before continuing.
task cloud:bootstrap
task cloud:up
task cloud:kubeconfig
```

`bootstrap` is for the first deployment only. It creates the Foundry account and
imports the managed network Azure creates with it. `cloud:up` then creates the
rest: AKS, ACR, networking, Foundry/model resources, Container Apps, and monitoring.
The APIs initially run placeholder images; the next step replaces them.

### 2. Build and deploy the applications

```bash
task build:all
task deploy:all
```

This builds seven images in ACR and deploys the two APIs, both Foundry agent
versions, the AKS model server, browser harness, bridges, and two-button test UI.
Both Foundry agents use the same image digest.

### 3. Set up HTTPS and user sign-in

Install the ingress controller and certificate manager:

```bash
task chat-agent:external-prereqs
kubectl -n ingress-nginx get svc ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].ip}{"\n"}'
```

At your DNS provider, create an **A record** pointing your chosen hostname to
that IP. Wait until the name resolves to it, then run:

```bash
task chat-agent:external-bootstrap \
  HOSTNAME=<your-demo-hostname> LETSENCRYPT_EMAIL=<your-email>
task cloud:plan
# Review the policy API authentication changes, then apply them.
task cloud:up
task chat-agent:external-status
```

The bootstrap creates the sign-in and policy API registrations, configures
delegated access, and requests the TLS certificate. It also writes the API's
authentication settings into `.env`; the final `cloud:up` applies those settings.
No manual app registration is needed.

### 4. Open the demo

When the certificate is ready, open **`https://<your-demo-hostname>`**.
Sign in as the allowed test user, then repeat in a private browser as the denied user.

```bash
task tool-apis:check
task foundry-agent:status
```

For development without HTTPS sign-in, use `task chat-agent:token` followed by
`task chat-agent:open`. That shared-token interface is not the user-identity demo.

## Part 2: ACS governance and Microsoft 365 Copilot

Start with part 1 running, including its protected policy API. Keep the same
`.env`, Terraform state, and AKS context.

### 1. Deploy the governance agents

```bash
task acs:up
task acs:build
task acs:deploy
task acs:status
```

These commands create three dedicated policies, deploy seven comparison agents,
and configure their access. They leave the original agents and APIs alone.
The private AKS helper handles deployment; it does not relay Copilot chat.

### 2. Deploy the OAuth-enabled Copilot agent

```bash
task copilot-toolbox:build
task copilot-toolbox:infra-up
```

This creates the separate project, protected MCP service, OAuth connection, real
callback, and versioned toolbox. It also configures the exact-host outbound rule.
If asked to consent, open `.task/copilot-toolbox/consent.html`, sign in, and rerun
**`task copilot-toolbox:infra-up`**.

The consenting user must be authorized on the MCP service. It inherits the
baseline's allowed users; to add another user to **this service only**, set
`TF_VAR_mcp_additional_authorized_user_ids='["<user-object-id>"]'` in `.env`
before running `infra-up`.

```bash
task copilot-toolbox:up
```

If preflight reports a missing or unready account capability host, stop:
this workflow requires the existing platform-managed host and does not create
a replacement or change account-wide routing.

### 3. Publish to Copilot

Create the publication metadata file once:

```bash
mkdir -p .task/copilot-toolbox
cp deploy/copilot/toolbox-publish-request.example.json \
  .task/copilot-toolbox/publish-request.json
```

Edit the copy with your public developer name, website, privacy URL, and terms URL.
Keep the display name **ACS OAuth Servicing Demo**. Do not overwrite an existing
filled file.

```bash
task copilot-toolbox:publish-plan
# Review the Just you publication and agent version.
task copilot-toolbox:publish
task copilot-toolbox:status
```

Open Microsoft 365 Copilot → **Your agents → ACS OAuth Servicing Demo**.
Start a new conversation and ask:

> Look up the servicing policy for the synthetic demo account, then send the
> synthetic servicing record to the external processor.

The lookup should succeed; ACS should block sending. This is application
governance, not a platform network-denial result.

**Optional:** to publish the original blocked-action-only **ACS Servicing Demo**,
fill `.task/copilot/publish-request.json` from
`deploy/copilot/publish-request.example.json`, then run `task acs:copilot`.
That entry does not provide delegated lookup; it is separate from the OAuth demo.

## Updating an existing environment

Do not rebuild just to use the demo. To inspect it:

```bash
task tool-apis:check
task acs:status
task copilot-toolbox:status
```

For code changes, rebuild and deploy only the affected part:

| Change | Commands |
| --- | --- |
| Baseline component | `task build:<component>`, then `task deploy:<component>` |
| Original ACS agents | `task acs:build`, `task acs:deploy`; `task acs:copilot` if published |
| OAuth Copilot demo | `task copilot-toolbox:build`, `infra-up`, `up`, `publish-plan`, then `publish` |

For the first row, replace `<component>` with `tool-apis`, `foundry-agent`,
`model-server`, `test-ui`, `agent-bridge`, or `chat-agent`.
In the last row, all commands use the `copilot-toolbox:` prefix.
Keep existing publication metadata; an image update changes the version pin, not
the catalog entry. Skip publication if the same version is already published.

Do not run `cloud:up` just to update an application or erase unrelated policy drift.
Keep `.env`, Terraform state under `infra/`, and private journals/image records
under `.task/`; they are needed for updates and cleanup.

## Troubleshooting

| Problem | First check |
| --- | --- |
| Wrong tenant, subscription, or AKS context | `task cloud:target-check`, then `task cloud:kubeconfig` |
| Managed network missing from Terraform state | `task cloud:network-import` for a partially created foundation |
| Hosted image will not start | Foundry's `acr-pe` outbound rule and registry approval; [troubleshooting](workshop/12-troubleshooting.md#infrastructure) |
| HTTPS certificate not ready | DNS points to the ingress IP; ports 80/443 are reachable |
| Policy lookup returns 401/403 | Signed-in user's authorization; in Copilot, check you selected the **OAuth** entry |
| Consent or publication stops partway | Keep the private journals and inspect status; do not delete them and blindly retry |

## Cleanup

Remove in this order. Each step leaves the layers below it running.

**1. Copilot.** Remove the OAuth extension before the shared helper:

```bash
task copilot-toolbox:disable
task copilot-toolbox:down
# If you also published the original ACS entry:
task copilot:disable
task governance:down
```

`copilot-toolbox:down` removes the hosted agent versions, grants, isolated Terraform resources and the dedicated OAuth registration. `governance:down` removes the original agents, the three policies and the helper deployment. Disabling a publication restores its endpoint; delete the catalog entry separately in Microsoft 365.

**2. Identity probe (only if you ran it).** Needs the cluster context:

```bash
task identity:destroy
```

**3. External sign-in and ingress:**

```bash
task chat-agent:external-down       # removes ingress and proxy; harness returns to token auth
task chat-agent:external-app-down   # removes the policy API registration and OBO settings
```

`external-down` keeps ingress-nginx, cert-manager, DNS and the app registrations. `external-app-down` keeps the sign-in app registration; delete that and the DNS record yourself.

**4. Everything else:**

```bash
task cloud:down
```

This starts deletion of every resource group tagged with the lab's application name and removes local Terraform state immediately, without waiting for Azure to finish. Back up state and the `.task/` journals first if you might need them. Never touch the AKS node resource group directly.
