#############################################
# CONTAINER APPS — the two controlled endpoints
#
# These are the agent's two destinations, and they are the witnesses for both results:
#
#   policy_api     - ALLOWLISTED. Its receipt proves the allowed call completed end to
#                    end, which is what rules out "the agent was simply broken" as an
#                    explanation for the other call failing.
#   test_receiver  - NOT allowlisted. It accepts absolutely everything, so if a request
#                    ever arrives it WILL be logged. Silence at this endpoint, paired with
#                    a platform denial record, is the negative result.
#
# THE RECEIVER MUST NOT REJECT ANYTHING. A 403 of its own would be indistinguishable from
# a proxy denial - the egress proxy signals denial with an HTTP 403 too. That property is
# enforced in services/test_receiver/main.py and guarded by tests/unit/test_services.py;
# this file must not undo it with an ingress restriction.
#
# Each endpoint runs its own image. services/Dockerfile resolves which app to serve at
# BUILD time, so a running container cannot be repointed at the other service by changing
# an environment variable. Both images come from that one Dockerfile, so they still cannot
# drift apart in base layer or dependency version.
#############################################

locals {
  # The single hostname the egress policy allows. Taken from the live ingress rather than
  # written down anywhere, so the allowlist and the deployed endpoint cannot disagree.
  policy_api_host    = azurerm_container_app.policy_api.ingress[0].fqdn
  test_receiver_host = azurerm_container_app.test_receiver.ingress[0].fqdn

  # Published while the environment is built, and only then. Terraform cannot point a
  # Container App at an image that ACR does not have yet, so the first apply runs this.
  placeholder_image = "mcr.microsoft.com/k8se/quickstart:latest"

  # The real images, once var.endpoint_image_tag is set.
  #
  # Built here from the registry login server and the repository names, NOT from the
  # Container App resource names. Those two are different strings: Container Apps cap at
  # 32 characters so `policy_api_name` is truncated, while the ACR repository is not.
  # `task build:deploy-endpoints` used to rebuild the app name by concatenation and
  # addressed an app that does not exist — "The containerapp does not exist". Terraform
  # already knows both names; nothing should reconstruct either.
  endpoint_images = {
    policy_api    = "${azurerm_container_registry.main.login_server}/containment-demo-policy-api:${var.endpoint_image_tag}"
    test_receiver = "${azurerm_container_registry.main.login_server}/containment-demo-test-receiver:${var.endpoint_image_tag}"
  }

  policy_api_image    = var.endpoint_image_tag == "" ? local.placeholder_image : local.endpoint_images.policy_api
  test_receiver_image = var.endpoint_image_tag == "" ? local.placeholder_image : local.endpoint_images.test_receiver
}

resource "azurerm_container_app_environment" "main" {
  name                       = local.caenv_name
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  infrastructure_subnet_id   = azurerm_subnet.container_apps.id

  # See var.test_endpoints_public. Public by default so that a failed call to the
  # receiver has exactly ONE sufficient explanation.
  internal_load_balancer_enabled = !var.test_endpoints_public

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  tags = local.common_tags
}

#############################################
# Policy API — the allowlisted destination
#############################################

resource "azurerm_container_app" "policy_api" {
  name                         = local.policy_api_name
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  ingress {
    external_enabled = var.test_endpoints_public
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "policy-api"
      image  = local.policy_api_image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }

  # NO `ignore_changes` on the image.
  #
  # It used to be ignored here because `az containerapp update --image` set the image out
  # of band. That meant terraform owned the app but not what it ran, so the two could
  # disagree forever and nothing would say so. The image is now var.endpoint_image_tag and
  # terraform owns it outright: if a plan shows this reverting to the placeholder, your
  # ENDPOINT_IMAGE_TAG is unset, and the plan telling you that is the point.

  tags = local.common_tags
}

#############################################
# Test receiver — the destination deliberately left OUT of the allowlist
#############################################

resource "azurerm_container_app" "test_receiver" {
  name                         = local.test_receiver_name
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  ingress {
    # Open on exactly the same terms as the policy API. The two endpoints differ ONLY in
    # whether the egress policy names them. Restricting this one at the network layer
    # would give a failed call a second sufficient cause and destroy attribution.
    external_enabled = var.test_endpoints_public
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Always warm. A cold-start timeout looks exactly like a silently dropped connection,
    # and the difference between those two is the entire negative result.
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "test-receiver"
      image  = local.test_receiver_image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }

  # See the policy API above: the image is terraform's, not a CLI's.

  tags = local.common_tags
}
