# clawden-ai

> Personal AI assistant infrastructure — OpenClaw + LightRAG + Telegram, running 24/7 on a private Hetzner server.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![OpenClaw](https://img.shields.io/badge/runtime-OpenClaw-black)](https://github.com/coollabsio/openclaw)
[![Telegram Bot](https://img.shields.io/badge/interface-Telegram-2CA5E0)](https://telegram.org)
[![LightRAG](https://img.shields.io/badge/memory-LightRAG-6B46C1)](https://github.com/HKUDS/LightRAG)

**Бенька.** Always on. Knows your context.

This repository is the **ops & config package** — deployment runbooks, workspace templates, redacted config artifacts, and infrastructure scripts. Not the OpenClaw source tree.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Memory System](#memory-system)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
- [Quick Operations](#quick-operations)
- [Security](#security)
- [Docs Reading Order](#docs-reading-order)
- [License](#license)

---

## How It Works

Messages arrive via Telegram → routed through OpenClaw gateway → agent responds with full tool access. Long-term context lives in a three-layer memory system backed by a LightRAG knowledge graph.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Hetzner CX23 (3 vCPU / 4GB RAM, Ubuntu 24.04)                     │
│                                                                     │
│  ┌──────────────────────────────────────────────┐                  │
│  │  Caddy (reverse proxy)                       │ ← 443 / 80       │
│  │  TLS termination + mTLS client cert auth     │                  │
│  └──────────────────┬───────────────────────────┘                  │
│                     │ 127.0.0.1:18789                              │
│  ┌──────────────────▼───────────────────────────┐                  │
│  │  openclaw-gateway  (Docker)                  │                  │
│  │  image: openclaw-with-iproute2:20260408      │                  │
│  │                                              │                  │
│  │  baked in:  ffmpeg · whisper · iproute2      │                  │
│  │  volume:    /opt/openclaw/config/  → state   │                  │
│  │             /opt/openclaw/workspace/ → bot   │                  │
│  │             /opt/obsidian-vault/ → vault     │                  │
│  │                                              │                  │
│  │  tools:  shell · fs · web · browser          │                  │
│  │          subagents · sessions · cron         │                  │
│  └──────────────────┬───────────────────────────┘                  │
│                     │ Docker network (openclaw_default)            │
│  ┌──────────────────▼───────────────────────────┐                  │
│  │  LightRAG  (Docker)        127.0.0.1:8020    │                  │
│  │  image: ghcr.io/hkuds/lightrag:latest        │                  │
│  │                                              │                  │
│  │  LLM:       gemini-2.0-flash                 │                  │
│  │  Embedding: gemini-embedding-001 (dim=3072)  │                  │
│  │  Storage:   NetworkX · NanoVectorDB · JsonKV │                  │
│  │                                              │                  │
│  │  inputs (read-only):                         │                  │
│  │    workspace/  ←  /opt/openclaw/workspace    │                  │
│  │    obsidian/   ←  /opt/obsidian-vault        │                  │
│  └──────────────────────────────────────────────┘                  │
│                                                                     │
│  /opt/obsidian-vault/   ← Syncthing bidirectional sync with Mac    │
└─────────────────────────────────────────────────────────────────────┘
          │                        │                    │
          ▼                        ▼                    ▼
   Telegram Bot API          OpenAI (gpt-5.4)    Google Gemini API
   (inbound messages)        via openai-codex     (LightRAG LLM +
                             OAuth                 embeddings)
```

---

## Features

- **Telegram interface** — DM (allowlist) + supergroup (mention-free in designated chat)
- **Voice messages** — Whisper transcription baked into container
- **Three-layer memory** — live workspace → raw decision log → LightRAG knowledge graph
- **Obsidian vault sync** — bidirectional Syncthing between Mac (iCloud) and server, changes propagate in seconds
- **Full tool access** — shell exec, filesystem, web search, browser, subagents, cron
- **Persistent sessions** — per-channel-peer session scope, resumes context across restarts
- **Knowledge graph queries** — hybrid vector + graph retrieval via LightRAG

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Agent runtime | [OpenClaw](https://github.com/coollabsio/openclaw) (Docker) |
| LLM | OpenAI gpt-5.4 via openai-codex OAuth |
| Knowledge graph | [LightRAG](https://github.com/HKUDS/LightRAG) + Gemini embeddings |
| Voice transcription | Whisper (ffmpeg, baked into image) |
| Interface | Telegram Bot API |
| Reverse proxy | Caddy 2 (mTLS client cert auth) |
| Notes sync | Obsidian ↔ [Syncthing](https://syncthing.net) (bidirectional) |
| Host | Hetzner CX23, Ubuntu 24.04 |

---

## Memory System

Three trust layers — never conflate them:

```
LIVE    — docker ps / curl / logs        highest trust, current state only
RAW     — workspace/raw/YYYY-MM-DD-*.md  verbatim decisions, redacted before commit
DERIVED — MEMORY.md, daily notes         quick recall, not canonical
```

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
│   ├── caddy.redacted.Caddyfile    reverse proxy config template
│   ├── docker-compose.redacted.yml compose template
│   ├── env.redacted.example        env vars template
│   └── auth-profile.redacted.json  OAuth profile template
├── docs/
│   ├── 01-server-state.md          current server snapshot (services, ports, images)
│   ├── 02-openclaw-installation.md deployment decisions and auth setup
│   ├── 03-operations.md            SSH commands, full ops runbook
│   ├── 06-command-log.md           full command history with decision context
│   ├── 07-architecture-and-security.md  security model (mTLS, UFW, exec policy)
│   ├── 08-git-and-redaction-policy.md   git safety rules, secret handling
│   ├── 09-workspace-setup.md       bot personalisation guide
│   ├── 10-memory-architecture.md   three-layer memory system design
│   └── 11-lightrag-setup.md        LightRAG deployment and ingestion guide
├── scripts/
│   ├── deploy-workspace.sh         rsync workspace/ to server
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
5. **Provision LightRAG** (first time): `./scripts/setup-lightrag.sh`
6. **Set up Obsidian sync**: install Syncthing on Mac (`brew install syncthing && brew services start syncthing`) and follow `docs/03-operations.md` → "Obsidian vault sync — Syncthing setup"

---

## Quick Operations

```bash
export OPENCLAW_HOST="deploy@<server-host>"

# Deploy workspace changes to server
./scripts/deploy-workspace.sh

# Check gateway health
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'curl -sf http://127.0.0.1:18789/healthz'

# Check LightRAG health
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'curl -sf http://127.0.0.1:8020/health | jq .status'

# Trigger knowledge graph re-index
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '/opt/lightrag/scripts/lightrag-ingest.sh'

# Check Obsidian vault sync status (Syncthing)
open http://127.0.0.1:8384

# Trigger LightRAG re-index after bulk Obsidian changes
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '/opt/lightrag/scripts/lightrag-ingest.sh'
```

See [`docs/03-operations.md`](docs/03-operations.md) for the full ops runbook.

---

## Security

- **Reverse proxy**: Caddy with mTLS — client certificate required for all external access
- **LightRAG**: bound to `127.0.0.1:8020` only — not reachable from internet
- **Firewall**: UFW allows only `22/tcp`, `80/tcp`, `443/tcp`
- **Bot tools**: `profile=full`, `exec=full` — Telegram access restricted to allowlist (owner only)
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
7. [`docs/08-git-and-redaction-policy.md`](docs/08-git-and-redaction-policy.md) — git safety rules

---

## License

MIT
