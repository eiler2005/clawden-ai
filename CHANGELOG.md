# Changelog

All notable changes to this deployment are documented here.  
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Added
- **`artifacts/signals-bridge/`**: new standalone signals pipeline artifact with internal 5-minute
  scheduler, AgentMail + Telethon adapters, deterministic rule matcher, Redis-backed event/state
  store, cheap OmniRoute-light enrichment path, Telegram poster, config/env templates, auth helper,
  and focused unit tests.
- **`scripts/deploy-signals-bridge.sh`**: deployment helper for `/opt/signals-bridge`; keeps the
  service independent from OpenClaw Cron Jobs, hydrates missing bot/router secrets from the shared
  OpenClaw env when available, and validates `GET /health` after restart.
- **`artifacts/agentmail-email/`**: new AgentMail inbox-email pipeline artifact with standalone
  `docker-compose.yml`, `cron_bridge.py`, `agent_runner.py`, prompt builders, Redis-backed
  derived-event buffer, Telegram poster, config/env templates, and OpenClaw cron sync helper.
- **`artifacts/agentmail-email/agentmail_api.py`**: direct AgentMail HTTP adapter for inbox
  listing, message listing, thread reads, and mailbox label updates.
- **`scripts/deploy-agentmail-email.sh`**: deployment helper for `/opt/agentmail-email`,
  Python-first bridge deployment, central OpenClaw cleanup, cron sync, and post-deploy Docker cleanup.
- **Telegram topology**: new `inbox-email` topic/surface added to policy/config docs next to
  `work-email` and `telegram-digest`.
- **`skills/`**: repo-managed project skill catalog added, starting with
  `skills/openclaw-cron-maintenance/SKILL.md` as the canonical playbook for OpenClaw cron-store
  maintenance and hanging-CLI recovery.
- **`docs/14-codex-skills.md`**: new catalog for custom Codex skills, their scope boundaries,
  install/sync pattern, and the planned next skill set for this deployment.

### Changed
- **Signals architecture**: `signals-bridge` now uses its own internal **5-minute** scheduler
  instead of any 30-second loop or OpenClaw cron job, and the enrichment path is explicitly limited
  to cheap `OmniRoute light` calls with low token settings plus a local fallback; GPT-5.4 is not
  used in the signals ingestion path.
- **Signals batch rendering**: signal mini-batches now retain a compact email excerpt and include a
  direct Telegram source link for Telegram-derived items, making manual review faster inside the
  `signals` topic.
- **Signals config layout**: public docs/templates no longer embed Denis-specific signal rules;
  the runtime now supports loading real local rule-sets from separate JSON files via `rule_files`
  (for example `secrets/signals-bridge/rules/*.json`).
- **`README.md` / `docs/03-operations.md` / `docs/13-ai-assistant-architecture.md`**: now document
  the standalone signals service, new Redis streams `ingest:jobs:signals` / `ingest:events:signals`,
  and the low-cost model policy for trading-style signals.
- **`artifacts/agentmail-email/cron_bridge.py`**: scheduled digests no longer disappear when the
  derived-event window is empty; the bridge now posts an explicit empty-window Telegram recap and
  marks the slot as delivered instead of silently skipping it.
- **`artifacts/agentmail-email/cron_bridge.py` / `poster.py`**: 5-minute `poll` runs are now
  internal-only (no Telegram mini-batches in `inbox-email`), while scheduled digests render
  directly from the real mailbox window and include exact message counts, sender counts, and
  per-message subjects for the slot.
- **`artifacts/agentmail-email/cron_bridge.py`**: the inbox-email 5-minute poll now runs from an
  internal scheduler inside the bridge instead of an OpenClaw cron job, and a deterministic
  prefilter skips obvious empty / low-signal windows before any LLM poll analysis.
- **AgentMail digest windows**: scheduled runs are now anchored to the fixed Moscow schedule
  boundaries (`08:00`, `13:00`, `16:00`, `20:00`) instead of drifting after a manual trigger.
- **`artifacts/telethon-digest/pulse.py`**: `Пульс дня` вынесен в отдельный модуль с общими
  правилами дедупликации по смысловому факту, fallback на реальные storyline из digest-контента,
  и без пустой заглушки про отсутствие сквозных тем.
- **`artifacts/telethon-digest/pulse.py`**: added interest-bucket ranking with persisted profile
  state in `/app/state/pulse-profile.json`; pulse selection now balances repeated signal, Denis-fit
  buckets, novelty, and diversity instead of only repeated news pressure.
