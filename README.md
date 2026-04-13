# clawden-ai

> Personal AI assistant infrastructure — OpenClaw + OmniRoute + LightRAG + Telegram, running 24/7 on a private Hetzner server.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![OpenClaw](https://img.shields.io/badge/runtime-OpenClaw-black)](https://github.com/coollabsio/openclaw)
[![Telegram Bot](https://img.shields.io/badge/interface-Telegram-2CA5E0)](https://telegram.org)
[![LightRAG](https://img.shields.io/badge/memory-LightRAG-6B46C1)](https://github.com/HKUDS/LightRAG)
[![OmniRoute](https://img.shields.io/badge/routing-OmniRoute-orange)](https://github.com/diegosouzapw/OmniRoute)

**Бенька.** Always on. Knows your context. Routes every request to the right model.

Incoming signals from any source — Telegram channels, email, feeds — go through a lightweight
async integration bus (Redis Streams) before reaching the digest and memory pipelines.

This repository is the **ops & config package** — deployment runbooks, workspace templates, redacted config artifacts, and infrastructure scripts. Not the OpenClaw source tree.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Model Routing](#model-routing)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Memory System](#memory-system)
- [Repository Structure](#repository-structure)
- [Integration Bus & Planned Ingestion Sources](#integration-bus--planned-ingestion-sources)
- [Getting Started](#getting-started)
- [Quick Operations](#quick-operations)
- [Security](#security)
- [Docs Reading Order](#docs-reading-order)
- [License](#license)

---

## How It Works

Messages arrive via Telegram → routed through OpenClaw gateway → Бенька picks the right AI model for the task → responds with full tool access. Long-term context lives in a three-layer memory system backed by a LightRAG knowledge graph.

Three standalone bridge containers hang off the same OpenClaw runtime. `telethon-digest-cron-bridge`
handles Telegram channel digests, `agentmail-email-bridge` handles personal inbox polling and
scheduled email recaps, and `signals-bridge` handles low-latency trading-style signals from
allowlisted email / Telegram sources. All three enqueue work through Redis Streams, but only the
LLM enrichment steps run through shared model infrastructure: source reads stay inside their
dedicated Python bridges.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Hetzner CX23 (3 vCPU / 4GB RAM, Ubuntu 24.04)                         │
│                                                                         │
│  ┌──────────────────────────────────────────────┐                      │
│  │  Caddy (reverse proxy)                       │ ← 443 / 80           │
│  │  TLS termination + mTLS client cert auth     │                      │
│  └──────────────────┬───────────────────────────┘                      │
│                     │ 127.0.0.1:18789                                  │
│  ┌──────────────────▼───────────────────────────┐                      │
│  │  openclaw-gateway  (Docker)                  │                      │
│  │  image: openclaw-with-iproute2:20260412-slim-2026.4.11 │           │
│  │                                              │──→ OpenAI gpt-5.4    │
│  │  baked in:  iproute2                         │    (primary, OAuth)  │
│  │  note:      voice transcription disabled     │                      │
│  │  volume:    /opt/openclaw/config/  → state   │                      │
│  │             /opt/openclaw/workspace/ → bot   │──→ omniroute:20129   │
│  │             /opt/obsidian-vault/ → vault     │    (smart/med/light) │
│  │                                              │                      │
│  │  tools:  shell · fs · web · browser          │                      │
│  │          subagents · sessions · cron         │                      │
│  └──────────────────┬───────────────────────────┘                      │
│                     │ Docker network (openclaw_default)                │
│  ┌──────────────────▼──────────────────────────────────────────────┐  │
│  │  OmniRoute  (Docker)   127.0.0.1:20128 (dashboard, SSH tunnel)  │  │
│  │                        127.0.0.1:20129 (OpenAI-compatible API)  │  │
│  │                                                                  │  │
│  │  smart  → Kiro/Claude Sonnet → OpenRouter/Claude 3.5 → OR/Kimi  │  │
│  │  medium → Kiro/Claude Haiku  → Gemini Flash → OpenRouter/Qwen3  │  │
│  │  light  → Gemini Flash → OpenRouter/Qwen3-8B → Kiro/Haiku       │  │
│  └──────────────────┬───────────────────────────────────────────────┘  │
│                     │                                                   │
│  ┌──────────────────▼───────────────────────────┐                      │
│  │  LightRAG  (Docker)        127.0.0.1:8020    │                      │
│  │  image: ghcr.io/hkuds/lightrag:latest        │                      │
│  │                                              │                      │
│  │  LLM:       Gemini 2.5 Flash Lite            │                      │
│  │  Embedding: gemini-embedding-001 (dim=3072)  │                      │
│  │  Storage:   NetworkX · NanoVectorDB · JsonKV │                      │
│  │                                              │                      │
│  │  inputs (read-only):                         │                      │
│  │    workspace/  ←  /opt/openclaw/workspace    │                      │
│  │    obsidian/   ←  /opt/obsidian-vault        │                      │
│  └──────────────────────────────────────────────┘                      │
│                                                                         │
│  ┌──────────────────────────────────────────────┐                      │
│  │  integration-bus-redis  (Docker)            │                      │
│  │  /opt/integration-bus                       │                      │
│  │                                              │                      │
│  │  Redis 7 Streams — async ingestion bus       │                      │
│  │  streams: ingest:jobs:*, ingest:events:*    │                      │
│  │           ingest:rag:queue, dlq:failed       │                      │
│  └──────────────────┬───────────────────────────┘                      │
│                     │                                                   │
│  ┌──────────────────▼───────────────────────────┐                      │
│  │  telethon-digest-cron-bridge  (Docker)      │                      │
│  │  /opt/telethon-digest                       │                      │
│  │                                              │                      │
│  │  HTTP /trigger → XADD stream → HTTP 202     │                      │
│  │  Consumer loop → digest_worker.py --now     │                      │
│  │  Telethon MTProto → OmniRoute medium →      │                      │
│  │  Bot API topic post + Obsidian + LightRAG   │                      │
│  │  schedule: 08/11/14/17/21 Europe/Moscow     │                      │
│  └──────────────────────────────────────────────┘                      │
│                                                                         │
│  ┌──────────────────────────────────────────────┐                      │
│  │  agentmail-email-bridge  (Docker)           │                      │
│  │  /opt/agentmail-email                       │                      │
│  │                                              │                      │
│  │  HTTP /trigger → XADD stream → HTTP 202     │                      │
│  │  Consumer loop → AgentMail HTTP API         │                      │
│  │  → thread snapshots → shared OpenClaw LLM   │                      │
│  │  Internal scheduler every 5m                │                      │
│  │  Digests: 08/13/16/20 Europe/Moscow         │                      │
│  │  Output: Telegram topic + Redis events      │                      │
│  └──────────────────────────────────────────────┘                      │
│                                                                         │
│  ┌──────────────────────────────────────────────┐                      │
│  │  signals-bridge  (Docker)                   │                      │
│  │  /opt/signals-bridge                        │                      │
│  │                                              │                      │
│  │  Internal scheduler every 5m                │                      │
│  │  → XADD ingest:jobs:signals                 │                      │
│  │  Consumer loop → AgentMail + Telethon       │                      │
│  │  deterministic prefilter → OmniRoute light  │                      │
│  │  (cheap/free-tier only) → signals topic     │                      │
│  │  Output: Telegram topic + Redis events      │                      │
│  └──────────────────────────────────────────────┘                      │
│                                                                         │
│  /opt/obsidian-vault/   ← Syncthing bidirectional sync with Mac        │
└─────────────────────────────────────────────────────────────────────────┘
        │              │ (primary)         │ (routing)         │
        ▼              ▼                   ▼                   ▼
 Telegram Bot    OpenAI gpt-5.4      Kiro (Claude)     Google Gemini
 (inbound)       via OAuth/Plus      AWS Builder ID    (embeddings +
                 (best quality)      free unlimited     light LLM)
                                         +
                                    OpenRouter hub
                                    (Claude/Kimi/Qwen)
```

---

## Model Routing

Not every task needs the most powerful (and expensive) model. OmniRoute acts as a smart dispatcher — Бенька decides which tier to use based on task complexity, and OmniRoute handles the actual provider selection with automatic fallback.

### Why three tiers?

| Tier | For | Example |
|------|-----|---------|
| **smart** | Complex code, architecture decisions, multi-step reasoning, long context (>8K tokens) | "Review this 200-line module and redesign the auth flow" |
| **medium** | Normal conversation, Q&A, summarization, translation | "What's the deadline for the roadmap item?" |
| **light** | Background helper tasks — classification, tagging, formatting | Note tagging, format checking |

### How Бенька decides

Simple rule chain, top-to-bottom:

1. Task involves code that needs to be generated or reviewed → **smart**
2. Request context exceeds 8K tokens → **smart**
3. Needs architectural trade-off analysis → **smart**
4. Normal chat, Q&A, summary → **medium**
5. Classification, data extraction, formatting → **light**
6. Any delegated LightRAG helper task → **light**; LightRAG's own extraction LLM is direct Gemini

### Provider chains (priority order within each tier)

OmniRoute tries providers in order. If one is unavailable or rate-limited, it automatically moves to the next.

```
smart:  Kiro / Claude Sonnet 4.5
         → OpenRouter / Claude 3.5 Sonnet
         → OpenRouter / Kimi K2

medium: Kiro / Claude 3.5 Haiku
         → Gemini 2.0 Flash
         → OpenRouter / Qwen3-30B

light:  Gemini 2.0 Flash
         → OpenRouter / Qwen3-8B
         → Kiro / Claude 3.5 Haiku
```

### Where does OpenAI gpt-5.4 fit?

OpenAI gpt-5.4 is Denis's **primary model** in OpenClaw — it handles the main conversation via an existing Plus subscription (OAuth, not API key). It doesn't go through OmniRoute because the Plus subscription is OAuth-only and can't be routed via a proxy. OmniRoute covers delegated subtasks and alternative provider fallbacks; LightRAG extraction uses direct Gemini for stability.

### Providers

| Provider | Auth | Models available | Cost |
|----------|------|-----------------|------|
| **Kiro** | AWS Builder ID OAuth | Claude Sonnet 3.7, Claude Haiku | Free, unlimited |
| **OpenRouter** | API key | Claude 3.5, Kimi K2, Qwen3 family | Pay-per-token hub; free models available |
| **Gemini** | API key | gemini-2.5-flash-lite, gemini-embedding-001 | Free tier |
| **OpenAI** | Plus OAuth (via OpenClaw) | gpt-5.4 | Existing Plus subscription |

---

## Features

- **Telegram interface** — DM (allowlist) + supergroup (mention-free in designated chat)
- **Telegram channel digest** — Telethon reads 150–200 subscribed channels and posts scheduled summaries to the `telegram-digest` topic; 5× daily
- **Interest-aware `Пульс дня`** — pulse ranking mixes repeated-signal strength, Denis-fit buckets, novelty, and diversity; bucket profile learns from recent posts and is reusable for future email recaps
- **AgentMail inbox feed** — Python-first AgentMail adapter uses an internal 5-minute scheduler for state/labeling only, applies a deterministic prefilter before LLM poll analysis, and publishes scheduled recaps to `inbox-email` with exact message counts, senders, subjects, and short summaries; Telegram no longer receives 5-minute poll mini-batches
- **Work email feed** — separate `work-email` runtime is now live on the same shared bridge codebase with its own Redis streams, labels, status key, topic `work-email`, internal 5-minute poll scheduler, and weekday-style digest slots `08:30 / 10:00 / 11:30 / 13:00 / 14:30 / 16:00 / 17:30 / 19:00` MSK
- **Signals bridge** — standalone `signals-bridge` polls allowlisted email + Telegram sources every 5 minutes, runs deterministic-first matching, and uses only cheap `OmniRoute light` enrichment with local fallback before posting to `signals`; Telegram batches include source links and posts render the source text excerpt when available
- **Async integration bus** — Redis Streams decouples ingestion from delivery; cron triggers return 202 immediately, pipeline runs asynchronously; extensible to email, signals, RAG
- **Voice messages** — transcription is intentionally disabled on this VPS for now; may return later via a lighter CPU path or external API
- **Smart model routing** — OmniRoute dispatches tasks to the right AI tier (smart/medium/light) with automatic provider fallback
- **Three-layer memory** — live workspace → raw decision log → LightRAG knowledge graph
- **Obsidian vault sync** — bidirectional Syncthing between Mac (iCloud) and server, changes propagate in seconds
- **Full tool access** — shell exec, filesystem, web search, browser, subagents, cron
- **Persistent sessions** — per-channel-peer session scope, resumes context across restarts
- **Knowledge graph queries** — hybrid vector + graph retrieval via LightRAG

---

## Telegram Surfaces

This is the fastest way to understand how the Telegram side of the system works.

```mermaid
flowchart TD
    Denis[Denis]
    DM[DM: Benka_Clawbot_base]
    SG[Private forum supergroup]

    Denis --> DM
    Denis --> SG

    OC[OpenClaw main conversation]
    TD[telethon-digest]
    AE[agentmail-email-bridge]
    AWE[agentmail-work-email-bridge]
    SB[signals-bridge]

    OC --> Inbox[inbox]
    OC --> Approvals[approvals]
    OC --> Tasks[tasks]
    OC --> System[system]
    OC --> RagLog[rag-log]

    TD --> TelegramDigest[telegram-digest]
    AE --> InboxEmail[inbox-email]
    AWE --> WorkEmail[work-email]
    SB --> Signals[signals]

    Inbox --> SG
    Approvals --> SG
    Tasks --> SG
    System --> SG
    RagLog --> SG
    TelegramDigest --> SG
    InboxEmail --> SG
    WorkEmail --> SG
    Signals --> SG
```

### What Each Surface Is For

| Surface | Why it exists | What the bot posts there | What it does not post |
|---|---|---|---|
| `Benka_Clawbot_base` (DM) | Most direct owner control channel | conversation, ad hoc requests, approvals when convenient | bulk digests by default |
| `inbox` | General ops intake | short operational dialogue, commands, coordination | scheduled feed noise |
| `approvals` | Human confirmation lane | explicit approval requests for sensitive actions | regular digests |
| `tasks` | Execution tracking | progress updates, task lifecycle, completion notes | inbox/news digests |
| `system` | Runtime visibility | deploy notes, health status, incident breadcrumbs | personal/work content |
| `rag-log` | Memory/RAG observability | ingestion decisions, indexing notes, failures | raw secrets or full private content |
| `inbox-email` | Personal email recap surface | scheduled personal email digests from `agentmail-email-bridge` | raw full emails, 5-minute poll chatter |
| `work-email` | Work email recap surface | scheduled work-email digests from `agentmail-work-email-bridge` | raw full emails, personal mailbox content |
| `telegram-digest` | Curated channel reading surface | scheduled Telegram channel digests from `telethon-digest` | raw channel firehose |
| `signals` | Time-sensitive alert surface | compact actionable alerts from `signals-bridge` | broad recap dumps |

### How It Works

| Pipeline | Input | Output topic | Cadence | Main job |
|---|---|---|---|---|
| `telethon-digest` | 150–200 Telegram channels | `telegram-digest` | `08:00 / 11:00 / 14:00 / 17:00 / 21:00` MSK | editorial digest |
| `agentmail-email-bridge` | personal AgentMail inbox | `inbox-email` | internal poll every 5m, Telegram digests at `08:00 / 13:00 / 16:00 / 20:00` | personal inbox recap |
| `agentmail-work-email-bridge` | work AgentMail inbox | `work-email` | internal poll every 5m, Telegram digests at `08:30 / 10:00 / 11:30 / 13:00 / 14:30 / 16:00 / 17:30 / 19:00` | work inbox recap |
| `signals-bridge` | allowlisted email + Telegram sources | `signals` | internal poll every 5m | urgent / actionable signal routing |
| `OpenClaw main` | Denis messages + ops context | `inbox`, `approvals`, `tasks`, `system`, `rag-log` | on demand | control plane and assistant interaction |

The detailed policy version lives in [docs/12-telegram-channel-architecture.md](docs/12-telegram-channel-architecture.md).

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Agent runtime | [OpenClaw](https://github.com/coollabsio/openclaw) (Docker) |
| Primary LLM | OpenAI gpt-5.4 via openai-codex OAuth (Plus subscription) |
| Model routing | [OmniRoute](https://github.com/diegosouzapw/OmniRoute) — smart/medium/light tiers, 3 provider chains |
| Routing providers | Kiro (Claude, AWS Builder ID) · OpenRouter hub · Gemini |
| Knowledge graph | [LightRAG](https://github.com/HKUDS/LightRAG) + Gemini embeddings |
| **Integration bus** | **Redis 7 Streams** — async ingestion, consumer groups, DLQ |
| Digest reader | Telethon MTProto — 150–200 Telegram channels, 5× daily |
| Email ingest | AgentMail HTTP API in standalone Python bridge + OpenClaw JSON-only summarization — separate personal + work runtimes with internal 5-min poll schedulers and scheduled Telegram digests |
| Signals ingest | Standalone Python bridge — 5-min internal scheduler, deterministic filters first, then OmniRoute `light` only |
| Voice transcription | Not enabled in the current image; may return later via a lighter CPU stack or external API |
| Interface | Telegram Bot API + Telethon MTProto + AgentMail HTTP inbox reader |
| Reverse proxy | Caddy 2 (mTLS client cert auth) |
| Notes sync | Obsidian ↔ [Syncthing](https://syncthing.net) (bidirectional) |
| Host | Hetzner CX23, Ubuntu 24.04 |

---

## Memory System

Long-term memory is file-first. Markdown remains readable and editable by humans; LightRAG is the
retrieval/index layer built from those files.

Three trust layers — never conflate them:

```
LIVE    — docker ps / curl / logs        highest trust, current state only
RAW     — workspace/raw/YYYY-MM-DD-*.md  verbatim decisions, redacted before commit
DERIVED — MEMORY.md, daily notes         quick recall, not canonical
```

### What Gets Stored

| Layer | Examples | How it enters memory |
|-------|----------|----------------------|
| Workspace context | `MEMORY.md`, `USER.md`, `AGENTS.md`, `TOOLS.md` | edited locally or by the bot, deployed to `/opt/openclaw/workspace` |
| Daily memory | `workspace/memory/YYYY-MM-DD.md` | bot session logs and compact decisions |
| Raw decision records | `workspace/raw/YYYY-MM-DD-topic.md` | explicit decisions, root causes, rejected options, redacted before git |
| Obsidian notes | reading notes, project wiki, personal knowledge | Syncthing syncs Mac Obsidian vault to `/opt/obsidian-vault` |

### How LightRAG Fits

LightRAG indexes workspace markdown and the Obsidian vault every 30 minutes via
`/opt/lightrag/scripts/lightrag-ingest.sh`. The script uploads markdown file-by-file, retries
failed/pending documents, and LightRAG turns the content into chunks, vectors, entities, and graph
relationships.

OpenClaw uses LightRAG from inside Docker at:

```text
http://lightrag:9621/query
```

The server host uses:

```text
http://127.0.0.1:8020/query
```

Бенька asks LightRAG when the question is about historical context, decisions, notes, books,
projects, or "what do we know about X?" The response includes a synthesized answer plus file
references. For important decisions, the bot should inspect the referenced source file before
answering confidently.

LightRAG is not the source of truth for live infrastructure. Questions like "is this running now?"
still require direct checks with Docker, curl, config reads, or logs.

**Boot sequence** (5–8 KB total context):
1. `MEMORY.md` + `USER.md` — long-term curated facts (gitignored, populated locally)
2. `memory/INDEX.md` — locate today + yesterday notes
3. Today's daily note (if exists)
4. LightRAG health check (non-blocking)

LightRAG replaces scanning archives — one `POST /query` returns relevant chunks instead of loading megabytes of history.

See [`docs/10-memory-architecture.md`](docs/10-memory-architecture.md) for full details.

---

## Repository Structure

```
.
├── artifacts/openclaw/
│   ├── openclaw.json               config template (all secrets as <placeholders>)
│   ├── telegram-surfaces.redacted.json  Telegram topology and memory/RAG policy draft
│   ├── caddy.redacted.Caddyfile    reverse proxy config template
│   ├── docker-compose.redacted.yml compose template
│   ├── env.redacted.example        env vars template
│   └── auth-profile.redacted.json  OAuth profile template
├── artifacts/omniroute/
│   ├── docker-compose.override.yml compose override template (adds OmniRoute service)
│   └── omniroute.env.example       env template with secret generation instructions
├── artifacts/integration-bus/
│   └── docker-compose.yml          Redis 7 Streams compose (deploy at /opt/integration-bus/)
├── artifacts/agentmail-email/
│   ├── docker-compose.yml          standalone inbox-email compose template
│   ├── Dockerfile                  lightweight Python service image
│   ├── cron_bridge.py              HTTP bridge + Redis consumer for poll/digest jobs
│   ├── agentmail_api.py            direct AgentMail HTTP client (messages / threads / labels)
│   ├── *.py                        Agent runner, prompts, event store, poster, models
│   ├── config.example.json         redacted inbox config template
│   ├── sync-openclaw-cron-jobs.sh  server-side OpenClaw Cron Jobs sync helper
│   └── email.env.example           redacted runtime env template
├── artifacts/telethon-digest/
│   ├── docker-compose.yml          standalone digest compose template
│   ├── Dockerfile                  Python service image
│   ├── cron_bridge.py              HTTP bridge + Redis consumer loop (async, v2)
│   ├── *.py                        Telethon reader, scorer, summarizer, poster
│   ├── config.example.json         redacted folder config template
│   ├── sync-openclaw-cron-jobs.sh  server-side OpenClaw Cron Jobs sync helper
│   └── telethon.env.example        redacted runtime env template
├── artifacts/signals-bridge/
│   ├── docker-compose.yml          standalone signals compose template
│   ├── Dockerfile                  Python service image
│   ├── cron_bridge.py              internal scheduler + Redis consumer + HTTP trigger
│   ├── *.py                        AgentMail/Telethon adapters, matcher, enrichment, poster
│   ├── config.example.json         generic source config template with external `rule_files`
│   ├── rules/                      public generic rule examples only
│   ├── signals.env.example         redacted runtime env template
│   └── tests/                      focused unit tests for matching / dedup / config validation
├── skills/
│   ├── README.md                   project-owned Codex skills catalog + install notes
│   └── openclaw-cron-maintenance/
│       └── SKILL.md                runbook skill for OpenClaw cron-store maintenance
├── docs/
│   ├── 01-server-state.md          current server snapshot (services, ports, images)
│   ├── 02-openclaw-installation.md deployment decisions and auth setup
│   ├── 03-operations.md            SSH commands, full ops runbook
│   ├── 06-command-log.md           full command history with decision context
│   ├── 07-architecture-and-security.md  security model (mTLS, UFW, exec policy)
│   ├── 08-git-and-redaction-policy.md   git safety rules, secret handling
│   ├── 09-workspace-setup.md       bot personalisation guide
│   ├── 10-memory-architecture.md   three-layer memory system design
│   ├── 11-lightrag-setup.md        LightRAG deployment and ingestion guide
│   ├── 12-telegram-channel-architecture.md  Telegram topology, permissions, RAG gates
│   ├── 13-ai-assistant-architecture.md      model routing and assistant behavior
│   └── 14-codex-skills.md          project-specific Codex skill catalog
├── scripts/
│   ├── deploy-workspace.sh         rsync workspace/ to server
│   ├── deploy-agentmail-email.sh   deploy inbox-email bridge + keep central OpenClaw clean
│   ├── deploy-agentmail-work-email.sh  deploy work-email bridge with isolated streams + schedule
│   ├── deploy-signals-bridge.sh    deploy low-cost signals bridge with internal 5-min scheduler
│   ├── deploy-telethon-digest.sh   deploy Telegram digest bridge
│   ├── setup-lightrag.sh           provision LightRAG on server
│   ├── sync-obsidian.sh            legacy one-way rsync (superseded by Syncthing)
│   ├── create-lightrag-env.sh      generate scripts/lightrag.env from template
│   ├── lightrag.env.template       env template (no secrets)
│   └── com.openclaw.obsidian-sync.plist.template  legacy rsync launchd template (superseded)
├── workspace/                      bot workspace (deployed to server)
│   ├── IDENTITY.md                 bot persona: Бенька
│   ├── AGENTS.md                   session protocol, memory rules, boot sequence
│   ├── BOOT.md                     8-step startup checklist
│   ├── TOOLS.md                    available tools + lightrag_query reference
│   ├── TELEGRAM_POLICY.md          Telegram runtime policy for surfaces and memory gates
│   ├── HEARTBEAT.md                periodic maintenance tasks
│   ├── INDEX.md                    master memory catalog
│   ├── memory/INDEX.md             daily note index (bot-managed)
│   └── raw/.gitkeep                placeholder — raw decision threads (gitignored)
│   # USER.md, MEMORY.md, SOUL.md — gitignored (contain personal data)
├── CHANGELOG.md                    version history (Keep a Changelog format)
├── CLAUDE.md                       Claude Code agent instructions
└── LOCAL_ACCESS.md                 ← gitignored — real credentials here
```

**Gitignored (never committed):** `LOCAL_ACCESS.md`, `secrets/`, `scripts/lightrag.env`, `workspace/USER.md`, `workspace/MEMORY.md`, `workspace/SOUL.md`, `workspace/memory/[0-9]*.md`
Real bridge env files belong under gitignored secret roots such as `secrets/agentmail-email/email.env`, `secrets/agentmail-work-email/email.env`, and `secrets/telethon-digest/telethon.env`.

---

## Integration Bus & Planned Ingestion Sources

The async integration bus (Redis Streams) is the shared backbone for all data ingestion.
Any source that produces content for the assistant goes through the bus — no bespoke sync paths per source.

### How it works

```
[Source trigger]          [Bus]                  [Worker]               [Output]
cron / webhook ──XADD──► Redis Stream ──XREAD──► pipeline worker ──────► Telegram topic
                                                                          Obsidian vault
                                                                          LightRAG graph
```

The trigger returns HTTP 202 immediately. The worker processes asynchronously. If it fails, the job lands in `dlq:failed`.

### Current sources

| Source | Stream | Status |
|--------|--------|--------|
| Telegram channel digest | `ingest:jobs:telegram` | ✅ Live — 150–200 channels, 5× daily |
| AgentMail inbox poll/digest | `ingest:jobs:email`, `ingest:events:email` | ✅ Live — standalone `agentmail-email-bridge` reads AgentMail directly, runs an internal 5-minute poll scheduler with deterministic prefiltering for low-signal windows, and posts only scheduled digests at 08/13/16/20 MSK with exact mailbox counts/senders/subjects; empty scheduled windows still post an explicit recap instead of silently skipping |
| AgentMail work-email poll/digest | `ingest:jobs:email:work`, `ingest:events:email:work` | ✅ Live — standalone `agentmail-work-email-bridge` reuses the same bridge codebase with isolated streams/status/labels, polls `workmail.denny@agentmail.to` internally every 5 minutes, and posts scheduled digests to topic `work-email` at 08:30/10:00/11:30/13:00/14:30/16:00/17:30/19:00 MSK |
| Signals bridge | `ingest:jobs:signals`, `ingest:events:signals` | ✅ Live artifact — standalone `signals-bridge` polls every 5m, loads real rules from local separate files, does deterministic-first matching, and uses only cheap `OmniRoute light` enrichment (or local fallback) before posting to `signals` |
| LightRAG async ingest | `ingest:rag:queue` | ✅ Live — digest notes pushed after each run, RAG consumer uploads immediately |

### Planned sources (v2)

| Source | Stream | Notes |
|--------|--------|-------|
| Signal feeds (real-time) | `ingest:events:telegram` | Future listener for priority channels / private groups beyond the current 5-minute `signals-bridge` polling model |
| Web feeds / webhooks | `ingest:events:web` | RSS, webhooks, site monitoring |

All future producers plug into the same Redis Streams. Workers are independent Python services
consuming from the bus — no shared code with the pipeline they feed.

---

## Getting Started

1. **Read the docs** in order (see [Docs Reading Order](#docs-reading-order))
2. **Copy artifact templates** from `artifacts/openclaw/` — fill in your real values
3. **Create gitignored files** locally:
   - `LOCAL_ACCESS.md` — SSH host, Telegram token, API keys, cert paths
   - `secrets/` — mTLS client certificates
   - `scripts/lightrag.env` — Gemini API key (from `lightrag.env.template`)
   - `workspace/USER.md`, `workspace/MEMORY.md`, `workspace/SOUL.md` — personal bot context
4. **Deploy workspace** to server: `./scripts/deploy-workspace.sh`
   - This updates only `/opt/openclaw/workspace`
   - Standalone bridges use separate deploy scripts and artifact roots under `/opt/`
5. **Deploy bridge artifacts as needed**:
   - `./scripts/deploy-telethon-digest.sh`
   - `./scripts/deploy-agentmail-email.sh`
   - `./scripts/deploy-signals-bridge.sh`
6. **Provision LightRAG** (first time): `./scripts/setup-lightrag.sh`
7. **Set up Obsidian sync**: install Syncthing on Mac (`brew install syncthing && brew services start syncthing`) and follow `docs/03-operations.md` → "Obsidian vault sync — Syncthing setup"

---

## Quick Operations

```bash
export OPENCLAW_HOST="deploy@<server-host>"

# Deploy workspace changes to server
./scripts/deploy-workspace.sh

# Deploy standalone bridge artifacts
./scripts/deploy-telethon-digest.sh
./scripts/deploy-agentmail-email.sh
./scripts/deploy-signals-bridge.sh
```

Notes:

- `deploy-workspace.sh` syncs only `workspace/` markdown files into `/opt/openclaw/workspace`.
- `telethon-digest`, `agentmail-email`, and `signals-bridge` run from their own live roots under `/opt/`.
- On the current server, `/opt/openclaw` should be treated as runtime/config state, not as the source of truth for bridge code.

```bash

# Check all services health
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'curl -sf http://127.0.0.1:18789/healthz'         # OpenClaw
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'curl -sf http://127.0.0.1:8020/health | jq .status'  # LightRAG
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'curl -sf http://127.0.0.1:20128/api/monitoring/health'  # OmniRoute

# OmniRoute dashboard (SSH tunnel → open in browser)
ssh -i ~/.ssh/id_rsa -L 20128:127.0.0.1:20128 "$OPENCLAW_HOST" -N &
# → open http://localhost:20128

# Trigger knowledge graph re-index
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '/opt/lightrag/scripts/lightrag-ingest.sh'

# Check Obsidian vault sync status (Syncthing)
open http://127.0.0.1:8384

# Integration bus — Redis health + stream lengths
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli ping'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:jobs:telegram'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:jobs:signals'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:events:email'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:events:signals'
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN dlq:failed'

# Telethon Digest logs
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/telethon-digest && sudo docker compose logs --tail=100 telethon-digest-cron-bridge'

# OpenClaw Cron Jobs
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'sudo cat /opt/openclaw/config/cron/jobs.json 2>/dev/null || sudo cat /home/deploy/.openclaw/cron/jobs.json'

# Telethon Digest cron bridge health/status
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8091/health && echo && curl -s http://127.0.0.1:8091/status'

# AgentMail inbox-email bridge health/status
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8092/health && echo && curl -s http://127.0.0.1:8092/status'

# AgentMail work-email bridge health/status
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8094/health && echo && curl -s http://127.0.0.1:8094/status'

# Signals bridge health/status
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'curl -s http://127.0.0.1:8093/health && echo && curl -s http://127.0.0.1:8093/status'
```

See [`docs/03-operations.md`](docs/03-operations.md) for the full ops runbook.

---

## Security

- **Reverse proxy**: Caddy with mTLS — client certificate required for all external access
- **LightRAG**: bound to `127.0.0.1:8020` only — not reachable from internet
- **Firewall**: UFW allows only `22/tcp`, `80/tcp`, `443/tcp`
- **Bot tools**: `profile=coding`, `exec=deny/ask-always` — OpenClaw stays focused on orchestration and LLM work; mailbox I/O lives in dedicated bridges
- **No secrets in git**: `LOCAL_ACCESS.md`, `secrets/`, `scripts/lightrag.env` are gitignored; tracked files use `<placeholder>` pattern

See [`docs/07-architecture-and-security.md`](docs/07-architecture-and-security.md) and [`docs/08-git-and-redaction-policy.md`](docs/08-git-and-redaction-policy.md).

---

## Docs Reading Order

1. [`docs/01-server-state.md`](docs/01-server-state.md) — current snapshot: services, ports, images
2. [`docs/07-architecture-and-security.md`](docs/07-architecture-and-security.md) — security model
3. [`docs/02-openclaw-installation.md`](docs/02-openclaw-installation.md) — how it was deployed
4. [`docs/03-operations.md`](docs/03-operations.md) — day-to-day ops commands
5. [`docs/10-memory-architecture.md`](docs/10-memory-architecture.md) — memory system design
6. [`docs/11-lightrag-setup.md`](docs/11-lightrag-setup.md) — LightRAG knowledge graph
7. [`docs/12-telegram-channel-architecture.md`](docs/12-telegram-channel-architecture.md) — Telegram topology and ingestion policy
8. [`docs/13-ai-assistant-architecture.md`](docs/13-ai-assistant-architecture.md) — assistant model routing and behavior
9. [`docs/14-codex-skills.md`](docs/14-codex-skills.md) — project skill catalog for recurring Codex workflows
10. [`docs/08-git-and-redaction-policy.md`](docs/08-git-and-redaction-policy.md) — git safety rules

---

## License

MIT
