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

  # Placeholder published while the environment is built. Terraform cannot know the real
  # digest at plan time, so the first apply runs this and `task cloud:deploy-endpoints`
  # replaces it. `ignore_changes` below stops a later apply from reverting the real image.
  placeholder_image = "mcr.microsoft.com/k8se/quickstart:latest"
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
      image  = local.placeholder_image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }

  lifecycle {
    # The real image is published by `task cloud:deploy-endpoints` against a digest that
    # does not exist at plan time. Without this, every later apply would roll the endpoint
    # back to the placeholder mid-demo.
    ignore_changes = [template[0].container[0].image]
  }

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
      image  = local.placeholder_image
      cpu    = 0.25
      memory = "0.5Gi"
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  tags = local.common_tags
}
