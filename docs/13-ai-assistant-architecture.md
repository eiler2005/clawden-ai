# AI Assistant Architecture

This document describes the design principles, model routing, channel interaction model,
and memory strategy for the Бенька / Benka AI assistant running on OpenClaw.

---

## Core Design Principles

### Least privilege by default

The assistant does not accumulate permissions, memory, or access beyond what is
needed for the current task. Each surface has its own mode, and the safest mode
is the default.

### Memory is earned, not automatic

Telegram messages are not memory by default. A message can be answered without being saved.
Saving to long-term memory requires either an explicit user command or a high-importance
signal with sufficient confidence. Family content always requires explicit approval.

### Approval before action

Destructive operations, external sends, deploys, credential changes, purchases, and
high-sensitivity memory writes require user confirmation before proceeding. This rule
applies regardless of channel.

### One response, one surface

The assistant responds where it was invoked. It does not cross-post between surfaces
(e.g., from Family to Ops) unless explicitly asked. Context from one domain does not
leak into another.

### Conservative by default, explicit to expand

If a surface, action, or memory write is ambiguous, the safer interpretation wins.
Expansion of permissions or memory scope requires explicit instruction.

---

## Model Routing Architecture

### Primary flow

```text
User message
  -> OpenClaw gateway
     -> Agent runner
        -> Primary model: openai-codex/gpt-5.4
           on rate_limit / error:
           -> Fallback 1: omniroute/smart
           -> Fallback 2: omniroute/medium
           -> Fallback 3: omniroute/light
```

Fallbacks are configured in `agents.defaults.model.fallbacks` in `openclaw.json`.
This is channel-agnostic — applies to all surfaces (Telegram, web UI, API).

### OmniRoute tiers

OmniRoute runs inside the same Docker Compose stack (`http://omniroute:20129/v1`).
It provides three routing tiers, each with a priority fallback list internally:

| Tier | Primary model | Use case |
|------|--------------|----------|
| `smart` | kiro/claude-sonnet-4.5 | Code generation, architecture review, multi-step reasoning, context >8K tokens |
| `medium` | kiro/claude-haiku-4.5 | Q&A, summarization, translation, standard dialog |
| `light` | gemini/gemini-2.0-flash | Classification, data extraction, formatting, quick lookups |

Each tier has internal fallbacks (e.g., openrouter models) if the primary fails.

### Model selection rules (agent-side)

The agent (running in the primary model context) selects OmniRoute tiers for subtasks:

1. Code >50 lines, architecture review, multi-step reasoning, context >8K → `smart`
2. Standard dialog, Q&A, summarization → `medium`
3. Classification, tagging, data extraction → `light`
4. LightRAG lookups and classification → `light`

The main user response is never proxied through OmniRoute when Codex is available.
OmniRoute is for subtasks and fallback only.

### Response footer

Every response in Telegram ends with a one-line footer:

```
_gpt-5.4 · primary · 8% · standard · memory_
```

Fields (separated by ` · `):

| Field | Values | Meaning |
|-------|--------|---------|
| Model | `gpt-5.4` / `smart` / `medium` / `light` | Which model generated the response |
| Source | `primary` / `fallback` / `delegated` | How the model was selected |
| Context % | `5%` … `95%` | Rough fill of the context window this session |
| Complexity | `complex` / `standard` / `simple` | Task tier that drove model selection |
| `memory` | optional suffix | Memory files were loaded in this session |

Examples:
```
_gpt-5.4 · primary · 8% · standard · memory_
_smart · fallback · 31% · complex_
_medium · fallback · 12% · standard · memory_
_light · delegated · 5% · simple_
```

---

## Telegram Interaction Model

### Surface hierarchy

| Surface | Mode | Proactivity | Memory writes |
|---------|------|-------------|---------------|
| DM (`Benka_Clawbot_base`) | Control | Medium | Decisions/facts on explicit command |
| Ops supergroup (`Benka_Clawbot_SuperGroup`) | Ops hub | Medium | OPLOG only |
| Work Email (topic) | Digest | Low | Summaries only, no raw email bodies |
| Telegram Digest (topic) | Digest | Low | Digest summaries only |
| Signals (topic) | Alert | High, narrow | Compact alert record |
| Family (separate group) | Family | Low, mention-only | Never without explicit approval |
| Knowledge (private channel) | Knowledge | Low | CURATED, Obsidian/RAG eligible |
| Ideas (capture group) | Idea capture | Low | RAW queue, not auto-promoted |
| Sandbox / Lab | Testing | Free | Never production memory |

### Trigger rules

- All groups require `@mention` or direct reply by default.
- The ops supergroup hub is the only surface where mention-free operation is allowed
  (configured per topic ID, not by name).
- DMs from non-allowlisted users are rejected before the agent runs.

### What the bot reads vs. what it acts on

The bot does **not** read the full message stream by default in any group.
In the ops supergroup, it reads only what is directed at it (mention/reply)
unless a specific topic workflow explicitly enables whole-stream reading for a
bounded task (e.g., a timed digest window).

---

## Memory Architecture

### Memory classes

