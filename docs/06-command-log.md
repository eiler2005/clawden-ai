# Command Log

High-signal, sanitized setup log.

This file intentionally records the sequence of work and the kinds of commands used, but avoids live credentials, raw tokens, and real connection coordinates.

## 1. Initial host inspection

Used to capture:

- OS and kernel version
- running services
- Docker containers
- listening ports
- resource headroom

Representative command shape:

```bash
ssh -i ~/.ssh/id_rsa deploy@<server-host> 'hostnamectl; uptime; free -h; df -h; docker ps; ss -lntup'
```

## 2. OpenClaw project bootstrap

Created:

- `/opt/openclaw`
- `/opt/openclaw/config`
- `/opt/openclaw/workspace`

Pulled and adapted upstream deployment material.

## 3. Runtime alignment

Adjusted Compose behavior to match the real container entrypoint used by the upstream image.

Representative runtime shape:

```bash
node openclaw.mjs gateway --allow-unconfigured --bind lan --port 18789
```

## 4. Auth profile materialization

Used a temporary local-auth bootstrap to let OpenClaw create its own provider profile, then removed the temporary bootstrap source from the server.

## 5. Public access experiments

The public path evolved through several phases:

1. localhost-only via SSH tunnel
2. reverse proxy experiments
3. early public access with HTTP auth
4. final public path with `mTLS`

## 6. Final public architecture

The stable public design became:

- `Caddy` on `80/443`
- client certificate required at the edge
- full Control UI + API traffic proxied to the local OpenClaw gateway

## 7. Runtime image fix

A small derived image was built to add `iproute2`, because the chosen bind/network mode depended on `ip neigh show` and the upstream image did not include that binary.

## 8. Local-only access materials

The following were deliberately kept out of committed docs:

- server access notes
- client certificate files
- certificate passwords
- tokenized dashboard URLs

## 9. Container transcription tools (Whisper + ffmpeg)

Date: `2026-04-05`

Goal: enable speech-to-text in the same runtime context where OpenClaw executes tools (the gateway container image).

Why this mattered:

- installing Whisper on the host OS did not make it available to tool execution inside the container

Key choices:

- bake `ffmpeg` + `openai-whisper` into the derived OpenClaw runtime image
- use an isolated venv in the image (`/opt/openclaw-whisper-venv`)
- force a CPU-only `torch` wheel to avoid pulling CUDA stacks on a CPU-only VPS
- keep the host OS lean by removing the earlier host-side experiment packages
- explicitly verify the boundary after cleanup: absent on host, present in `openclaw-gateway`

Representative command shape (sanitized):

```bash
cd /opt/openclaw

# update derived Dockerfile (iproute2 + ffmpeg + whisper venv)
sudo $EDITOR /opt/openclaw/Dockerfile.iproute2

sudo docker build -t openclaw-with-iproute2:20260405 -f Dockerfile.iproute2 .
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260405/" /opt/openclaw/.env
sudo docker compose up -d --force-recreate openclaw-gateway

docker compose exec -T openclaw-gateway which whisper
docker compose exec -T openclaw-gateway which ffmpeg
docker compose exec -T openclaw-gateway which ffprobe

# host cleanup (only if previously installed on host)
sudo apt-get purge -y ffmpeg python3-pip python3-venv || true
sudo apt-get autoremove -y || true
```

## 10. OpenClaw core update test (latest) and rollback

Date: `2026-04-06`

Goal: update runtime from `OpenClaw 2026.4.2` to the latest available upstream release.

Validation source:

- GitHub Releases for `openclaw/openclaw` showed `openclaw 2026.4.5` marked as latest.

Applied update shape:

```bash
cd /opt/openclaw

# validate latest image version from GHCR
sudo docker pull ghcr.io/openclaw/openclaw:latest
sudo docker run --rm ghcr.io/openclaw/openclaw:latest openclaw --version

# rebuild derived runtime image on top of latest upstream
sudo docker build --pull -t openclaw-with-iproute2:20260406 -f Dockerfile.iproute2 .

# switch deployment image and recreate gateway
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260406/" /opt/openclaw/.env
sudo docker compose up -d --force-recreate openclaw-gateway

# verify
sudo docker compose exec -T openclaw-gateway openclaw --version
```

Result:

- latest image path (`2026.4.5`) was validated
- runtime rollback was applied to keep service stability:
  - running container image: `openclaw-with-iproute2:20260405`
  - running OpenClaw version: `2026.4.2`

