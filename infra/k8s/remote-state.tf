#############################################
# INPUTS FROM infra/cloud
#
# Every value this module needs comes out of the cloud module's outputs. Nothing is
# reconstructed from a naming convention: Container App names are truncated, the RAI
# policy references have to be full ARM resource IDs, and both have already caused a
# deploy that addressed something which did not exist.
#
# If an output is missing here, add it to infra/cloud/outputs.tf. Do not rebuild it.
#############################################

data "terraform_remote_state" "cloud" {
  backend = "local"

  config = {
    path = "${path.module}/${var.cloud_state_path}"
  }
}

locals {
  cloud = data.terraform_remote_state.cloud.outputs

  # The image the init container runs. It is the SAME image as the hosted agent, pinned
  # by digest and invoked with a different entrypoint. Pinning the digest matters twice
  # over: the deploy module that publishes the agent version is byte-identical to the
  # agent code it publishes, and the digest is also the experiment's control.
  agent_image = "${local.cloud.acr_login_server}/${var.agent_image_repository}@${var.agent_image_digest}"

  # The private data-plane base URL is NOT built here. deploy.py assembles it from the
  # account and project names, so building a second copy would give us two places that
  # can disagree about where the data plane is. See docs/compatibility.md B9.

  common_labels = {
    "app.kubernetes.io/part-of" = "agent-boundary-lab"
  }
}