- **`artifacts/telethon-digest/sync-openclaw-cron-jobs.sh`** and
  **`artifacts/agentmail-email/sync-openclaw-cron-jobs.sh`**: no longer depend on
  `openclaw cron list/add/remove`; they now patch the gateway cron store directly,
  back it up, and restart the gateway to avoid the hanging CLI path on this server.
- **Telethon Digest schedule**: окна обновлены до `08:00`, `11:00`, `14:00`, `17:00`, `21:00`
  Moscow time across config, cron sync, deploy helper, and ops docs.
- **`README.md`**: repository structure, integration-bus status, quick ops, and feature list now
  include the AgentMail inbox-email pipeline.
- **OpenClaw runtime image**: production first moved from `openclaw-with-iproute2:20260408` to
  a slim image without Whisper, and then to `openclaw-with-iproute2:20260412-slim-2026.4.11`;
  the image still keeps only `iproute2` and no longer bakes in Whisper, ffmpeg, or the extra
  Python venv/toolchain.
- **OmniRoute**: upgraded from `3.5.9` to `3.6.3`, pinned in `/opt/openclaw/omniroute-src`
  on local branch `deploy/v3.6.3`, rebuilt in place with the existing `omniroute-data` volume.
- **`README.md` / `docs/03-operations.md` / `docs/13-ai-assistant-architecture.md`**: now show
  `agentmail-email-bridge` as its own Docker service in the main architecture, document the
  recovery/backfill path via `lookback_minutes`, and describe the Python-first AgentMail flow.
- **`artifacts/agentmail-email/`**: removed embedded OpenClaw runtime path and removed AgentMail MCP
  from the active runtime path; the bridge now reads mailbox data directly over AgentMail HTTP,
  while OpenClaw only handles JSON-only classification and digest generation.
- **`artifacts/agentmail-email/sync-openclaw-cron-jobs.sh`**: the token-spending `*/5` poll cron
  job was removed entirely; OpenClaw now manages only the four digest slots for inbox-email.
- **`artifacts/agentmail-email/cron_bridge.py`**: trigger payload now accepts `lookback_minutes`
  for manual catch-up windows; poll/digest status tails include concise runtime summaries; label
  commit now tolerates per-message `404 NotFoundError` instead of failing the whole run.
- **`artifacts/agentmail-email/prompts.py`**: OpenClaw prompts now operate on pre-fetched
  thread snapshots / derived events only and explicitly disallow mailbox tools.
- **`artifacts/openclaw/openclaw.json`**: removed `mcp.servers.agentmail` and tightened
  `tools.profile` back to `"coding"`.
- **`scripts/deploy-agentmail-email.sh`**: post-deploy validation now checks that the 5-minute
  poll cron job is absent, that the four digest cron jobs remain enabled with next scheduled runs,
  and it still removes stale AgentMail-specific env/config coupling from the shared OpenClaw deployment.
- **Server cleanup**: stale email Redis lock/pending entry removed after embedded-runtime rollback;
  unused Docker build cache cleared and the bridge image size dropped from ~2.78 GB to ~229 MB.
- **`README.md` / `docs/01-server-state.md` / `docs/02-openclaw-installation.md` / `docs/03-operations.md` / `artifacts/openclaw/env.redacted.example`**:
  updated to reflect that voice transcription is disabled in production for now and may return later
  through a lighter CPU-oriented stack or an external API.
- **`docs/01-server-state.md` / `docs/03-operations.md` / `docs/13-ai-assistant-architecture.md`**:
  updated to reflect current OpenClaw `2026.4.11` and OmniRoute `3.6.3` runtime state.
- **`docs/03-operations.md`**: added AgentMail inbox-email deploy/runbook section.
- **`docs/12-telegram-channel-architecture.md`** and **`docs/13-ai-assistant-architecture.md`**:
  added `Inbox Email` surface, bus streams `ingest:jobs:email` / `ingest:events:email`, and
  near-real-time poll + scheduled digest architecture.

