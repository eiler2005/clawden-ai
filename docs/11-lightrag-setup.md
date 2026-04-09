# LightRAG Setup

LightRAG is the knowledge graph brain for the memory system. It indexes all markdown content
(workspace files + Obsidian vault) and provides hybrid retrieval (vector + graph traversal).

See `docs/10-memory-architecture.md` for the full memory system context.

---

## Architecture Position

```
Mac iCloud vault (/DenisJournals) ──rsync every 15 min──────────────────┐
workspace/ markdown files ──────────────────────────────────────────────┤
                                                                        ▼
                                                           /opt/obsidian-vault/
                                                           /opt/openclaw/workspace/
                                                                        │
                                                                        ▼
                                                           LightRAG (:8020)
                                                           [127.0.0.1 only]
                                                                        │
                              ┌─────────────────────────────────────────┘
                              ▼
                     OpenClaw bot (Бенька)
                     lightrag_query tool call
```

LightRAG is NOT exposed publicly. Caddy does not proxy it. Internal access only.

---

## Resource Requirements (Hetzner CX23: 3 vCPU, 4GB RAM)

| Component | Choice | Why |
|-----------|--------|-----|
| Graph storage | NetworkX (built-in) | File-based, no Neo4j |
| Vector storage | NanoVectorDB (built-in) | File-based, no Qdrant |
| KV storage | JsonKV (built-in) | File-based, no Redis |
| LLM | `gemini-2.0-flash` | Fast, cheap, free tier 15 RPM / 1500 RPD |
| Embedding | `gemini-embedding-001` | Same API key, dim=3072 |

All graph/vector data lives under `/opt/lightrag/data/` on the host.

**One API key total: Google Gemini.** Free tier covers typical RAG workload.  
Get key: https://aistudio.google.com/app/apikey

**Free tier limits (important for bulk ingestion):**
- 15 requests per minute (RPM)
- 1,500 requests per day (RPD) — resets at UTC midnight (03:00 МСК)
- If RPD is exhausted during bulk indexing: wait for reset, or add billing to the GCP project

---

## Directory Layout on Server

```
/opt/lightrag/
├── docker-compose.yml          ← upstream file (from GitHub clone)
├── docker-compose.override.yml ← our overrides (ports, volumes, image)
├── .env                        ← secrets, gitignored
├── data/                       ← LightRAG persistent state (graph + vectors + kv)
│   └── inputs/
│       ├── obsidian/           ← mounted from /opt/obsidian-vault (read-only)
│       └── workspace/          ← mounted from /opt/openclaw/workspace (read-only)
└── scripts/
    └── lightrag-ingest.sh      ← manual/cron re-index trigger

/opt/obsidian-vault/            ← rsync target from Mac iCloud vault
```

---

## Docker Compose

The upstream `docker-compose.yml` is not modified. Our settings go in `docker-compose.override.yml`.

File: `/opt/lightrag/docker-compose.override.yml`

```yaml
services:
  lightrag:
    image: lightrag-local:latest   # local build; falls back to ghcr.io/hkuds/lightrag:latest
    ports:
      - "127.0.0.1:8020:9621"      # internal only; container port is 9621
    volumes:
      - ./data:/app/data
      - /opt/obsidian-vault:/app/data/inputs/obsidian:ro
      - /opt/openclaw/workspace:/app/data/inputs/workspace:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:9621/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 90s
```

**Start command** (always use both files):

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
'
```

**Image note:** local build `lightrag-local:latest` was built from `Dockerfile.lite` in the cloned repo.
The upstream `ghcr.io/hkuds/lightrag:latest` is also available and equivalent.

---

## Environment File

File: `/opt/lightrag/.env` (never commit — keep actual key in `LOCAL_ACCESS.md`)

Generate it with:
```bash
./scripts/create-lightrag-env.sh
```

Or manually from template `scripts/lightrag.env.template`:

```env
# LLM: Google Gemini Flash
LLM_BINDING=gemini
LLM_MODEL=gemini-2.0-flash
LLM_BINDING_API_KEY=<gemini-api-key>
LLM_BINDING_HOST=https://generativelanguage.googleapis.com
LLM_MAX_TOKEN_SIZE=32768

# Embeddings: Google Gemini (same key)
EMBEDDING_BINDING=gemini
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_BINDING_API_KEY=<gemini-api-key>
EMBEDDING_BINDING_HOST=https://generativelanguage.googleapis.com
EMBEDDING_DIM=3072
EMBEDDING_MAX_TOKEN_SIZE=2048

# Storage: file-based
LIGHTRAG_KV_STORAGE=JsonKVStorage
LIGHTRAG_VECTOR_STORAGE=NanoVectorDBStorage
LIGHTRAG_GRAPH_STORAGE=NetworkXStorage
LIGHTRAG_DOC_STATUS_STORAGE=JsonDocStatusStorage

# Rate limiting (important for free tier)
MAX_PARALLEL_INSERT=1
MAX_ASYNC=2
TIMEOUT=120

