# Changelog

All notable changes to this deployment are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Pending
- LightRAG initial bulk indexing (blocked: Gemini free tier RPD quota, resets UTC midnight)

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
