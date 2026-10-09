# Demo UI deploy tasks
- `tasks/Taskfile.ui.yml` (included as `ui:`): build, digest, secret, token, render, plan, up, open, verify. `Dockerfile.demo-ui` is a separate image (`--no-deps` install; agent digest untouched).
- Placeholders are substituted at render time by `task ui:render`; the image is pinned by digest resolved from ACR, never a tag. Nothing rendered is committed. Leftover placeholders and non-sha256 digests are refused.
- Token: `openssl rand` piped into `kubectl create secret --from-file=/dev/stdin` (no argv). Secret is not in kustomize. `task ui:token` prints it on request; `ROTATE=1 task ui:secret` rotates and restarts.
- Access: ClusterIP + `task ui:open` (port-forward). `task ui:verify` checks 401/200.
- Gotchas: relative OUT paths for included tasks resolve under tasks/; the task shell lacks `$!`.