## 11. Health and proxy architecture normalization

Date: `2026-04-06`

Goal: remove split UI serving and define a deterministic readiness contract.

Applied shape:

```bash
# Compose: strict readiness probe on gateway /healthz
cd /opt/openclaw
sudo $EDITOR docker-compose.yml
sudo docker compose up -d openclaw-gateway

# Caddy: proxy all HTTP + WebSocket traffic to gateway
sudo $EDITOR /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Result:

- edge now has a single backend path (`127.0.0.1:18789`) for UI + API
- no host-side static UI copy is required for serving requests
- `docker compose ps` now reflects strict readiness (`starting/unhealthy/healthy`) based on `/healthz`

## 12. 2026.4.5 upgrade execution and rollback incident

Date: `2026-04-06`

Goal:

- move runtime from `openclaw-with-iproute2:20260405` (`OpenClaw 2026.4.2`)
- to `openclaw-with-iproute2:20260406` (`OpenClaw 2026.4.5`)

What was executed:

```bash
cd /opt/openclaw
sudo docker pull ghcr.io/openclaw/openclaw:latest
sudo docker run --rm ghcr.io/openclaw/openclaw:latest openclaw --version
sudo docker build --pull -t openclaw-with-iproute2:20260406 -f Dockerfile.iproute2 .
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260406/" .env
sudo docker compose up -d --force-recreate openclaw-gateway
```

Observed behavior:

- version switch succeeded (`OpenClaw 2026.4.5` in container)
- gateway process entered a high-CPU state and did not bind `:18789`
- edge returned persistent `502 Bad Gateway` instead of converging after startup
- attempted mitigations (`--force`, `bind=custom` + `customBindHost=0.0.0.0`) did not restore availability

Rollback action:

- reverted image tag in `.env` to `openclaw-with-iproute2:20260405`
- restored pre-change `docker-compose.yml` and `openclaw.json` backups

Current caveat at incident time:

- during rollback validation, SSH access to the host started timing out during banner exchange
- final post-rollback health confirmation could not be completed from this workspace session

Status:

- superseded by Section 13 after access recovery and full validation

## 13. Recovery confirmation after temporary SSH firewall widening

## 14. LLM-Wiki rollout v2 and safe cutover attempt

Date: `2026-04-14`

Goal:

- introduce curated `wiki/` + narrowed `raw/signals/` ingest for LightRAG
- deploy the internal `wiki-import` bridge
- switch LightRAG away from indexing the full legacy vault
- prepare bot-owned curated import flow

Representative command shape:

```bash
# deploy deterministic curated import bridge
OPENCLAW_HOST="deploy@<server-host>" bash scripts/deploy-wiki-import.sh

# safe LightRAG cutover without wiping /opt/obsidian-vault
OPENCLAW_HOST="deploy@<server-host>" bash scripts/setup-llm-wiki.sh
```

Observed result:

- `wiki-import` deployed to `/opt/wiki-import`, bound to `127.0.0.1:8095`
- scaffold deployment to `/opt/obsidian-vault/wiki` started successfully
- tracked `/opt/lightrag/scripts/lightrag-ingest.sh` was replaced with the narrowed v2 script
- LightRAG rebuild/restart path became heavy enough that the host stopped completing new SSH banner exchanges during the rollout window

Operational note:

- the cutover flow was adjusted to use `sudo` for clearing derived LightRAG state because parts of
  `/opt/lightrag/data/` were root-owned
- rollout validation and bootstrap imports must resume only after SSH responsiveness is restored

Date: `2026-04-06`

What was verified after SSH access was restored:

- host reachable over SSH again
- compose state:
  - `openclaw-openclaw-gateway-1` is `Up ... (healthy)`
  - running image is back to `openclaw-with-iproute2:20260405`
  - `openclaw --version` reports `OpenClaw 2026.4.2`
- public access check with client certificate:
  - `https://<public-host>/` returns `HTTP/1.1 200 OK`

Additional isolation test:

- `2026.4.5` was reproduced in clean throwaway containers (with fresh config volume and loopback bind)
- same symptom appeared: high CPU `openclaw-gateway`, no listening port, `/healthz` connection reset

Conclusion:

- keep production pinned to `20260405` for now
- treat `2026.4.5` as blocked in this environment until upstream/root-cause fix is available

