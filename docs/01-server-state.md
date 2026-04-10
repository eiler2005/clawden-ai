# Server State

Snapshot date: `2026-04-10`

## Host

- provider: Hetzner Cloud
- instance class: `CX23`
- OS: Ubuntu `24.04 LTS`
- workload shape: one existing application plus one dedicated OpenClaw deployment

## High-level runtime inventory

### Existing service kept unchanged

- app name: `deploy-bridge-1`
- purpose: pre-existing production workload
- project root: `/opt/maxtg-bridge`
- status during setup: left running and not rebuilt

### LightRAG (knowledge graph memory)

- project root: `/opt/lightrag`
- compose files: `/opt/lightrag/docker-compose.yml` + `docker-compose.override.yml`
- image: `ghcr.io/hkuds/lightrag:latest` (upstream official); local build also present as `lightrag-local:latest`
- data dir: `/opt/lightrag/data/` (graph + vector + kv state, file-based)
- port: `127.0.0.1:8020` → container internal port `9621` (not exposed via Caddy)
- input mounts (read-only): `/opt/obsidian-vault` → `/app/data/inputs/obsidian`, `/opt/openclaw/workspace` → `/app/data/inputs/workspace`
- LLM: OmniRoute `light` tier (`http://omniroute:20129/v1`, model=`light`) — routes through Gemini Flash → OpenRouter/Qwen3-8B → Kiro Haiku
- embedding: `gemini-embedding-001` via direct Gemini API key (dim=3072, not routed through OmniRoute)
- storage backend: NetworkX + NanoVectorDB + JsonKV (no external DB)
- ingest script: `/opt/lightrag/scripts/lightrag-ingest.sh` (uses `POST /documents/upload` file-by-file)
- cron: every 30 minutes
- see `docs/10-memory-architecture.md` and `docs/11-lightrag-setup.md`

### Obsidian vault

- path: `/opt/obsidian-vault/`
- purpose: external AI Wiki, fed into LightRAG for knowledge graph indexing
- sync method: **bidirectional Syncthing** between Mac (iCloud vault) and server — NOT git, NOT rsync
- Mac device: `EJ6FHJG` (MacBook-Pro-Denis.local), Server device: `6JODYFX` (ubuntu-4gb-hel1-6)
- folder ID: `obsidian-vault`, type: `sendreceive` on both sides
- connection: via Syncthing global relay (port 22000 blocked by Hetzner cloud firewall)
- Syncthing on Mac: homebrew service (`homebrew.mxcl.syncthing`), config: `~/Library/Application Support/Syncthing/`, GUI: `http://127.0.0.1:8384`
- Syncthing on server: systemd service (`syncthing@deploy`), config: `~/.config/syncthing/`, GUI via SSH tunnel: `ssh -L 8385:127.0.0.1:8384 deploy@<server-host>` → `http://127.0.0.1:8385`
- re-index: manual or after bulk changes — `lightrag-ingest.sh`
- legacy rsync agent (`com.openclaw.obsidian-sync`) still installed but **superseded by Syncthing**

### OpenClaw deployment

- project root: `/opt/openclaw`
- config dir: `/opt/openclaw/config`
- workspace dir: `/opt/openclaw/workspace`
- compose file: `/opt/openclaw/docker-compose.yml`
- env file: `/opt/openclaw/.env`
- reverse proxy: `Caddy`
- public hostname: intentionally omitted from git-safe docs

### Container-side tools (optional)

Installed inside the OpenClaw gateway container image (not on the host OS):

- `ffmpeg` and `ffprobe`
- `whisper` CLI exposed as `/usr/local/bin/whisper`
  - backed by an isolated Python venv at `/opt/openclaw-whisper-venv`

Explicitly not installed on the host OS:

- `whisper`
- `ffmpeg`
- `ffprobe`

That absence is intentional. In this deployment, agent-facing runtime tools belong in the OpenClaw container image, not on the Ubuntu host.

## Network exposure

### Publicly reachable

- `80/tcp` for HTTP to HTTPS redirect
- `443/tcp` for TLS termination and `mTLS`

### Host-local only

- `127.0.0.1:18789` for the OpenClaw gateway publish
- `127.0.0.1:18790` for the bridge/helper publish
- `127.0.0.1:8020` for LightRAG API (port 8020 → container 9621; UFW blocks external access even if bound on 0.0.0.0 internally)
- `127.0.0.1:20128` for OmniRoute dashboard (SSH tunnel access only)
- `127.0.0.1:20129` for OmniRoute OpenAI-compatible API (container-to-container only)

### Administrative access

- `22/tcp` for SSH
- actual server address and SSH details are intentionally kept only in `LOCAL_ACCESS.md`

## Deployment state

The final deployment is a layered setup:

1. `Caddy` handles public TLS and client certificate validation.
2. `Caddy` reverse-proxies both HTTP and WebSocket traffic to `127.0.0.1:18789`.
3. OpenClaw gateway serves the Control UI and backend API from one runtime source.
4. OpenClaw itself uses token auth on the gateway layer.

## Image state

OpenClaw is not running from the untouched upstream image anymore.

Last confirmed healthy image:

- `openclaw-with-iproute2:20260408`

Reason:

- the upstream image did not include `iproute2`
- in this deployment, `bind=lan` caused OpenClaw to depend on `ip neigh show`
- without `iproute2`, the process could enter a bad startup state even though the rest of the config was correct
- the same derived image also includes `ffmpeg` and `openai-whisper` to ensure speech-to-text tooling is available in the OpenClaw runtime (container) context
- the host OS remains lean and does not carry duplicate runtime toolchains for OpenClaw features
- current OpenClaw CLI version in that image: `2026.4.8`

