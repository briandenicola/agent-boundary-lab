# Agent identities need Cognitive Services OpenAI User on the account (proposed, not applied)

**By:** Parker, 2026-10-09

- Evidence: v7 model call to the account-level OpenAI endpoint passed egress and failed
  authorisation; principal 842d7e21 (the audit agent's `-AgentIdentity`) holds no role.
- Role: **Cognitive Services OpenAI User** — `OpenAI/responses/*` verified verbatim from
  `az role definition list`; narrowest built-in that carries `responses/write`.
- Principal: the Entra `-AgentIdentity` (verified per-agent, stable across versions, distinct
  audit vs enforced). NOT the blueprint — it authenticates, it does not call the model.
- Why it is needed at all: docs say the project endpoint gives implicit model access; our
  code bypasses it and calls the account endpoint (documented case needing a role).
- Design: option B, `task cloud:agent-access-plan` (read-only) / `agent-access-up`. Tag-keyed
  lookup, no GUIDs, exactly-one-match-or-fail, same role+scope for both agents, idempotent.
  Terraform rejected: identities don't exist at plan time on a fresh environment and it needs
  a new provider.
- **Brian must approve running `task cloud:agent-access-up`** (two role assignments).
- **Alternative for Brett/Lambert/Ripley:** call the project endpoint instead (no role, but
  changes the egress-allowlisted model host). Unverified under our networking.
- Separately recorded from the same docs: Container Registry Repository Reader is preferred
  over AcrPull; ACR needs `azureADAuthenticationAsArmPolicy` enabled and the project has an ACR
  connection — neither verified on our resources.
- Recreating an agent mints a new identity: re-run `agent-access-up`.
