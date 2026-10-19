# Terraform owns naming and Azure RBAC only. Canonical Graph SDK/API lifecycle is
# managed separately by identity_setup.py; Graph objects never enter Terraform state.
resource "random_pet" "this" {
  length = 2
}

resource "random_id" "this" {
  byte_length = 2
}

resource "random_uuid" "incoming_scope" {}

locals {
  name = "${random_pet.this.id}-${random_id.this.hex}-identity-probe"
}

# Neither the denied user nor the intermediary agent receives an invoke role.
resource "azurerm_role_assignment" "allowed_user_invoke" {
  depends_on           = [terraform_data.setup_target]
  scope                = var.foundry_project_resource_id
  role_definition_name = "Foundry Agent Consumer"
  principal_id         = var.allowed_user_id
  principal_type       = "User"
}