## 14. Second 2026.4.5 upgrade attempt — blocked by smoke-test

Date: `2026-04-07`

Goal: retry upgrade to `OpenClaw 2026.4.5` using the new safe upgrade SOP (backup → isolated smoke-test → switch).

Pre-flight:

- backup taken: `/opt/openclaw-backup-20260407-121633`
- baseline confirmed: `openclaw-with-iproute2:20260405`, `OpenClaw 2026.4.2`, `healthy`

Image built:

```bash
sudo docker pull ghcr.io/openclaw/openclaw:latest   # confirmed 2026.4.5
sudo docker build --pull -t openclaw-with-iproute2:20260407 -f Dockerfile.iproute2 .
```

Smoke-test (isolated throwaway container, loopback bind, port 19999):

```bash
sudo docker run -d \
  --name openclaw-test-upgrade \
  -p 127.0.0.1:19999:18789 \
  openclaw-with-iproute2:20260407 \
  node openclaw.mjs gateway --allow-unconfigured --bind loopback --port 18789
sleep 25
curl -sf http://127.0.0.1:19999/healthz   # → FAIL
```

Observed:

- container running, ExitCode=0
- CPU: ~130% (high-CPU spin loop)
- port 18789 not bound
- container logs: empty (process stalls before logger init)
- identical to Section 12–13 failure mode

Result:

- smoke-test caught the failure **before touching production**
- production remained on `20260405` throughout — no rollback needed
- `2026.4.5` still blocked in this environment
- await upstream fix or release notes explaining the startup regression

## 15. Successful upgrade to OpenClaw 2026.4.8

Date: `2026-04-08`

Goal: upgrade from `openclaw-with-iproute2:20260405` (`OpenClaw 2026.4.2`) to `2026.4.8` following the safe upgrade SOP.

Note: `:latest` resolved to `2026.4.8` (not `2026.4.7` as initially expected — upstream released a patch).

Pre-flight:

- backup: `/opt/openclaw-backup-20260408-073652`
- baseline: `20260405`, `OpenClaw 2026.4.2`, `healthy`

Build:

```bash
sudo docker pull ghcr.io/openclaw/openclaw:latest  # → OpenClaw 2026.4.8
sudo docker build --pull -t openclaw-with-iproute2:20260408 -f Dockerfile.iproute2 .
```

Smoke-test (key lesson from prior attempts):

- `--bind loopback` inside container = 127.0.0.1 on container loopback, not reachable via Docker port mapping
- must use `--bind lan` for smoke-test so Docker port mapping (127.0.0.1:19999→18789) works

```bash
sudo docker run -d \
  --name openclaw-test-upgrade \
  -p 127.0.0.1:19999:18789 \
  openclaw-with-iproute2:20260408 \
  node openclaw.mjs gateway --allow-unconfigured --bind lan --port 18789
# PASS at t=30s
```

Startup profile vs 2026.4.5:
- 2026.4.5: empty logs, CPU ~130%, port never bound → broken
- 2026.4.8: logs normal, gateway ready in ~14s, CPU ~0% at idle → healthy

Production switch:

```bash
sudo sed -i "s/^OPENCLAW_IMAGE=.*/OPENCLAW_IMAGE=openclaw-with-iproute2:20260408/" .env
sudo docker compose up -d --force-recreate openclaw-gateway
```

doctor output: no errors; applied startup optimization hints:

```bash
# added to .env:
NODE_COMPILE_CACHE=/var/tmp/openclaw-compile-cache
OPENCLAW_NO_RESPAWN=1
sudo mkdir -p /var/tmp/openclaw-compile-cache
```

Result:

- `openclaw-with-iproute2:20260408`, `OpenClaw 2026.4.8`, `healthy`
- startup time: ~90s to `healthy` (Compose probe convergence)
- `2026.4.5` startup regression confirmed fixed in `2026.4.8`

## 17. Workspace onboarding — bot personalisation

Date: `2026-04-08`

Goal: configure OpenClaw workspace files to give the bot a persistent identity, user profile, and operating rules.

### Context

OpenClaw loads Markdown files from its workspace at the start of every session. Before this step, the workspace was empty (only a pre-existing `BOOTSTRAP.md` was present from initial setup). After this step, the bot has a named identity ("Бенька"), knows who Denis is, and operates under explicit anti-sycophancy rules.

