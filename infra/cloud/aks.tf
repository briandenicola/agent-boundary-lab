#############################################
# AKS — host for the agentic harness, and for the Phase 8/9 Dapr workflow app
#
# The workflow app invokes the UNCHANGED Foundry agent from an activity, waits on an
# authenticated approval event with a durable deadline, and must survive a workflow-pod
# restart. Durable Task Scheduler and its SDK are explicitly NOT dependencies: the
# durability comes from Dapr Workflow over a persistent state store.
#
# The harness also runs here. It is the client, and it sits inside the VNet deliberately
# so it reaches the inbound-private Foundry account over the private endpoint rather than
# the internet. It stands in for an on-premises environment; it is not actually on
# premises, and nothing should describe it as if it were.
#
# Provisioned unconditionally rather than behind a toggle. A cluster that only exists for
# some applies is a cluster whose restart test has never been run on a clean environment.
#############################################

# Resolved at plan time rather than pinned. A hardcoded version rots: AKS moves versions
# into Long-Term-Support-only status and the apply then fails with K8sVersionNotSupported
# on a config that worked last month. The cluster is not an experimental variable here,
# so tracking the region's current default is the correct behaviour.
data "azurerm_kubernetes_service_versions" "current" {
  location        = azurerm_resource_group.this.location
  include_preview = false
}

resource "azurerm_kubernetes_cluster" "main" {
  depends_on = [azurerm_subnet_network_security_group_association.aks]

  lifecycle {
    ignore_changes = [
      default_node_pool[0].node_count,
      kubernetes_version,
    ]
  }

  name                = local.aks_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  node_resource_group = local.aks_node_rg_name
  kubernetes_version  = coalesce(var.kubernetes_version, data.azurerm_kubernetes_service_versions.current.latest_version)
  dns_prefix          = local.aks_name
  sku_tier            = "Standard"

  automatic_upgrade_channel = "patch"
  node_os_upgrade_channel   = "SecurityPatch"

  local_account_disabled       = true
  run_command_enabled          = false
  azure_policy_enabled         = true
  cost_analysis_enabled        = true
  image_cleaner_enabled        = true
  image_cleaner_interval_hours = 48

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  default_node_pool {
    name                        = "system"
    temporary_name_for_rotation = "temp"
    node_count                  = var.aks_node_count
    vm_size                     = var.aks_node_size
    vnet_subnet_id              = azurerm_subnet.aks.id
    type                        = "VirtualMachineScaleSets"
    auto_scaling_enabled        = true
    min_count                   = 1
    max_count                   = var.aks_node_count * 2
    max_pods                    = 110
    os_sku                      = "AzureLinux"

    upgrade_settings {
      max_surge = "25%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  azure_active_directory_role_based_access_control {
    azure_rbac_enabled = true
    tenant_id          = data.azurerm_client_config.current.tenant_id
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    network_policy      = "cilium"
    service_cidr        = "10.${random_integer.services_cidr.result}.0.0/16"
    dns_service_ip      = "10.${random_integer.services_cidr.result}.0.10"
    pod_cidr            = "10.${random_integer.pod_cidr.result}.0.0/16"
    load_balancer_sku   = "standard"
    outbound_type       = "loadBalancer"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }

  workload_autoscaler_profile {
    keda_enabled = true
  }

  tags = local.common_tags
}

# The operator needs cluster access to deploy the workflow app and to kill a pod during
# the durability test.
resource "azurerm_role_assignment" "current_user_aks_admin" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "current_user_aks_user" {
  scope                = azurerm_kubernetes_cluster.main.id
  role_definition_name = "Azure Kubernetes Service Cluster User Role"
  principal_id         = data.azurerm_client_config.current.object_id
}
