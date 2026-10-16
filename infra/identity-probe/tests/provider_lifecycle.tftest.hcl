mock_provider "azurerm" {}
mock_provider "random" {}
mock_provider "msgraph" {}

override_data {
  target = data.msgraph_resource.foundry_api
  values = {
    output = {
      app_id = "00000000-0000-4000-8000-000000000007"
      names  = ["https://ai.azure.com"]
      scopes = [{ value = "synthetic.invoke", isEnabled = true }]
    }
  }
}

variables {
  tenant_id                        = "00000000-0000-4000-8000-000000000001"
  graph_deployer_client_id         = "00000000-0000-4000-8000-000000000002"
  graph_deployer_certificate_path  = "/synthetic/no-certificate-used"
  sponsor_user_id                  = "00000000-0000-4000-8000-000000000003"
  allowed_user_id                  = "00000000-0000-4000-8000-000000000004"
  denied_user_id                   = "00000000-0000-4000-8000-000000000005"
  foundry_project_resource_id      = "/subscriptions/00000000-0000-4000-8000-000000000006/resourceGroups/synthetic/providers/Microsoft.CognitiveServices/accounts/synthetic/projects/synthetic"
  foundry_endpoint                 = "https://synthetic.services.ai.azure.com/api/projects/synthetic"
  foundry_api_service_principal_id = "00000000-0000-4000-8000-000000000008"
  foundry_delegated_scope          = "synthetic.invoke"
  foundry_audience                 = "https://ai.azure.com"
  aks_oidc_issuer_url              = "https://synthetic.example/"
  probe_image                      = "synthetic.azurecr.io/agent@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  sidecar_image                    = "mcr.microsoft.com/entra-sdk/auth-sidecar@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}

run "unverified_provider_cannot_provision" {
  command         = plan
  expect_failures = [terraform_data.agent_id_provider_gate]
}

run "targeting_browser_cannot_bypass_gate" {
  command = plan
  plan_options {
    target = [msgraph_resource.browser]
  }
  expect_failures = [terraform_data.agent_id_provider_gate]
}

run "targeting_rbac_cannot_bypass_gate" {
  command = plan
  plan_options {
    target = [azurerm_role_assignment.allowed_user_invoke]
  }
  expect_failures = [terraform_data.agent_id_provider_gate]
}