### Files created in `workspace/` (tracked in git as templates)

| File | Purpose |
|------|---------|
| `IDENTITY.md` | Bot name (Бенька 🐾), emoji, schnauzer personality |
| `SOUL.md` | Anti-sycophancy protocol, communication values, techno-minimalist purpose |
| `USER.md` | Denis's profile — tech enthusiast, builder, domain character, interests |
| `AGENTS.md` | Operating instructions, session protocol, decision approach |
| `MEMORY.md` | Long-term curated memory: active projects, partnerships, professional facts |
| `HEARTBEAT.md` | Lightweight periodic tasks (no heavy sweeps — preserves tokens) |
| `TOOLS.md` | Workspace tools + Denis's external tools and stack |
| `BOOT.md` | Session startup checklist |

### Deploy script created

`scripts/deploy-workspace.sh` — rsync-based deploy from `workspace/` to `/opt/openclaw/workspace/` on the server.

### Deployment (Method B — rsync via SSH)

```bash
OPENCLAW_HOST="deploy@<server-host>" ./scripts/deploy-workspace.sh
```

Transfer result: 9 files, 7982 bytes sent, speedup 1.74x.

### Verification on server

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" \
  'docker compose -f /opt/openclaw/docker-compose.yml exec -T openclaw-gateway \
   sh -lc "ls -la /home/node/.openclaw/workspace/"'
