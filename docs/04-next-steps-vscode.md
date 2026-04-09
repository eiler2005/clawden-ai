# Next Steps In VS Code

This is the recommended sequence for continuing work safely.

## 1. Keep the working folder local until the docs are reviewed

Before any Git initialization or remote push:

- verify that `secrets/` stays ignored
- verify that `LOCAL_ACCESS.md` stays ignored
- verify that no raw `.env`, auth profile, certificate, or tokenized URL was copied into tracked docs

## 2. First verification pass

Use the placeholder host pattern from [`03-operations.md`](./03-operations.md).

Run:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && docker compose ps'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'sudo systemctl status caddy --no-pager'
```

Then validate browser access using the local client certificate and tokenized URL.

## 3. Decide whether to keep the derived image local or publish it

Current deployment depends on a small derived image because the upstream image lacked `iproute2`.

Decision to make:

- keep building the image locally on the server
- or publish a pinned custom image to a controlled registry

If this deployment is meant to last, publishing and pinning the image is the cleaner long-term option.

## 4. Normalize health reporting

The built-in container healthcheck is misleading for this deployment.

Recommended future improvement:

- override the healthcheck in Compose with a custom probe that reflects the real readiness contract

## 5. Decide how much of the public architecture should remain

Current public path is strong enough for controlled use:

- `mTLS` at the edge
- local-only gateway publish
- no direct public OpenClaw port

Still worth deciding:

- whether to keep a public `sslip.io` style hostname
- whether to migrate to a real managed domain
- whether to rotate and reissue client certificates on a schedule

## 6. If you turn this into a real repository

Recommended first tracked content:

- `README.md`
- `docs/`
- `artifacts/`
- `.gitignore`

Recommended next tracked additions:

- `LICENSE` if distribution is planned
- `CHANGELOG.md` if this becomes a maintained operations repo
- simple helper scripts or a `Makefile` for repeatable ops

## 7. Useful next engineering tasks

- pin the exact upstream OpenClaw base image digest in the custom Dockerfile
- add a documented smoke test for the browser and WebSocket flow
- add a deterministic script to refresh the copied `control-ui` assets when the image changes
- replace placeholder host instructions with environment-variable driven scripts
