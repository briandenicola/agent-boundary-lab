The Secret `demo-ui-config` (key `DEMO_UI_TOKEN`) is deliberately NOT in this kustomization.
`task ui:secret` creates it out of band so the token never exists in a manifest or in git.
