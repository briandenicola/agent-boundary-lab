The Secret `harness-config` (key `HARNESS_UI_TOKEN`) is deliberately NOT in this kustomization.
`task chat-agent:secret` creates it out of band so the token never exists in a manifest or in git.
The façade token comes from the existing `a2a-facade-config` Secret (`task agent-bridge:secret`).

Operator component name: `chat-agent`. Build with `task build:chat-agent` and deploy with
`task deploy:chat-agent` after the model server and bridges. The Foundry publishing helper
in `../base/` is a different Deployment, managed by `deploy:foundry-agent`.

The harness needs no Azure identity (it reaches Foundry only through the façades), so it runs as
the namespace's default ServiceAccount with no token mounted. It does not reuse `demo-ui`.

## External HTTPS + Entra login (ingress OIDC)

The external path for issue #4 is additive and uses `deploy/kustomize/harness-external/`:

- `harness-oauth2-proxy` (oauth2-proxy deployment + service),
- `harness-oauth2` and `harness-external` ingress resources,
- a cert-manager `ClusterIssuer` for Let's Encrypt,
- `chat-agent:external-up` setting `HARNESS_AUTH_MODE=ingress_oidc` on the harness deployment.

Run via Task targets:

1. `task app:deploy-external HOSTNAME=... LETSENCRYPT_EMAIL=...` (full from-scratch path)
2. `task chat-agent:external-status` (read-only status check)

Lower-level options still exist when needed:
- `task chat-agent:external-app HOSTNAME=...` creates/updates the Entra app registration + OIDC Secret.
- `task chat-agent:external-up HOSTNAME=... LETSENCRYPT_EMAIL=...` applies ingress resources.

This keeps the harness service itself `ClusterIP`; only ingress is public.
