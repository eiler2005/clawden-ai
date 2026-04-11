# Changelog

All notable changes to this deployment are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Pending
- Monitor the first scheduled Telethon Digest daemon run after deployment.

## [2026-04-10] — telethon-digest: Telegram channel digest service

### Added
- **`telethon-digest` Docker service**: reads 150–200 Telegram channels via Telethon MTProto,
  scores posts by folder priority × pin boost, summarizes via OmniRoute `medium`, posts 4× daily
  (08:00/12:00/16:00/20:00 МСК) to `telegram-digest` topic in `Benka_Clawbot_SuperGroup`.
- Service files prepared for `/opt/telethon-digest/`:
  `auth.py`, `digest_worker.py`, `reader.py`, `scorer.py`, `link_builder.py`,
  `summarizer.py`, `poster.py`, `state_store.py`, `sync_channels.py`, `Dockerfile`, `requirements.txt`.
- `artifacts/telethon-digest/` added to repo with all Python modules, standalone `docker-compose.yml`,
  `config.example.json`, and `telethon.env.example` (redacted).
- Standalone Compose project uses the external `openclaw_default` network plus `telethon-sessions`
  and `telethon-state` named Docker volumes.
- Local gitignored secret source created at `secrets/telethon-digest/telethon.env`.
- Telethon user session authorized and stored in the `telethon-sessions` Docker volume.
- Telegram folders synced into server `config.json`: 18 folders, 499 dialogs, 426 broadcast channels.
- Read scope locked down with explicit allowlist and `read_broadcast_channels_only=true`.
- Local gitignored catalog copy created at `secrets/telethon-digest/config.local.json`.
- `docs/13-ai-assistant-architecture.md` updated with Telegram Channel Digest section.
- `docs/14-telethon-digest-handoff.md` added as the continuation/runbook source for future LLMs.

### Fixed
- Telethon Digest summarizer now handles OmniRoute `text/event-stream` responses as well as JSON
  chat completions, and falls back locally if the LLM refuses summarization.

### Verified
- Full smoke test read the allowlisted channels, selected top posts, and posted digest chunks to the
  `telegram-digest` topic through the OpenClaw Telegram bot.
- Synthetic OmniRoute summarization smoke test passes after the SSE parser fix.
- Daemon started successfully; APScheduler next run is managed inside the `telethon-digest` container.

## [2026-04-10]

### Fixed
- OpenAI Codex rate-limit failover: added `agents.defaults.model.fallbacks` in `openclaw.json` so
  when Codex hits its usage cap the gateway automatically retries `omniroute/smart` → `omniroute/medium`
  → `omniroute/light` instead of surfacing the error to the user. Config hot-reloaded on the live server.
- OmniRoute combo model IDs corrected: `smart` now uses `kiro/claude-sonnet-4.5` (was `claude-sonnet-4-5`
  with dashes), `medium` and `light` now use `kiro/claude-haiku-4.5` (was `claude-3-5-haiku-20241022`).
  All three tiers verified working.

### Added
- `docs/13-ai-assistant-architecture.md`: comprehensive description of AI assistant design principles,
  model routing (primary + OmniRoute fallback tiers), Telegram surface interaction model, memory
  classes, LightRAG integration rules, approval gates, and anti-patterns.
- AGENTS.md updated on server: model-selection and fallback sections updated; response footer instruction
  added (`_model · ctx% · memory_` at end of every Telegram reply).
- Daily memory file `memory/2026-04-10.md` created on server with today's decisions and open items.

### Added
- Telegram channel architecture policy:
  - final / minimal / safe-first topology for DM, ops supergroup topics, work email, Telegram digest, signals, family, knowledge, ideas, and sandbox
  - least-privilege permission matrix for each Telegram surface
  - OpenClaw behavior modes and approval boundaries
  - conservative memory and RAG/Obsidian ingestion gates
  - redacted implementation draft in `artifacts/openclaw/telegram-surfaces.redacted.json`
  - runtime policy file in `workspace/TELEGRAM_POLICY.md`
- Telegram policy deployed to the live server:
  - `workspace/TELEGRAM_POLICY.md` deployed to `/opt/openclaw/workspace/`
  - ops forum topics created in the live supergroup: `inbox`, `approvals`, `tasks`, `signals`, `system`, `rag-log`, `work-email`, `telegram-digest`
  - server-local topic map written to `/opt/openclaw/config/telegram-topic-map.json`
  - server-local live surface policy written to `/opt/openclaw/config/telegram-surfaces.policy.json`
  - full redacted architecture document copied into server workspace `raw/` for LightRAG indexing