```

All 8 files confirmed present alongside pre-existing `BOOTSTRAP.md`.

### Functional test

Connected to the bot via web UI, ran `/new` to start a fresh session:

- bot responded with name "Бенька" ✓
- bot described Denis's profile from `USER.md` ✓
- anti-sycophancy mode active ✓

### Documentation added

- `docs/09-workspace-setup.md` — full onboarding guide (both Method A and B)
- `docs/03-operations.md` — expanded with detailed web UI connection steps and workspace management commands

## 16. Web search enabled

Date: `2026-04-08`

Goal: add web search capability using the existing OpenAI Codex provider (no new API keys).

Configuration added to `/opt/openclaw/config/openclaw.json` under `tools.web.search`:

```json
{
  "tools": {
    "web": {
      "search": {
        "enabled": true,
        "provider": "duckduckgo",
        "maxResults": 5,
        "cacheTtlMinutes": 15,
        "openaiCodex": {
          "enabled": true,
          "mode": "cached",
          "contextSize": "high",
          "userLocation": {
            "country": "RU",
            "timezone": "Europe/Moscow"
          }
        }
      }
    }
  }
}
```

How it works:

- `openaiCodex.enabled: true` — activates provider-native search for `openai-codex/*` models (already configured). No new API key needed — uses the existing Codex auth profile.
- `provider: "duckduckgo"` — key-free HTML-based fallback for non-Codex models or if Codex search is unavailable.
- `mode: "cached"` — recommended default, avoids redundant search calls.

Applied via Python merge script (same pattern as security settings), then `docker compose up -d --force-recreate openclaw-gateway`. Gateway converged to `healthy` with no config errors.

## 17. Telegram group configured for all-message mode (no mention required)

Date: `2026-04-08`

Goal: make bot respond to all messages in the "Семья" supergroup (with topics) without requiring @mention or reply.

Context:

- group is a Telegram forum supergroup with topics
- bot is already admin with Privacy Mode disabled in BotFather
- previously: `groups."*".requireMention: true` — bot only responded to @mention

Configuration added to `channels.telegram` in `/opt/openclaw/config/openclaw.json`:

```json
{
  "channels": {
    "telegram": {
      "groupAllowFrom": ["<owner-user-id>"],
      "groups": {
        "*": {
          "requireMention": true
        },
        "<supergroup-chat-id>": {
          "requireMention": false,
          "groupPolicy": "open"
        }
      }
    }
  }
}
```

Key settings:

- `groupAllowFrom` — explicit user allowlist for group triggers (separate from DM `allowFrom`)
- `requireMention: false` — bot reads and responds to every message in this group
- `groupPolicy: "open"` — any group member can trigger the bot (not just allowlisted users)
- `"*"` default kept as `requireMention: true` — all other groups still require @mention

Group chat ID found in OpenClaw session store (`sessions.json`) — actual value in `LOCAL_ACCESS.md`.

Apply shape:

```bash
# Python merge into /opt/openclaw/config/openclaw.json
# then:
sudo docker compose up -d --force-recreate openclaw-gateway
```

Result:

- gateway `healthy`, bot responds to all messages in target group without @mention
- other groups unaffected

## 18. Security hardening — OpenClaw config and Caddy

Date: `2026-04-07`

Reference: [docs.openclaw.ai/gateway/security](https://docs.openclaw.ai/gateway/security)

Goal: apply all relevant security settings from the official security reference to the running deployment.

### Pre-step: capture Docker bridge IP for trustedProxies

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  docker network inspect opt_openclaw_default \
    --format "{{range .IPAM.Config}}{{.Gateway}}{{end}}" 2>/dev/null ||
  docker network inspect bridge \
    --format "{{range .IPAM.Config}}{{.Gateway}}{{end}}"
'
```

Actual IP recorded in `LOCAL_ACCESS.md` (not committed).

### Changes to /opt/openclaw/config/openclaw.json

Added the following top-level sections (merged with existing `agents` and `auth` sections):

```json
{
  "gateway": {
    "mode": "local",
    "auth": { "allowTailscale": false, "rateLimit": {} },
    "trustedProxies": ["<docker-bridge-gateway-ip>"],
    "allowRealIpFallback": false
  },
  "tools": {
    "profile": "messaging",
    "exec": { "security": "deny", "ask": "always" },
    "fs": { "workspaceOnly": true },
    "elevated": { "enabled": false }
  },
  "logging": { "redactSensitive": "tools" },   // "all" rejected by 2026.4.2 (allowed: "off", "tools")
  "discovery": { "mdns": { "mode": "off" } },
  "session": { "dmScope": "per-channel-peer" },
  "browser": { "ssrfPolicy": { "dangerouslyAllowPrivateNetwork": false } }
}
```

Representative apply shape:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/openclaw &&
  sudo $EDITOR config/openclaw.json   # merge new sections
  sudo docker compose up -d --force-recreate openclaw-gateway
  sleep 15
  docker compose ps
  docker compose exec -T openclaw-gateway openclaw --version
'
```

### Changes to /etc/caddy/Caddyfile

Updated HSTS max-age from 300 to 31536000 (1 year production standard):

```
Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
```

Apply shape:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  sudo $EDITOR /etc/caddy/Caddyfile
  sudo caddy validate --config /etc/caddy/Caddyfile
  sudo systemctl reload caddy
'
```

### Validation after apply

```bash
# Gateway healthy
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" 'cd /opt/openclaw && docker compose ps'

# mTLS public endpoint
curl -skI --cert-type P12 \
  --cert /path/to/client.p12:<password> \
  https://<public-host>/
# Expected: HTTP/1.1 200 OK

# Verify HSTS header value
curl -skI --cert-type P12 \
  --cert /path/to/client.p12:<password> \
  https://<public-host>/ | grep -i strict
# Expected: max-age=31536000
```

Result:

- gateway remained healthy after config reload
- all security settings applied as documented in `docs/07-architecture-and-security.md`
- redacted artifacts updated in repo (`artifacts/openclaw/`)

## 19. Builtin OpenClaw memorySearch enabled over curated wiki only

Date: `2026-04-15`

Goal: enable the gateway's builtin memory layer for fast local recall without breaking the existing
LLM-Wiki / LightRAG architecture.

Configuration applied to `/opt/openclaw/config/openclaw.json`:

```json
{
  "memory": {
    "citations": "auto"
  },
  "agents": {
    "defaults": {
      "memorySearch": {
        "enabled": true,
        "provider": "gemini",
        "model": "gemini-embedding-001",
        "extraPaths": ["/opt/obsidian-vault/wiki"],
        "cache": {
          "enabled": true,
          "maxEntries": 50000
        },
        "query": {
          "hybrid": {
            "enabled": true,
            "vectorWeight": 0.7,
            "textWeight": 0.3,
            "mmr": {
              "enabled": true,
              "lambda": 0.7
            }
          }
        }
      }
    }
  }
}
```

Runtime change:

- forwarded `GEMINI_API_KEY` into `openclaw-gateway` and `openclaw-cli`
- reused the existing Gemini embedding key already present in `/opt/lightrag/.env`
- kept the retrieval boundary narrow: builtin memory indexes only `MEMORY.md`, `memory/**/*.md`,
  and `/opt/obsidian-vault/wiki/**/*.md`
- explicitly did not expand builtin memory to `raw/signals`, `raw/articles`, `raw/documents`, or
  legacy vault trees

Why this shape:

- builtin memory is a fast local recall layer for curated files
- LightRAG remains the broader historical retrieval layer over `workspace + wiki + raw/signals`
- raw vault sources stay out of retrieval until curated import materializes them into canonical wiki pages

Applied on the live server with targeted config and compose updates, then verified via:

- `curl http://127.0.0.1:18789/healthz`
- `docker compose ps openclaw-gateway`
- `openclaw memory index --force`
- `openclaw memory status --deep`
- `openclaw memory search "LightRAG"`

