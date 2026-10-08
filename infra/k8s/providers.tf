#############################################
# PROVIDERS
#
# This is a SEPARATE root module from infra/cloud, deliberately.
#
# The kubernetes provider has to be configured with a cluster endpoint and a CA
# certificate. If those resources live in the same root module that creates the cluster,
# then on a clean state both values are unknown at plan time and `terraform plan` fails
# before it can show anything. Splitting the cluster's contents into their own state
# keeps `task cloud:plan` working on an empty subscription, which is the one time you
# most want to read a plan.
#
# State is local, matching infra/cloud. The cluster's own outputs are read back out of
# that state file rather than duplicated here.
#############################################

terraform {
  required_version = ">= 1.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.35"
    }
  }
}

provider "azurerm" {
  features {}
  storage_use_azuread = true
}

# Read rather than recreated. The cluster's endpoint and CA are properties of the thing
# infra/cloud built; carrying them through a second state file would give us two places
# that can disagree about where the API server is.
data "azurerm_kubernetes_cluster" "main" {
  name                = local.cloud.aks_cluster_name
  resource_group_name = local.cloud.resource_group_name
}

# OPERATOR AUTHENTICATION, not workload authentication.
#
# The cluster runs with local_account_disabled = true and Entra RBAC, so there is no
# static admin kubeconfig to borrow. kubelogin exchanges the operator's existing Azure
# session for a cluster token. This is the same ambient credential the azurerm provider
# already requires, and it is the human running the apply — nothing that ships inside a
# container authenticates this way. The deploy init container uses workload identity and
# invokes no CLI at all.
provider "kubernetes" {
  host                   = data.azurerm_kubernetes_cluster.main.kube_config[0].host
  cluster_ca_certificate = base64decode(data.azurerm_kubernetes_cluster.main.kube_config[0].cluster_ca_certificate)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "kubelogin"
    args = [
      "get-token",
      "--login", var.kubelogin_login_mode,
      "--server-id", var.aks_entra_server_application_id,
    ]
  }
}