| Class | What | Sources | Retention | RAG | Obsidian |
|-------|------|---------|-----------|-----|---------|
| `LIVE` | Current conversation, temp task state | Any | Session only | No | No |
| `OPLOG` | Task status, approval outcomes | Ops topics, tools | 14–30 days | No | No |
| `RAW` | Redacted decisions, `#canon` threads, candidate ideas | DM explicit, ops decisions, Ideas | 30–90 days | Only redacted decisions | No |
| `DERIVED` | Summaries, digests, extracted tasks | Work Email, Digest, Signals | 30–180 days | Selective | Optional |
| `CURATED` | Structured durable knowledge | Knowledge channel, reviewed Ideas | Durable | Yes | Yes |
| `LONG_TERM` | Stable user facts, preferences | DM explicit, Knowledge explicit | Durable until revoked | Yes | Optional |

### Strict rules

- Telegram messages → `LIVE` by default. Not persisted unless promoted.
- Work email full bodies → never indexed. Compact summaries only.
- Family content → `LIVE` only. Long-term requires explicit approval.
- Credentials, tokens, keys → never stored in memory, RAG, or Obsidian.
- Sandbox → excluded from all production memory paths.

### Session startup

1. Load `MEMORY.md` (~2KB, always).
2. Load `memory/INDEX.md` → find today's and yesterday's daily files.
3. Load today's daily file (if exists and topic is relevant).
4. Load yesterday's daily file (only if today has <3 entries).
5. Check LightRAG health: `GET http://lightrag:9621/health` (non-blocking).
6. Note unresolved items from previous sessions.
7. Confirm readiness briefly — no verbose preamble.

Cold-start limit: ~5–8KB context. Do not load `raw/` at startup.

---

## LightRAG Integration

### What goes in

Only structured, curated content:

- Obsidian vault markdown (synced from Mac via Syncthing)
- Promoted Ideas with full structure
- `CURATED` knowledge items with required fields
- Redacted root-cause / `#canon` decision records

### What does NOT go in

- Raw Telegram chat
- Full email bodies
- Operational logs
- Credentials or sensitive data
- Sandbox content

### Query

```
POST http://lightrag:9621/query
{"query": "...", "mode": "hybrid"}
```

Results are `DERIVED`-level — not authoritative for current system state.
Use live checks (`docker ps`, `curl`) for current state, not LightRAG.

### URL note

Use DNS alias `lightrag` (not container name `lightrag-lightrag-1`):

```
http://lightrag:9621/health   ✓
http://lightrag-lightrag-1:9621/health   ✗  (blocked by SSRF policy)
```

---

## Approval Gates

These actions always require explicit user confirmation, regardless of surface:

- Destructive operations (delete, drop, rm, wipe)
- External sends (email replies, Telegram posts to external chats)
- Deploys, restarts, config changes
- Purchases or irreversible commitments
- Credential or token changes
- High-sensitivity memory writes (sensitivity ≥ 0.70)
- Any family long-term memory
- Cross-domain content movement (work ↔ family ↔ personal)

Scheduled digests and summaries within Telegram do not require approval
if they only summarize and publish within the configured topic.

---

## Anti-Patterns to Avoid

- Treating Telegram as a memory stream (it is a communication channel).
- Posting full email bodies into Telegram topics or memory.
- Mixing family, work, and ops contexts in one surface.
- Using LightRAG as a source of truth for current system state.
- Making the bot full admin in groups.
- Storing secrets, logs, or raw code dumps in Obsidian or RAG.
- Writing memory from Sandbox / Lab.
- Calling `smart` for trivial classification tasks.
- Proxying the main user response through OmniRoute when Codex is available.

---

## Telegram Channel Digest

### Overview

A scheduled service reads 150–200 Telegram channels Denis subscribes to,
scores posts by folder priority and pinned-dialog status, summarizes via
OmniRoute `medium`, and posts a compact digest to the `telegram-digest`
topic in `Benka_Clawbot_SuperGroup` — 6× daily (08:00, 09:00, 12:00, 15:00, 19:00, 21:00 МСК).

### Architecture

```
OpenClaw Cron Jobs (08:00/09:00/12:00/15:00/19:00/21:00 МСК)
  └── isolated OpenClaw agent run
        └── HTTP POST /trigger → telethon-digest-cron-bridge
              └── XADD ingest:jobs:telegram → HTTP 202 (immediate)

                        ↓ async (Redis Streams)

              telethon-digest-cron-bridge (consumer loop, same container)
                    └── python digest_worker.py --now
                          └── telethon-digest container context (Python, async)
              ├── reader.py       — Telethon MTProto, batched reads (10/batch), FloodWait-safe
              ├── scorer.py       — Pass 1: folder_priority × pin_boost; top-30 → LLM
              ├── link_builder.py — t.me deep links per post
              ├── summarizer.py   — OmniRoute medium, structured digest prompts
              └── poster.py       — Bot API → telegram-digest topic, split at 4000 chars
```

**Integration bus** (`integration-bus-redis`, Redis 7 Alpine):

