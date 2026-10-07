#############################################
# MODEL DEPLOYMENT — the chat model backing the agent
#
# Pinned to an explicit version. A floating version would let Azure change the model
# between the Audit run and the Enforced run, quietly introducing a second variable into
# an experiment whose entire validity rests on there being only one.
#
# The model is not under test. It only has to be capable enough to call two tools.
#############################################

resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.model_name
  cognitive_account_id = azapi_resource.foundry.id

  sku {
    name     = "GlobalStandard"
    capacity = var.model_capacity
  }

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  # Azure raises the model version on its own schedule unless told not to. Left to
  # itself, it would be able to change the agent's behaviour between two runs that are
  # supposed to be identical.
  version_upgrade_option = "NoAutoUpgrade"
}