### Fixed
- LightRAG indexing repaired on the live server:
  - attached `lightrag-lightrag-1` to `openclaw_default` with DNS alias `lightrag`
  - replaced public `0.0.0.0:9621` publish with host-local `127.0.0.1:8020`
  - changed healthcheck from missing `curl` to Python `urllib`
  - switched LightRAG extraction from OmniRoute `light` to direct Gemini `gemini-2.5-flash-lite`
  - reprocessed the corpus successfully (`processed=26`, `failed=0`)

### Changed
- Expanded LightRAG documentation across README, memory architecture, setup, operations, and workspace tool docs:
  - why LightRAG exists
  - what data is ingested
  - how cron/upload/reprocess updates the index
  - how OpenClaw queries it
  - when LightRAG results are trustworthy versus when live checks are required

---

## [2026-04-10] — OmniRoute smart model routing layer + Бенька model selection

### Added
- **OmniRoute** deployed as additional service in OpenClaw Docker Compose (via `docker-compose.override.yml`)
  - Source cloned to `/opt/openclaw/omniroute-src`
  - Dashboard: `127.0.0.1:20128` (SSH tunnel access only)
  - API: `127.0.0.1:20129` (OpenAI-compatible `/v1/*`, `REQUIRE_API_KEY=true`)
  - Network: `openclaw_default` (same as openclaw-gateway and lightrag)
  - Providers connected: Kiro (AWS Builder ID OAuth, Claude Sonnet/Haiku, free unlimited), OpenRouter (API key hub — Claude 3.5, Kimi K2, Qwen3), Gemini (API key, Flash)
  - Routing tiers (priority order, auto-fallback):
    - `smart`: Kiro/claude-sonnet-4-5 → OpenRouter/claude-3.5-sonnet → OpenRouter/kimi-k2
    - `medium`: Kiro/claude-3-5-haiku → Gemini/gemini-2.0-flash → OpenRouter/qwen3-30b
    - `light`: Gemini/gemini-2.0-flash → OpenRouter/qwen3-8b → Kiro/claude-3-5-haiku
- **LightRAG LLM** switched from direct Gemini to OmniRoute `light` tier (`LLM_BINDING=openai`, `LLM_BINDING_HOST=http://omniroute:20129/v1`)
- **OpenClaw**: OmniRoute registered as additional provider in `openclaw.json` (3 virtual models: `smart`, `medium`, `light`); Codex/gpt-5.4 remains primary
- **Бенька model selection rules** added to `workspace/AGENTS.md` — rule-based heuristics for choosing routing tier by task complexity (code → smart, chat → medium, LightRAG → light)
- **SSH TCP forwarding** enabled for `deploy` user via `/etc/ssh/sshd_config.d/50-deploy-forwarding.conf` (was blocked by hardening config)
- `artifacts/omniroute/` — redacted compose override and env example added to repo

### Changed
- `docs/01-server-state.md`: OmniRoute service entry, ports 20128/20129, actual providers and tiers
- `docs/03-operations.md`: OmniRoute operations section (start/stop/logs/tunnel/upgrade/bootstrap)
- `README.md`: architecture diagram updated with OmniRoute layer; new "Model Routing" section; tech stack and features updated

---

## [2026-04-09b] — Syncthing bidirectional sync + clawden-ai GitHub release

### Added
- **Syncthing bidirectional vault sync** — replaces one-way rsync
  - Mac (`EJ6FHJG`, homebrew service) ↔ Server (`6JODYFX`, systemd `syncthing@deploy`)
  - Folder ID: `obsidian-vault`, type `sendreceive`, connection via global relay
  - Bot can now write notes directly to vault; changes appear in Obsidian on Mac
- **GitHub repo published**: `eiler2005/clawden-ai` (public, MIT)
  - Sensitive files gitignored: `workspace/USER.md`, `MEMORY.md`, `SOUL.md`, daily notes
- **OpenClaw elevated permissions**: `profile=full`, `exec.security=full`, `elevated.enabled=true`, `fs.workspaceOnly=false`
- **`/opt/obsidian-vault` mounted** into `openclaw-gateway` container with `rw` access

### Changed
- `CLAUDE.md`: added "Commit Permission Rule" — no commit/push without explicit user approval
- `docs/03-operations.md`: Syncthing setup guide added, legacy rsync marked deprecated
- `docs/01-server-state.md`: Obsidian sync method updated to reflect Syncthing
- `README.md`: architecture diagram, tech stack, quick ops updated for Syncthing

