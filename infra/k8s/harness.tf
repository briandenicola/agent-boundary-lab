#############################################
# THE CLIENT HARNESS POD
#
# What this is for: the Foundry data plane is inbound-private
# (publicNetworkAccess Disabled), so creating an agent version has to originate from
# inside the VNet. This pod is that inside-the-VNet place. It is also where the A2A
# client loop will live later — the harness stands in for an on-premises caller. It sits
# in the VNet deliberately and is NOT actually on premises; nothing should describe it
# as if it were.
#
# Right now the pod is deliberately minimal: a ServiceAccount, workload identity, an
# init container that publishes the agent versions, and a main container that does
# nothing but hold the pod open. The agent loop is later work and is not in this file.
#
# WHY AN INIT CONTAINER AND NOT A JOB. A Job would be a second thing to schedule, a
# second identity binding to keep in step, and it would disappear between runs — so the
# agent versions would silently depend on whether someone remembered to run it. As an
# init container, the harness cannot serve a request until the versions it is going to
# call actually exist. The deploy module must therefore be idempotent: the pod restarts
# for ordinary reasons, and every restart runs it again.
#############################################

# The pod runs as THIS account, and the federated credential in
# infra/cloud/identity.tf names exactly this account in its subject. The init container
# needs the identity, and an init container shares the pod's ServiceAccount, so the whole
# pod runs as the deployer.
resource "kubernetes_service_account_v1" "agent_deployer" {
  metadata {
    name      = local.cloud.agent_deployer_service_account
    namespace = kubernetes_namespace_v1.demo.metadata[0].name
    labels    = local.common_labels

    # The client ID of the user-assigned identity the workload-identity webhook will
    # exchange the projected token for. Read from the cloud module, never pasted: a
    # stale GUID here fails at token exchange, not at apply.
    annotations = {
      "azure.workload.identity/client-id" = local.cloud.agent_deployer_client_id
    }
  }
}

# Values that must not appear in `kubectl get deployment -o yaml`. The agent's
# diagnostic route token and the Application Insights connection string are both
# credentials; they are passed to the hosted agent as environment variables, so the
# deploy module needs them, but they travel through a Secret rather than through the
# pod spec.
resource "kubernetes_secret_v1" "agent_config" {
  metadata {
    name      = "${var.harness_name}-config"
    namespace = kubernetes_namespace_v1.demo.metadata[0].name
    labels    = local.common_labels
  }

  type = "Opaque"

  data = {
    DEMO_DIAGNOSTICS_TOKEN                = local.cloud.diagnostics_token
    APPLICATIONINSIGHTS_CONNECTION_STRING = local.cloud.application_insights_connection_string
  }
}

locals {
  # Non-secret configuration for the deploy init container.
  #
  # These names are a CONTRACT with src/containment_demo/deploy.py. Each one is a field
  # on DeploySettings or on Settings, both of which read the DEMO_ prefix. Checked
  # against that module, not guessed. FOUNDRY_ and AGENT_ are reserved by the platform
  # and are never used for our own settings.
  #
  # AZURE_CLIENT_ID, AZURE_TENANT_ID and AZURE_FEDERATED_TOKEN_FILE are NOT set here.
  # The workload-identity webhook injects them when the pod carries the
  # `azure.workload.identity/use` label, and DefaultAzureCredential picks them up. Setting
  # them by hand would shadow the webhook and is a common way to get a confusing
  # authentication failure.
  deploy_env = {
    # Where to publish to.
    DEMO_FOUNDRY_ACCOUNT_NAME = local.cloud.foundry_account_name
    DEMO_FOUNDRY_PROJECT_NAME = local.cloud.project_name

    # What to publish. One digest, two agents.
    DEMO_AGENT_IMAGE         = local.agent_image
    DEMO_AGENT_NAME_AUDIT    = local.cloud.agent_name_audit
    DEMO_AGENT_NAME_ENFORCED = local.cloud.agent_name_enforced

    # The only experimental variable. These must be FULL ARM resource IDs — a bare policy
    # name is rejected by the data plane. See docs/compatibility.md B4.
    DEMO_RAI_POLICY_AUDIT_ID    = local.cloud.rai_policy_audit_id
    DEMO_RAI_POLICY_ENFORCED_ID = local.cloud.rai_policy_enforced_id

    # Agent runtime settings, passed through into the hosted agent's
    # definition.environment_variables. Both destinations are set for both agents: the
    # agent never knows which host is allowlisted, and must not be able to find out.
    DEMO_POLICY_API_URL        = local.cloud.policy_api_url
    DEMO_TEST_RECEIVER_URL     = local.cloud.test_receiver_url
    DEMO_MODEL_DEPLOYMENT      = local.cloud.model_deployment_name
    DEMO_AZURE_OPENAI_ENDPOINT = local.cloud.foundry_endpoint
    DEMO_DIAGNOSTICS_ENABLED   = "true"
  }
}