```
                            REDIS STREAMS (integration-bus-redis)
                       ┌──────────────────────────────────────────────┐
 [Producers]           │                                              │  [Workers]
                       │  ingest:jobs:telegram ───────────────────────┼──► cron-bridge consumer loop
 cron /trigger ────────┤    {run_id, digest_type, config_ref}        │    → digest_worker.py --now
                       │                                              │
                       │  ingest:jobs:email ──────────────────────────┼──► email-worker (future)
 email-trigger ────────┤                                              │
                       │  ingest:events:telegram ─────────────────────┼──► telethon-event-listener (future)
 Telethon listener ────┤    (individual messages, real-time)         │    → enrich → classify → alert/rag
                       │                                              │
                       │  ingest:rag:queue ───────────────────────────┼──► lightrag-indexer (future)
                       │                                              │
                       │  dlq:failed ─────────────────────────────────┼──► monitoring / retry
                       └──────────────────────────────────────────────┘
```

Stream naming:
- `ingest:jobs:{source}` — batch job triggers (telegram, email)
- `ingest:events:{source}` — real-time item events (signals, private groups)
- `ingest:rag:queue` — items queued for LightRAG indexing
- `dlq:failed` — dead letter queue (all sources)

Container `telethon-digest-cron-bridge` shares the `openclaw_default` network and
has direct access to `http://omniroute:20129/v1` and `http://integration-bus-redis:6379`.

The scheduler of record is the OpenClaw Gateway itself. The six digest jobs
are stored in the gateway cron store and show up in Control → Cron Jobs:

- `Telethon Digest · 08:00 Morning brief`
- `Telethon Digest · 09:00 Regular digest`
- `Telethon Digest · 12:00 Regular digest`
- `Telethon Digest · 15:00 Regular digest`
- `Telethon Digest · 19:00 Regular digest`
- `Telethon Digest · 21:00 Evening editorial`

### Rate limit handling

- Channels read in batches of 10 with 1.5 s pause between batches.
- Telethon auto-retries on `FloodWaitError` internally.
- Full read of 200 channels: ~30–60 s (well within the longest regular interval).

### Integration bus status

**Implemented (v1):** Redis Streams async ingestion bus is live.

- `cron_bridge.py` enqueues jobs to `ingest:jobs:telegram` and returns HTTP 202 immediately.
- Consumer loop runs as a background thread in the same container; calls `digest_worker.py --now`.
- Failed pipelines are written to `dlq:failed` stream.
- `integration-bus-redis` (Redis 7 Alpine) runs as a standalone Docker Compose project at
  `/opt/integration-bus/`, joined to `openclaw_default` network.

**Known failure mode (poster.py):** `poster.py` hides the entire `Пульс дня` block when
`document.themes` is empty, but `summarizer.py` can legitimately sanitize all candidate
themes down to `[]`. That case should be treated as a content-quality fallback, not a reason
to hide the section.

**Backlog (v2):**

- `ingest:events:telegram` — real-time Telethon listener for private groups and signal channels
- `ingest:jobs:email` — Work Email digest producer
- `ingest:rag:queue` — LightRAG indexer worker consuming enriched items
- Per-item pipeline: individual posts as events (vs. current whole-digest-as-job)
- Monitoring/metrics for Redis streams (XLEN, DLQ alerts)

### Scoring

```
score = folder_priority × (pin_boost if pinned else 1)
```

Posts below `min_score` (default: 2) are dropped.
Top 30 by score → LLM. Rest discarded.

### Memory / state

- `state.json` (Docker volume `telethon-state`): per-channel `last_seen_msg_id` watermarks.
- `last_run` timestamp drives the read window for the next cycle.
- Session file (Docker volume `telethon-sessions`): Telethon user session.
- Read scope is application-enforced: `read_only=true`, explicit folder/channel allowlists,
  and `read_broadcast_channels_only=true` by default. Telegram user sessions do not provide
  server-side API scopes, so the service fails closed if the allowlist selects no channels.

### Setup steps (one-time)

Current status: completed and running on the server through OpenClaw Cron Jobs.

```bash
# 0. Work from the standalone project directory
cd /opt/telethon-digest
# 1. Fill in /opt/telethon-digest/telethon.env
#    Local gitignored source: secrets/telethon-digest/telethon.env
# 2. Authorize session
docker compose run --rm telethon-digest python auth.py
# 3. Sync folder/channel list from Telegram
docker compose run --rm telethon-digest python sync_channels.py
# 4. Manual smoke test
docker compose run --rm telethon-digest python digest_worker.py --now
# 5. Sync OpenClaw Cron Jobs
/opt/telethon-digest/sync-openclaw-cron-jobs.sh
```

### Digest format (Telegram HTML)

```html
📊 <b>Дайджест</b> | 08:00–12:00 (143 каналов, 12 постов)

📁 <b>VIP</b>
• <b>КаналA</b>: Краткое резюме события. (<a href="https://t.me/...">→</a>)
• <b>КаналB</b> 📌: Закреплено — ключевая новость.

📁 <b>Finance</b>
• <b>КаналC</b>: ...

<i>medium · delegated · 5% · simple</i>
```
