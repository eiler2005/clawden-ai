# OpenClaw Deployment Handoff

Sanitized, git-safe documentation for an OpenClaw deployment on a Hetzner VM.

This folder is not the live application source tree. It is an operations and handoff package that captures:

- the deployment architecture
- the server layout
- the deployment decisions made during setup
- the security posture
- the git/redaction rules required before publishing anything

## Current deployment summary

- OpenClaw runs as a dedicated Docker Compose project under `/opt/openclaw`
- the pre-existing `deploy-bridge-1` service was intentionally left untouched
- public access terminates at `Caddy` on `80/443`
- browser access is protected with `mTLS` using a client certificate
- `Caddy` reverse-proxies full Control UI + API traffic to local OpenClaw on `127.0.0.1:18789`
- OpenClaw auth remains in token mode for the WebSocket layer
- a small derived image is used because the upstream image lacked `iproute2`, which was required for the chosen network model
- optional: `ffmpeg` + `openai-whisper` are baked into the derived image so transcription tooling exists in the same container runtime where OpenClaw executes tools
- OpenClaw-related runtime tooling is container-only by policy; the Hetzner host OS is intentionally kept free of `whisper`, `ffmpeg`, and similar agent-facing packages

Current operational state (as of 2026-04-08):

- production runtime: `openclaw-with-iproute2:20260408` (`OpenClaw 2026.4.8`) — healthy
- `OpenClaw 2026.4.5` was tested, found unstable (high-CPU startup spin-loop), and remains blocked
- workspace personalisation completed: bot identity "Бенька" (🐾), personality, and user profile active
- see `docs/06-command-log.md` for full history

## Repository intent

This folder is meant to be safe to turn into a Git repository after review.

Safe to commit:

- documentation
- redacted artifacts
- `.gitignore`
- `CLAUDE.md`
- `.claude/settings.json`
- `.claude/hooks/`

Must stay local-only:

- `LOCAL_ACCESS.md`
- everything under `secrets/`
- raw `.env` files
- raw auth profiles
- client certificates, passwords, and tokenized URLs

## Recommended reading order

1. [`docs/01-server-state.md`](./docs/01-server-state.md) — host, image, network, workspace state
2. [`docs/02-openclaw-installation.md`](./docs/02-openclaw-installation.md) — deployment shape and decisions
3. [`docs/07-architecture-and-security.md`](./docs/07-architecture-and-security.md) — security model and applied settings
4. [`docs/03-operations.md`](./docs/03-operations.md) — SSH commands, web UI connection, workspace ops
5. [`docs/09-workspace-setup.md`](./docs/09-workspace-setup.md) — bot personalisation and onboarding
6. [`docs/08-git-and-redaction-policy.md`](./docs/08-git-and-redaction-policy.md) — git safety rules

## Local-only materials

Actual connection details and access materials are intentionally kept out of the git-safe docs.

- private server access notes live in [`LOCAL_ACCESS.md`](./LOCAL_ACCESS.md)
- local browser/client access materials live under `secrets/`

Both are already ignored by [`.gitignore`](/Users/DenisErmilov/aiprojects/openclaw_firststeps/.gitignore).

## AI agent guardrails

This repository also includes Claude Code guardrails:

- `CLAUDE.md` for project-level instructions
- `.claude/settings.json` for shared permissions and hooks
- `.claude/hooks/` for lightweight safeguards against unsafe Git staging and host-level OpenClaw runtime installs

These files are intentionally generic, secret-free, and safe to commit.
