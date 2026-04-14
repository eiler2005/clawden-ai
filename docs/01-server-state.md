# Server State

Snapshot date: `2026-04-14`

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
- Docker networks: `lightrag_default` + `openclaw_default`; OpenClaw container uses `http://lightrag:9621`
- input mounts (read-only): `/opt/obsidian-vault` → `/app/data/inputs/obsidian`, `/opt/openclaw/workspace` → `/app/data/inputs/workspace`
- LLM: direct Gemini `gemini-2.5-flash-lite` (`MAX_ASYNC=1`, `TIMEOUT=180`) for stable bulk extraction
- embedding: `gemini-embedding-001` via direct Gemini API key (dim=3072, not routed through OmniRoute)
- storage backend: NetworkX + NanoVectorDB + JsonKV (no external DB)
- ingest script: `/opt/lightrag/scripts/lightrag-ingest.sh` (uses `POST /documents/upload` file-by-file)
- active ingest boundary:
  - `/opt/openclaw/workspace/**/*.md`
  - `/opt/obsidian-vault/wiki/**/*.md`
  - `/opt/obsidian-vault/raw/signals/**/*.md`
- excluded from active ingest:
  - `/opt/obsidian-vault/raw/articles/**`
  - `/opt/obsidian-vault/raw/documents/**`
  - legacy vault folders outside `wiki/` and `raw/signals/`
- cron: every 30 minutes
- validation on 2026-04-10: `processed=26`, `failed=0`; query for "Сто лет недосказанности Семихатов" returns `Книги и статьи.md`
- see `docs/10-memory-architecture.md` and `docs/11-lightrag-setup.md`

### Obsidian vault

- path: `/opt/obsidian-vault/`
- purpose: external AI Wiki, fed into LightRAG for knowledge graph indexing
- curated layout:
  - `wiki/` — curated entity/concept/decision/research/session pages plus bot-maintained system files
  - `raw/signals/` — daily Last30Days signal digests written by `signals-bridge`
  - `raw/articles/` and `raw/documents/` — stored sources waiting for curated import
- bot-maintained system pages:
  - `wiki/SCHEMA.md`
  - `wiki/INDEX.md`
  - `wiki/OVERVIEW.md`
  - `wiki/IMPORT-QUEUE.md`
  - `wiki/LOG.md`
- sync method: **bidirectional Syncthing** between Mac (iCloud vault) and server — NOT git, NOT rsync
- Mac device: `EJ6FHJG` (MacBook-Pro-Denis.local), Server device: `6JODYFX` (ubuntu-4gb-hel1-6)
- folder ID: `obsidian-vault`, type: `sendreceive` on both sides
- connection: via Syncthing global relay (port 22000 blocked by Hetzner cloud firewall)
- Syncthing on Mac: homebrew service (`homebrew.mxcl.syncthing`), config: `~/Library/Application Support/Syncthing/`, GUI: `http://127.0.0.1:8384`
- Syncthing on server: systemd service (`syncthing@deploy`), config: `~/.config/syncthing/`, GUI via SSH tunnel: `ssh -L 8385:127.0.0.1:8384 deploy@<server-host>` → `http://127.0.0.1:8385`
- re-index: manual or after bulk changes — `lightrag-ingest.sh`
- legacy rsync agent (`com.openclaw.obsidian-sync`) still installed but **superseded by Syncthing**

### wiki-import bridge

- project root: `/opt/wiki-import`
- compose file: `/opt/wiki-import/docker-compose.yml`
- env file: `/opt/wiki-import/wiki-import.env`
- port: `127.0.0.1:8095`
- network: `openclaw_default`
- purpose: deterministic curated import bridge for `url`, `text`, and `server_path`
- write scope:
  - `/opt/obsidian-vault/raw/articles/**`
  - `/opt/obsidian-vault/raw/documents/**`
  - bot-generated pages under `/opt/obsidian-vault/wiki/**`
  - `wiki/OVERVIEW.md`, `wiki/INDEX.md`, `wiki/IMPORT-QUEUE.md`, `wiki/LOG.md`
- API:
  - `GET /health`
  - `GET /status`
  - `POST /trigger`
  - `POST /lint`

### OpenClaw deployment

- project root: `/opt/openclaw`
- config dir: `/opt/openclaw/config`
- workspace dir: `/opt/openclaw/workspace`
- compose file: `/opt/openclaw/docker-compose.yml`
- env file: `/opt/openclaw/.env`
- reverse proxy: `Caddy`
- public hostname: intentionally omitted from git-safe docs

### Container-side tools (optional)

Installed inside the current OpenClaw gateway container image:

- `iproute2`

Explicitly not installed on the host OS:

- `whisper`
- `ffmpeg`
- `ffprobe`

Also intentionally absent from the current gateway container image:

- `whisper`
- `ffmpeg`
- `ffprobe`

That absence is intentional. Voice transcription was removed to keep the CX23 VPS leaner; it can be revisited later with a lighter CPU-oriented stack or an external API.

## Network exposure

### Publicly reachable

- `80/tcp` for HTTP to HTTPS redirect
- `443/tcp` for TLS termination and `mTLS`

### Host-local only