## 20. Builtin memorySearch post-tuning for Hetzner CX23

Date: `2026-04-15`

Goal: reduce host impact from future builtin memory indexing and search on the small `CX23` VPS
without changing the retrieval boundary.

Configuration adjustments:

```json
{
  "agents": {
    "defaults": {
      "memorySearch": {
        "remote": {
          "batch": {
            "enabled": true,
            "concurrency": 1,
            "wait": false
          }
        },
        "query": {
          "hybrid": {
            "candidateMultiplier": 2,
            "mmr": {
              "enabled": false
            }
          }
        }
      }
    }
  }
}
```

Why this shape:

- `candidateMultiplier=2` shrinks the hybrid search candidate pool from the more expensive default
- disabling MMR removes an extra reranking pass that is unnecessary on the small curated corpus
- provider-side Gemini batch mode keeps embedding work gentler for future reindex runs
- `concurrency=1` avoids turning reindex into a bursty background job on a 4 GB VPS

Operational note:

- after the first builtin memory backfill, avoid launching multiple `openclaw memory ...` commands
  in parallel on this host
- prefer one-at-a-time smoke checks (`memory status`, then `memory search`) and schedule forced
  rebuilds off-hours when possible

## 28. Knowledgebase + Ideas topics: search, auto-ingest, dual-mode

Date: `2026-04-16`

### 28a. Knowledgebase topic (topic_id=232) — dual-mode

Goal: make the Knowledgebase supergroup topic dual-purpose — plain-text messages trigger knowledge base search; any other content (forwarded post, link, plain text) is auto-structured and ingested by the bot without any manual fields from Denis.

Changes:

- `artifacts/openclaw/telegram-surfaces.redacted.json` — added Knowledgebase surface: type `supergroup_topic`, chat_id `<ops-supergroup-chat-id>`, topic_id=232; `search_mode` with backends `lightrag_hybrid` + `memory_search`, max 5 results, snippet+citations format; `auto_structure: true`, `required_fields_filled_by: agent` (bot extracts title/domain/source/date/summary automatically)
- `workspace/TELEGRAM_POLICY.md` — Knowledgebase row: question → search, any content → bot auto-extracts + wiki_ingest
- `workspace/TOOLS.md` — `knowledge_channel` section: intent routing + response format template; bot extracts all metadata, Denis never fills structured fields manually
- `docs/12-telegram-channel-architecture.md`, `docs/15-llm-wiki-query-flow.md`, `docs/03-operations.md` — updated to reflect dual-mode

**Note:** `openclaw.json` groups section was NOT changed — the existing supergroup entry already covers all topics including Knowledgebase.

### 28b. Ideas topic (topic_id=639) — frictionless capture

Goal: create a dedicated Ideas topic in the supergroup for zero-friction capture of Telegram posts, links, and thoughts; promote to Knowledgebase on demand.

Changes:

- Created forum topic `💡 Ideas` in `Ben'ka_Clawbot_SuperGroup` via Bot API `createForumTopic`; assigned topic_id=639
- `artifacts/openclaw/telegram-surfaces.redacted.json` — added Ideas surface: type `supergroup_topic`, topic_id=639, mode `idea_capture`; bot auto-captures, classifies, tags, queues; no RAG write without explicit promotion
- `workspace/TOOLS.md` — `ideas_capture` section: any message in topic_id=639 → auto-capture, respond "✅ Захвачено: [тема]. Тег: [domain]"
- `workspace/TELEGRAM_POLICY.md` — Ideas row: any content → auto-capture + queue, promote on demand
- `artifacts/openclaw/telegram-topic-map.json` — added `knowledgebase: 232` and `ideas: 639`
- Pinned usage instructions in both topics via Bot API
