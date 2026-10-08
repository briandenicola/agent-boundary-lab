#############################################
# NAMESPACE
#
# One namespace holds the harness today and the Dapr workflow app from Phase 8. Its name
# comes from the cloud module, because the same string is baked into the workload-identity
# federated credential subject (`system:serviceaccount:<ns>:<sa>`). If the two ever drift
# apart, the token exchange fails with a subject mismatch and the only symptom is an
# AADSTS70021 in the init container's log.
#############################################

resource "kubernetes_namespace_v1" "demo" {
  metadata {
    name   = local.cloud.kubernetes_namespace
    labels = local.common_labels
  }
}