### Verified
- `python3 -m unittest discover -s artifacts/signals-bridge/tests -p 'test_*.py'`
- `python3 -m py_compile artifacts/signals-bridge/*.py artifacts/signals-bridge/tests/*.py`
- `bash -n scripts/deploy-signals-bridge.sh`
- `agentmail-email-bridge` now starts as a lightweight Python image (`229 MB` on server after rebuild).
- `/trigger` returns `202` and enqueues `poll` jobs into `ingest:jobs:email`.
- Bridge consumer loop starts successfully and performs direct AgentMail API reads / label updates.
- Manual `poll` finished with `exit_code=0` on `2026-04-11`; the window had no publishable emails, so
  the empty-window path completed without Telegram posting or label mutations.
- Manual `poll lookback=1440` finished with `exit_code=0` on `2026-04-12`; it scanned 32 threads,
  produced 1 publishable event, and applied `benka/polled=23`, `benka/low-signal=6` with one
  missing message id skipped safely.
- Manual `editorial` digest finished with `exit_code=0` on `2026-04-12`; it summarized the
  derived event buffer and applied `benka/digested=1`.

## [2026-04-11c] — Fix sync-openclaw-cron-jobs.sh duplicate prevention

### Fixed
- **`sync-openclaw-cron-jobs.sh`**: `read_existing_job_ids()` now uses `openclaw cron list`
  CLI output instead of reading the JSON file directly. Parses JSON output first, falls back
  to UUID extraction from text table lines. Eliminates silent failures that caused duplicates.
- Removed unused `OPENCLAW_CRON_STORE` variable from the script.

## [2026-04-11b] — Integration bus: async LightRAG ingest via ingest:rag:queue

### Added
- **`ingest:rag:queue` Redis stream**: LightRAG file uploads now go through the bus
  instead of being called synchronously inside the digest pipeline.
- **`rag_consumer_loop()`** in `cron_bridge.py`: second background thread that reads
  from `ingest:rag:queue` (consumer group `rag-workers`), uploads each file to
  `LightRAG /documents/upload`, calls `reprocess_failed`, writes `dlq:failed` on error.
- `_upload_file_to_lightrag_sync()` in `cron_bridge.py`: synchronous httpx upload
  used by the RAG consumer thread (no aiohttp needed in thread context).

### Changed
- **`persistence.py`**: `persist_digest()` now calls `_enqueue_lightrag_uploads()`
  instead of `_upload_paths_to_lightrag()` directly. If `REDIS_URL` is set, file paths
  are pushed to `ingest:rag:queue`; falls back to direct HTTP if Redis unavailable.
- **`cron_bridge.py`**: `main()` starts two background threads — `digest-consumer`
  (unchanged) and new `rag-consumer`.

### Verified
Digest triggered → `persistence.py` pushed `interval-*.md` to `ingest:rag:queue` →
`rag-consumer` uploaded to LightRAG HTTP 200 → `reprocess_failed` called → XPENDING=0, DLQ=0.

## [2026-04-11] — Integration bus v1 (Redis Streams)

### Added
- **`artifacts/integration-bus/docker-compose.yml`**: standalone Redis 7 Alpine Compose project.
  Joins `openclaw_default` network; persistent `integration-bus-redis-data` volume.
  Deploy at `/opt/integration-bus/` on server.
- **Integration bus streams** (naming convention):
  - `ingest:jobs:{source}` — batch job triggers (telegram, email, …)
  - `ingest:events:{source}` — real-time item events (signals, private groups — v2)
  - `ingest:rag:queue` — LightRAG indexer queue (v2)
  - `dlq:failed` — dead letter queue for all sources

### Changed
- **`cron_bridge.py`** refactored to async-first bridge:
  - `POST /trigger` now enqueues to `ingest:jobs:telegram` via Redis XADD and returns HTTP 202
    immediately (previously blocked synchronously for up to 90 min).
  - Redis consumer loop runs as a background thread in the same container; reads from
    `ingest:jobs:telegram` consumer group `digest-workers`, calls `digest_worker.py --now`,
    writes status to `cron-bridge-status.json` (unchanged), pushes failures to `dlq:failed`.
  - Removed `fcntl` file lock (consumer group handles sequential processing).
  - Added graceful Redis reconnect with exponential backoff.
- **`requirements.txt`**: added `redis>=5.0.0`.
- **`docker-compose.yml`** (telethon-digest): added `REDIS_URL` env to `cron-bridge` service.

### Docs
- `docs/13-ai-assistant-architecture.md`: updated Telegram Digest architecture diagram to show
  async bus; replaced backlog section with implemented status + v2 backlog.
- `docs/03-operations.md`: added Integration Bus operations section (deploy, ping, stream
  inspection, DLQ, manual enqueue, trim commands).

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
