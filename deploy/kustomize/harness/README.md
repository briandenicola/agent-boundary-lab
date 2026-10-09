The Secret `harness-config` (key `HARNESS_UI_TOKEN`) is deliberately NOT in this kustomization.
`task harness:secret` creates it out of band so the token never exists in a manifest or in git.
The façade token comes from the existing `a2a-facade-config` Secret (`task a2a:secret`).

The harness needs no Azure identity (it reaches Foundry only through the façades), so it runs as
the namespace's default ServiceAccount with no token mounted. It does not reuse `demo-ui`.