---

## [2026-04-09] — Memory system + LightRAG

### Added
- **LightRAG knowledge graph** — deployed at `127.0.0.1:8020`, Docker compose override pattern
  - LLM: `gemini-2.0-flash`, Embedding: `gemini-embedding-001` (one API key)
  - File-based storage: NetworkX + NanoVectorDB + JsonKV (no external DB)
  - Cron: re-index every 30 min via `/opt/lightrag/scripts/lightrag-ingest.sh`
- **Three-layer memory architecture** (Live > Raw > Derived)
  - `workspace/INDEX.md` — master memory catalog
  - `workspace/memory/INDEX.md` — daily note index
  - `workspace/raw/` — verbatim decision threads (redacted, git-tracked)
  - `workspace/memory/archive/` — compressed old daily notes
- **Obsidian vault sync** — one-way rsync from Mac iCloud vault to `/opt/obsidian-vault/`
  - launchd agent on Mac (`com.openclaw.obsidian-sync`), every 15 min
  - `TRIGGER_REINDEX=true` calls LightRAG ingest after sync
- **`lightrag_query` tool** in `workspace/TOOLS.md`
  - endpoint: `POST http://lightrag-lightrag-1:9621/query {"query": "...", "mode": "hybrid"}`
  - replaces bulk-reading archives: 1 query → ~2KB answer
- **`workspace/BOOT.md`** — 8-step session startup checklist
- **`workspace/AGENTS.md`** — memory protocol, promotion criteria for raw/, boot algorithm
- Scripts: `setup-lightrag.sh`, `sync-obsidian.sh`, `create-lightrag-env.sh`

### Fixed
- `exec denied: host=gateway security=deny` — browser plugin now enabled for agent, SSRF private network allowed
- LightRAG unreachable from bot — connected `lightrag_default` → `openclaw_default` Docker network
- Wrong URL `http://lightrag:8020` → `http://lightrag-lightrag-1:9621` (correct Docker DNS)
- Ingestion: switched from `POST /documents/scan` (doesn't recurse) to `POST /documents/upload` file-by-file
- Volume mount path: `/app/inputs/` → `/app/data/inputs/` (LightRAG actual `INPUT_DIR`)
- `memory/2026-04-08.md` — removed duplicate stale bootstrap entries
- `memory/INDEX.md` — updated from `_(none yet)_` to reflect actual state

### Changed
- `openclaw.json`: removed `browser` from agent deny list; `dangerouslyAllowPrivateNetwork: true`
- `workspace/TOOLS.md`: updated LightRAG endpoint URL

---

## [2026-04-08] — Bot personalisation + upgrade

### Added
- Bot identity: **Бенька** 🐾 (цвергшнауцер, anti-sycophancy, direct + light playful tone)
- `workspace/IDENTITY.md`, `workspace/SOUL.md`, `workspace/USER.md`, `workspace/MEMORY.md`
- `workspace/HEARTBEAT.md` — weekly lightweight maintenance tasks
- Telegram group support: bot responds to mentions in group `<telegram-group-id>` without `/start`
- `openai-whisper` + `ffmpeg` baked into derived container image for voice transcription
- `OPENCLAW_NO_RESPAWN=1` + `NODE_COMPILE_CACHE` for faster startup on CX23

### Fixed
- Upgraded from `2026.4.5` (high-CPU spin-loop, port never bound) → `2026.4.8` (stable)
- `iproute2` added to derived image — required for `bind=lan` network mode
- `BOOTSTRAP.md` removed after initial setup completed

### Changed
- Container image: `openclaw-with-iproute2:20260408` (derived from upstream)
- Disk cleanup: removed 4 old `openclaw-with-iproute2` images + build cache (freed ~27 GB, 67% disk free)

---

## [2026-04-04] — Initial deployment

### Added
- Hetzner CX23 provisioned (Ubuntu 24.04)
- OpenClaw deployed under `/opt/openclaw` (Docker Compose)
- Caddy reverse proxy with mTLS — client certificate auth
- Telegram bot connected (`dmPolicy: allowlist`, token auth on WebSocket layer)
- Pre-existing `deploy-bridge-1` service left untouched
- `docs/` ops package: server state, installation, operations, architecture, security, git policy
- `LOCAL_ACCESS.md` + `secrets/` for private access materials (gitignored)
- UFW: only `22/tcp`, `80/tcp`, `443/tcp` open
