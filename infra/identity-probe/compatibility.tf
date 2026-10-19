data "azurerm_client_config" "current" {}

resource "terraform_data" "setup_target" {
  lifecycle {
    precondition {
      condition     = data.azurerm_client_config.current.tenant_id == var.tenant_id
      error_message = "The Azure provider must authenticate in the same tenant as the probe."
    }
    precondition {
      condition     = var.allowed_user_id != var.denied_user_id
      error_message = "Use distinct existing synthetic test users."
    }
  }
}