# Server
HOST=0.0.0.0
PORT=9621
CORS_ORIGINS=http://127.0.0.1
LIGHTRAG_WORKING_DIR=/app/data
WEBUI_TITLE=БенькаMemory
```

Only `LLM_BINDING_API_KEY` / `EMBEDDING_BINDING_API_KEY` (Gemini key) are secret.

---

## Obsidian Vault Sync

### Method: rsync from Mac (deployed)

The vault is synced one-way from Mac iCloud to server via rsync. No git repo needed on the server.

**Mac vault path:** `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/DenisJournals`  
**Server path:** `/opt/obsidian-vault/`

Script: `scripts/sync-obsidian.sh`

```bash
# One-time manual sync:
OPENCLAW_HOST="deploy@<server-host>" ./scripts/sync-obsidian.sh
```

### Auto-sync via launchd (installed on Mac)

Template: `scripts/com.openclaw.obsidian-sync.plist.template`

Installed at: `~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist`

Runs every 900 seconds (15 minutes). With `TRIGGER_REINDEX=true`, calls the ingest script on server after sync.

```bash
# Load (run once after install):
launchctl load ~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist

# Check status:
launchctl list | grep obsidian

# Unload:
launchctl unload ~/Library/LaunchAgents/com.openclaw.obsidian-sync.plist
```

Logs: `/tmp/obsidian-sync.log`, `/tmp/obsidian-sync-error.log`

---

## Ingestion

**Important:** `POST /documents/scan` does NOT recurse into subdirectories. Use `POST /documents/upload` file-by-file instead.

### Ingest script on server

File: `/opt/lightrag/scripts/lightrag-ingest.sh`

```bash
#!/bin/bash
# Uploads all .md files under /opt/lightrag/data/inputs/ to LightRAG one by one
set -euo pipefail
INPUT_BASE="/opt/lightrag/data/inputs"

for file in $(find "$INPUT_BASE" -name "*.md" -type f); do
  curl -sf -X POST http://127.0.0.1:8020/documents/upload \
    -F "file=@${file}" \
    -F "description=auto-ingested" | jq -c '.'
done
echo "LightRAG re-index triggered at $(date)"
```

### Trigger manually from local machine

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '/opt/lightrag/scripts/lightrag-ingest.sh'
```

### Cron (installed on server)

```
*/30 * * * * /opt/lightrag/scripts/lightrag-ingest.sh >> /var/log/lightrag-ingest.log 2>&1
```

---

## Querying

From OpenClaw bot (Бенька) via `lightrag_query` tool (see `workspace/TOOLS.md`):

```
POST http://127.0.0.1:8020/query
Content-Type: application/json

{"query": "why did we choose PostgreSQL over Redis", "mode": "hybrid"}
```

Direct test from server:

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf -X POST http://127.0.0.1:8020/query \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"test query\", \"mode\": \"hybrid\"}" | jq .
'
```

---

## Operations

### Start LightRAG

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
'
```

### Check status

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml ps
'
```

### Check health

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/health | jq .
'
```

### View logs

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml logs --tail=100 lightrag
'
```

### View indexed documents

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  curl -sf http://127.0.0.1:8020/documents | jq .
'
```

### WebUI access (via SSH tunnel)

LightRAG has a built-in WebUI at port 9621. Access it locally via SSH tunnel:

```bash
ssh -i ~/.ssh/id_rsa -L 9621:127.0.0.1:8020 "$OPENCLAW_HOST" -N &
# Then open: http://127.0.0.1:9621
```

### Restart

```bash
ssh -i ~/.ssh/id_rsa "$OPENCLAW_HOST" '
  cd /opt/lightrag &&
  docker compose -f docker-compose.yml -f docker-compose.override.yml restart lightrag
'
```

---

## Initial Indexing Notes

During the first bulk index of all Obsidian + workspace files (26+ files), the Gemini free tier
RPD limit (1500/day) can be exhausted. If you see `429 RESOURCE_EXHAUSTED`:

1. Wait until UTC midnight (03:00 МСК) for quota reset
2. Or add billing to the GCP project to remove the daily cap
3. `MAX_PARALLEL_INSERT=1` and `MAX_ASYNC=2` are already set in `.env` to serialize requests

After quota resets, re-run: `ssh deploy@<server> '/opt/lightrag/scripts/lightrag-ingest.sh'`

---

## Security Notes

- LightRAG port `8020` is bound to `127.0.0.1` only — not reachable from internet
- UFW allows only 22/80/443 — even if container bound on 0.0.0.0:9621, UFW blocks it externally
- Caddy does NOT proxy LightRAG (no public API endpoint)
- `.env` contains API keys — never commit, keep in `LOCAL_ACCESS.md`
- Obsidian vault mounted read-only in the container
- Workspace files mounted read-only in the container

---

## Files to Back Up

- `/opt/lightrag/.env` (Gemini API key)
- `/opt/lightrag/data/` (graph + vector state — rebuild requires re-ingestion)
- `/opt/lightrag/docker-compose.override.yml`
- `/opt/lightrag/scripts/lightrag-ingest.sh`
