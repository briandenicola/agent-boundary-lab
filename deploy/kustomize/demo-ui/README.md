The Secret `demo-ui-config` (key `DEMO_UI_TOKEN`) is deliberately NOT in this kustomization.
`task test-ui:secret` creates it out of band so the token never exists in a manifest or in git.

Operator component name: `test-ui`. Build with `task build:test-ui` and deploy with
`task deploy:test-ui`, which prepares both required Secrets before applying manifests.
