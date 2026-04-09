# OpenClaw Installation

## Goals

The deployment was designed around four constraints:

1. avoid disrupting the existing production container
2. avoid a host-wide Node/OpenClaw install
3. keep sensitive access material out of Git
4. expose OpenClaw publicly only through a hardened reverse proxy path

## Chosen deployment shape

OpenClaw was deployed as a separate Docker Compose project under `/opt/openclaw`.

Why this was chosen:

- clean isolation from the pre-existing app
- easy rollback by removing one project directory
- explicit config and workspace paths
- predictable Docker-only lifecycle
- easy capture of redacted artifacts for documentation

## Runtime boundary policy

OpenClaw is a Dockerized workload on the Hetzner server. Treat the container runtime as the application environment.

Policy:

- if a tool is needed by OpenClaw, its agents, or gateway-executed workflows, install it into the derived OpenClaw image or invoke it with `docker compose exec`
- do not install OpenClaw-adjacent runtime packages on the host OS unless the requirement is explicitly host-administrative
- when debugging command availability, verify both contexts:
  - host OS
  - `openclaw-gateway` container

This rule exists because a host-only install can appear successful while remaining invisible to the actual OpenClaw runtime.

## What differed from the upstream happy path

The real deployment did not follow the simplest upstream path end to end.

### 1. Compose and image behavior had to be aligned

The upstream Compose material and the pulled image behavior did not line up cleanly, so the local Compose file was adapted to the actual image entrypoint behavior.

### 2. OAuth bootstrap was done through a temporary local-auth transfer

To materialize a working OpenClaw auth profile in a headless server environment:

1. a local Codex auth file was copied to the server temporarily
2. OpenClaw was allowed to materialize its own provider profile
3. the temporary copied auth file was deleted again
4. the temporary mount was removed from the deployment

Result:

- OpenClaw now has its own auth profile on the server
- the temporary bootstrap file is no longer part of the live deployment

### 3. Public access evolved through several iterations

The public access path changed during debugging:

- localhost-only access over SSH tunnel
- reverse proxy experiments
- early public access protected by HTTP auth
- final public access protected by `mTLS`

The final path is the one documented here. Earlier iterations are intentionally not treated as the target architecture.

### 4. A derived runtime image became necessary

The final deployment uses a small derived image instead of the raw upstream image because `iproute2` was missing and the chosen network mode required it.

Derived image:

- `openclaw-with-iproute2:20260405`

Upgrade history:

- `openclaw-with-iproute2:20260405` (`OpenClaw 2026.4.2`) — first stable derived image
- `openclaw-with-iproute2:20260406/07` (`OpenClaw 2026.4.5`) — startup instability; blocked
- `openclaw-with-iproute2:20260408` (`OpenClaw 2026.4.8`) — current production; `2026.4.5` regression fixed

## Final deployed shape

### OpenClaw runtime

- gateway bind mode: `lan`
- gateway auth mode: `token`
- trusted proxies: localhost and Docker bridge
- host publish:
  - `127.0.0.1:18789:18789`
  - `127.0.0.1:18790:18790`

### Public access layer

- reverse proxy: `Caddy`
- public ports:
  - `80/tcp`
  - `443/tcp`
- access control:
  - TLS server certificate
  - mandatory client certificate for browser access
- traffic model:
  - full HTTP + WebSocket reverse proxy to `127.0.0.1:18789`
  - OpenClaw gateway serves both Control UI and backend

### Token handling

- WebSocket auth remains token-based inside OpenClaw
- the tokenized browser URL is stored locally under `secrets/`
- that URL must never be committed to Git

## Server-side files of interest

- `/opt/openclaw/docker-compose.yml`
- `/opt/openclaw/.env`
- `/opt/openclaw/config/openclaw.json`
- `/opt/openclaw/config/agents/main/agent/auth-profiles.json`
- `/opt/openclaw/Dockerfile.iproute2`
- `/etc/caddy/Caddyfile`
- `/etc/caddy/certs/`

## Container-side Whisper (optional)

Whisper is installed inside the **OpenClaw gateway container image**, because agent tooling runs in that same container runtime context.

Assumption: `OPENCLAW_HOST` is set as described in `docs/03-operations.md`.

### Build + enable

This deployment bakes Whisper into the derived runtime image (`/opt/openclaw/Dockerfile.iproute2`) and then switches `OPENCLAW_IMAGE`.

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/openclaw

  sudo docker build -t openclaw-with-iproute2:20260405 -f Dockerfile.iproute2 .
  sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260405/" .env
  sudo docker compose up -d --force-recreate openclaw-gateway
'
```

### Verify (inside the container)

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  docker compose exec -T openclaw-gateway sh -lc "
    which whisper &&
    which ffmpeg &&
    which ffprobe &&
    python3 --version &&
    pip3 --version
  "
'
```

### Host cleanup (recommended)

If Whisper was installed on the host during early experiments, remove it to keep the host OS lean.

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo rm -f /usr/local/bin/whisper
  sudo rm -rf /opt/openclaw/.venv-whisper
  sudo apt-get purge -y ffmpeg python3-pip python3-venv || true
  sudo apt-get autoremove -y || true
  sudo apt-get clean || true
'
```

Verify the host is intentionally clean:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  command -v whisper || echo host_whisper_absent
  command -v ffmpeg || echo host_ffmpeg_absent
  command -v ffprobe || echo host_ffprobe_absent
'
```

## Redacted artifacts in this folder

- [`../artifacts/openclaw/docker-compose.redacted.yml`](../artifacts/openclaw/docker-compose.redacted.yml)
- [`../artifacts/openclaw/caddy.redacted.Caddyfile`](../artifacts/openclaw/caddy.redacted.Caddyfile)
- [`../artifacts/openclaw/openclaw.json`](../artifacts/openclaw/openclaw.json)
- [`../artifacts/openclaw/env.redacted.example`](../artifacts/openclaw/env.redacted.example)
- [`../artifacts/openclaw/auth-profile.redacted.json`](../artifacts/openclaw/auth-profile.redacted.json)