resource "kubernetes_deployment_v1" "harness" {
  metadata {
    name      = var.harness_name
    namespace = kubernetes_namespace_v1.demo.metadata[0].name
    labels    = merge(local.common_labels, { "app.kubernetes.io/name" = var.harness_name })
  }

  spec {
    replicas = var.harness_replicas

    selector {
      match_labels = {
        "app.kubernetes.io/name" = var.harness_name
      }
    }

    template {
      metadata {
        labels = merge(local.common_labels, {
          "app.kubernetes.io/name" = var.harness_name

          # Without this label the webhook does not mutate the pod, no projected token is
          # mounted, and DefaultAzureCredential silently falls back to something else.
          # It is a label, not an annotation.
          "azure.workload.identity/use" = "true"
        })

        # Redeploy when configuration changes. Kubernetes does not restart pods when a
        # Secret's contents change, so without this a rotated token would be picked up
        # only at the next unrelated restart.
        annotations = {
          "agent-boundary-lab/config-hash" = sha256(jsonencode(local.deploy_env))
        }
      }

      spec {
        service_account_name = kubernetes_service_account_v1.agent_deployer.metadata[0].name

        security_context {
          run_as_non_root = true
        }

        dynamic "init_container" {
          for_each = var.agent_deploy_enabled ? [1] : []

          content {
            name  = "agent-deploy"
            image = local.agent_image

            # The image's own ENTRYPOINT is the Foundry protocol adapter. The deploy
            # module is a second entrypoint into the SAME image, so the code that
            # publishes the agent version is byte-identical to the code being published.
            #
            # The interpreter is an ABSOLUTE path, not `python`. The Dockerfile installs
            # the agent's dependencies with `uv pip install --system` and the deploy
            # extra (azure-ai-projects) into the separate venv at /opt/deploy-venv only.
            # That venv is never activated and is not on PATH, so a bare `python` resolves
            # to the system interpreter and the init container dies at import time with
            # ModuleNotFoundError: azure.ai.projects. Relying on PATH ordering would also
            # make this silently sensitive to a future ENV PATH edit in the Dockerfile.
            command = [var.agent_deploy_interpreter, "-m", var.agent_deploy_module]

            dynamic "env" {
              for_each = local.deploy_env
              content {
                name  = env.key
                value = env.value
              }
            }

            env {
              name = "DEMO_DIAGNOSTICS_TOKEN"
              value_from {
                secret_key_ref {
                  name = kubernetes_secret_v1.agent_config.metadata[0].name
                  key  = "DEMO_DIAGNOSTICS_TOKEN"
                }
              }
            }

            env {
              name = "APPLICATIONINSIGHTS_CONNECTION_STRING"
              value_from {
                secret_key_ref {
                  name = kubernetes_secret_v1.agent_config.metadata[0].name
                  key  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
                }
              }
            }

            resources {
              requests = {
                cpu    = var.harness_cpu_request
                memory = var.harness_memory_request
              }
              limits = {
                memory = var.harness_memory_limit
              }
            }

            security_context {
              allow_privilege_escalation = false
              read_only_root_filesystem  = false
              capabilities {
                drop = ["ALL"]
              }
            }
          }
        }

        container {
          name  = "harness"
          image = local.agent_image

          # PLACEHOLDER BODY, ON PURPOSE. This pod exists today to give the deploy init
          # container a home and to prove the workload-identity and ACR-pull paths. The
          # A2A client loop replaces this command; nothing else in this file changes when
          # it does. Running the agent image rather than a generic base image means the
          # pull path exercised here is the same one the real harness will use.
          command = ["sleep", "infinity"]

          dynamic "env" {
            for_each = local.deploy_env
            content {
              name  = env.key
              value = env.value
            }
          }

          env {
            name = "DEMO_DIAGNOSTICS_TOKEN"
            value_from {
              secret_key_ref {
                name = kubernetes_secret_v1.agent_config.metadata[0].name
                key  = "DEMO_DIAGNOSTICS_TOKEN"
              }
            }
          }

          env {
            name = "APPLICATIONINSIGHTS_CONNECTION_STRING"
            value_from {
              secret_key_ref {
                name = kubernetes_secret_v1.agent_config.metadata[0].name
                key  = "APPLICATIONINSIGHTS_CONNECTION_STRING"
              }
            }
          }

          resources {
            requests = {
              cpu    = var.harness_cpu_request
              memory = var.harness_memory_request
            }
            limits = {
              memory = var.harness_memory_limit
            }
          }

          security_context {
            allow_privilege_escalation = false
            capabilities {
              drop = ["ALL"]
            }
          }
        }
      }
    }
  }
}
