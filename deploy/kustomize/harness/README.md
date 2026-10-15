The Secret `harness-config` (key `HARNESS_UI_TOKEN`) is deliberately NOT in this kustomization.
`task chat-agent:secret` creates it out of band so the token never exists in a manifest or in git.
The façade token comes from the existing `a2a-facade-config` Secret (`task agent-bridge:secret`).

Operator component name: `chat-agent`. Build with `task build:chat-agent` and deploy with
`task deploy:chat-agent` after the model server and bridges. The Foundry publishing helper
in `../base/` is a different Deployment, managed by `deploy:foundry-agent`.

The harness needs no Azure identity (it reaches Foundry only through the façades), so it runs as
the namespace's default ServiceAccount with no token mounted. It does not reuse `demo-ui`.