- `127.0.0.1:18789` for the OpenClaw gateway publish
- `127.0.0.1:18790` for the bridge/helper publish
- `127.0.0.1:8020` for LightRAG API (host-local publish; container port 9621)
- `127.0.0.1:8095` for wiki-import API
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

- `openclaw-with-iproute2:20260412-slim-2026.4.11`

Reason:

- the upstream image did not include `iproute2`
- in this deployment, `bind=lan` caused OpenClaw to depend on `ip neigh show`
- without `iproute2`, the process could enter a bad startup state even though the rest of the config was correct
- Whisper, ffmpeg, and the extra Python toolchain were intentionally removed from the derived image on 2026-04-12 because they added roughly 2+ GB and were not being used
- voice transcription remains a future option, but it is not part of the current production runtime
- the host OS remains lean and does not carry duplicate runtime toolchains for OpenClaw features
- current OpenClaw CLI version in that image: `2026.4.11`

Previous blocked releases: `2026.4.5` — startup instability (high-CPU spin loop, port never bound). Fixed by later releases including the current `2026.4.11`.

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

Upgrade to `2026.4.11` confirmed successful (2026-04-12):

- gateway container is `healthy`
- `/healthz` returns `{"ok":true,"status":"live"}`
- `openclaw --version` reports `OpenClaw 2026.4.11`
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
- deployed version: `v3.6.3`
- checkout pin: local branch `deploy/v3.6.3` at tag `v3.6.3`
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
- LightRAG integration: **active** — OpenClaw can query LightRAG at `http://lightrag:9621`; LightRAG uses direct Gemini for extraction because OmniRoute `light` is too bursty for bulk indexing
- OpenClaw integration: **active** — registered as `omniroute` provider in `openclaw.json` with 3 virtual models (`smart`, `medium`, `light`); Codex/gpt-5.4 stays primary
- Бенька model selection: rule-based heuristics in `workspace/AGENTS.md` — code/complex → smart, chat → medium, lightweight lookups/classification → light
- auth: `REQUIRE_API_KEY=true` on API port; dashboard password-protected; API key stored in `/opt/openclaw/.env`

### Telethon Digest (Telegram channel digest)

- project root: `/opt/telethon-digest`
- compose file: `/opt/telethon-digest/docker-compose.yml`
- env file: `/opt/telethon-digest/telethon.env` (gitignored secret; local source: `secrets/telethon-digest/telethon.env`)
- source artifact: `artifacts/telethon-digest/`
- network: `openclaw_default` (external; used to reach OmniRoute at `http://omniroute:20129/v1`)
- runtime containers:
  - `telethon-digest-cron-bridge` — always-on HTTP trigger bridge for OpenClaw Cron Jobs
  - `telethon-digest` — one-shot worker container used by manual runs / compose runs
- Docker volumes:
  - `telethon-sessions` — Telethon user session file
  - `telethon-state` — per-channel watermarks, last run timestamp, and `pulse-profile.json` for learned interest buckets
- runtime config: `/opt/telethon-digest/config.json`, generated from Telegram folders by `sync_channels.py`
- output target: `telegram-digest` topic in `Benka_Clawbot_SuperGroup`
- schedule: OpenClaw Cron Jobs at 08:00, 11:00, 14:00, 17:00, 21:00 Moscow time
- read scope: application-enforced allowlist, `read_only=true`, `read_broadcast_channels_only=true`
- current allowlist: `news`, `evolution`, `startups`, `growth.me`, `fintech`, `investing`, `work`, `eb1`, `гребенюк`, `personal`, `faang`
- catalog: 18 folders, 499 dialogs, 426 broadcast channels recorded; 240 broadcast channels selected by current allowlist
- bridge endpoints: `GET /health`, `GET /status`, `POST /trigger`
- status: running as `telethon-digest`; job timing managed by OpenClaw Gateway cron store

### Signals Bridge

- project root: `/opt/signals-bridge`
- compose file: `/opt/signals-bridge/docker-compose.yml`
- env file: `/opt/signals-bridge/signals.env` (gitignored secret)
- source artifact: `artifacts/signals-bridge/`
- network: `openclaw_default`
- container: `signals-bridge` — always-on, internal 5-minute scheduler (no external cron needed)
- port: `127.0.0.1:8093`
- bridge endpoints: `GET /health`, `GET /status`, `POST /trigger`
- Docker volumes: `signals-bridge-sessions`, `signals-bridge-state`
- runtime config: `/opt/signals-bridge/config.json` (volume-mounted)
- output targets: `signals` topic (5-min signal alerts), `last30daysTrend` topic (daily 07:00 MSK World Radar)
- key env vars in `signals.env`:
  - `OPENROUTER_API_KEY` — enables LLM planning/reranking in external last30days script (exits local_mode)
  - `LAST30DAYS_PLANNER_MODEL=google/gemini-2.5-flash-lite` — overrides default invalid model ID
  - `LAST30DAYS_RERANK_MODEL=google/gemini-2.5-flash-lite` — same for rerank step
  - `OMNIROUTE_API_KEY` — signals enrichment via internal OmniRoute
- Last30Days source counts (typical run): `github:38, x:29, hn:6–12`
- Last30Days posted themes per run: 10 (6 before HN companion pass was added)
- status: running; Last30Days scheduled at 07:00 MSK, signals every 5 min
