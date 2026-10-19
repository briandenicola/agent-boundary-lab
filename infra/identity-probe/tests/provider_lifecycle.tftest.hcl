mock_provider "azurerm" {}
mock_provider "random" {}

override_data {
  target = data.azurerm_client_config.current
  values = {
    tenant_id = "00000000-0000-4000-8000-000000000001"
  }
}

variables {
  tenant_id                        = "00000000-0000-4000-8000-000000000001"
  allowed_user_id                   = "00000000-0000-4000-8000-000000000004"
  denied_user_id                    = "00000000-0000-4000-8000-000000000005"
  foundry_project_resource_id       = "/subscriptions/00000000-0000-4000-8000-000000000006/resourceGroups/synthetic/providers/Microsoft.CognitiveServices/accounts/synthetic/projects/synthetic"
  foundry_endpoint                  = "https://synthetic.services.ai.azure.com/api/projects/synthetic"
  foundry_api_service_principal_id  = "00000000-0000-4000-8000-000000000008"
  foundry_delegated_scope           = "synthetic.invoke"
  foundry_audience                  = "https://ai.azure.com"
  aks_oidc_issuer_url               = "https://synthetic.oic.prod-aks.azure.com/00000000-0000-4000-8000-000000000001/00000000-0000-4000-8000-000000000002/"
  probe_image                      = "synthetic.azurecr.io/agent@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  sidecar_image                    = "mcr.microsoft.com/entra-sdk/auth-sidecar@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}

run "supported_naming_and_rbac_only" {
  command = plan
  assert {
    condition     = azurerm_role_assignment.allowed_user_invoke.principal_id == var.allowed_user_id
    error_message = "Only the allowed user receives the project invoke role."
  }
}

run "wrong_tenant_cannot_provision" {
  command = plan
  variables {
    tenant_id = "00000000-0000-4000-8000-000000000002"
  }
  expect_failures = [terraform_data.setup_target]
}

run "targeting_rbac_cannot_bypass_tenant_guard" {
  command = plan
  variables {
    tenant_id = "00000000-0000-4000-8000-000000000002"
  }
  plan_options {
    target = [azurerm_role_assignment.allowed_user_invoke]
  }
  expect_failures = [terraform_data.setup_target]
}