Previous blocked releases: `2026.4.5` — startup instability (high-CPU spin loop, port never bound). Fixed in `2026.4.8`.

## Workspace state

Snapshot date: `2026-04-08`

Workspace directory on host: `/opt/openclaw/workspace/`
Workspace directory in container: `/home/node/.openclaw/workspace/`

### Tracked template files (deployed from git `workspace/`)

| File | Description |
|------|-------------|
| `IDENTITY.md` | Bot name: Бенька 🐾 (цвергшнауцер persona) |
| `SOUL.md` | Anti-sycophancy protocol, values, techno-minimalist purpose |
| `USER.md` | Denis's profile — tech enthusiast, builder, domain expertise |
| `AGENTS.md` | Operating instructions, session protocol, decision approach |
| `INDEX.md` | Master memory catalog: what lives where, navigation |
| `MEMORY.md` | Long-term curated memory: projects, partnerships, professional facts |
| `HEARTBEAT.md` | Lightweight periodic tasks (no heavy scanning) |
| `TOOLS.md` | Workspace tools including lightrag_query |
| `BOOT.md` | Session startup checklist (8-step, includes LightRAG health check) |

### Runtime-managed files (not tracked in git)

| Path | Description |
|------|-------------|
| `memory/YYYY-MM-DD.md` | Daily conversation logs, created by bot |
| `memory/INDEX.md` | Daily note index (bot-managed) |
| `memory/archive/` | Compressed old daily notes (bot-managed) |
| `raw/YYYY-MM-DD-{topic}.md` | Verbatim decision threads, redacted (bot-managed) |
| `BOOTSTRAP.md` | Pre-existing file from initial setup (not modified) |
| `.openclaw/` | Internal bot state (sessions, search index) |
| `state/` | Bot runtime state |
| `.git/` | Workspace git history (managed by OpenClaw internally) |

### Deploy command

```bash
export OPENCLAW_HOST="deploy@<server-host>"
./scripts/deploy-workspace.sh
```

See `docs/09-workspace-setup.md` for full onboarding guide.

## Validation status note

Upgrade to `2026.4.8` confirmed successful (2026-04-08):

- gateway container is `healthy`
- `/healthz` returns `{"ok":true,"status":"live"}`
- `openclaw --version` reports `OpenClaw 2026.4.8`
- `openclaw doctor` reports no errors (startup optimization hints applied)

## Important caveat

The stack now uses a custom Compose healthcheck against `http://127.0.0.1:18789/healthz`.

Operationally relevant truth sources are:

- successful `Caddy` responses over `mTLS`
- successful `mTLS` gate behavior
- successful browser access using the local tokenized URL kept in `secrets/`

During gateway cold starts or config-triggered restarts, `docker compose ps` can temporarily show `starting` or `unhealthy` before converging to `healthy`.

### OmniRoute (smart model routing)

- project root: `/opt/openclaw` (not a separate project — added via `docker-compose.override.yml`)
- source: `/opt/openclaw/omniroute-src` (git clone of diegosouzapw/OmniRoute, `target: runner-base`)
- compose override: `/opt/openclaw/docker-compose.override.yml` (merged automatically by Docker Compose)
- env file: `/opt/openclaw/omniroute.env` (gitignored; see `artifacts/omniroute/omniroute.env.example`)
- dashboard port: `127.0.0.1:20128` → container `20128` (SSH tunnel access only)
- API port: `127.0.0.1:20129` → container `20129` (OpenAI-compatible `/v1/*`, `REQUIRE_API_KEY=true`)
- network: `openclaw_default` (same as openclaw-gateway and LightRAG)
- data volume: `omniroute-data` (SQLite — stores OAuth tokens, combo configs, API keys)
- providers connected:
  - **Kiro** (Claude Sonnet 4.5 / Haiku) — AWS Builder ID OAuth, free unlimited
  - **OpenRouter** — API key hub (routes to Claude 3.5, Kimi K2, Qwen3 and others)
  - **Gemini** — direct API key (`gemini-2.0-flash`), free tier 1500 req/day
- routing tiers (priority order, auto-fallback if provider unavailable):
  - `smart` → Kiro/claude-sonnet-4-5 → OpenRouter/claude-3.5-sonnet → OpenRouter/kimi-k2
  - `medium` → Kiro/claude-3-5-haiku-20241022 → Gemini/gemini-2.0-flash → OpenRouter/qwen3-30b-a3b
  - `light` → Gemini/gemini-2.0-flash → OpenRouter/qwen3-8b → Kiro/claude-3-5-haiku-20241022
- LightRAG integration: **active** — LightRAG LLM binding switched to OmniRoute `light` tier (`LLM_BINDING=openai`, `LLM_BINDING_HOST=http://omniroute:20129/v1`)
- OpenClaw integration: **active** — registered as `omniroute` provider in `openclaw.json` with 3 virtual models (`smart`, `medium`, `light`); Codex/gpt-5.4 stays primary
- Бенька model selection: rule-based heuristics in `workspace/AGENTS.md` — code/complex → smart, chat → medium, LightRAG tasks → light
- auth: `REQUIRE_API_KEY=true` on API port; dashboard password-protected; API key stored in `/opt/openclaw/.env`
