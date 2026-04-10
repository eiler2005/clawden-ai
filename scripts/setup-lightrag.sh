#!/usr/bin/env bash
# setup-lightrag.sh
# Sets up LightRAG knowledge graph service on the OpenClaw server.
#
# Prerequisites:
#   - OPENCLAW_HOST=deploy@<server-host> must be set
#   - LIGHTRAG_ENV_FILE must point to a local .env file with real API keys
#     (copy scripts/lightrag.env.template → scripts/lightrag.env, fill in keys)
#
# Usage:
#   OPENCLAW_HOST=deploy@<server-host> \
#   LIGHTRAG_ENV_FILE=scripts/lightrag.env \
#   ./scripts/setup-lightrag.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"
SSH="ssh -i ${SSH_KEY}"
SCP="scp -i ${SSH_KEY}"

if [[ -z "${OPENCLAW_HOST:-}" ]]; then
  echo "Error: OPENCLAW_HOST is not set."
  echo "Usage: OPENCLAW_HOST=deploy@<server-host> LIGHTRAG_ENV_FILE=scripts/lightrag.env $0"
  exit 1
fi

LIGHTRAG_ENV_FILE="${LIGHTRAG_ENV_FILE:-${SCRIPT_DIR}/lightrag.env}"
if [[ ! -f "${LIGHTRAG_ENV_FILE}" ]]; then
  echo "Error: env file not found: ${LIGHTRAG_ENV_FILE}"
  echo "Copy scripts/lightrag.env.template to scripts/lightrag.env and fill in API keys."
  exit 1
fi

echo "=== Setting up LightRAG on ${OPENCLAW_HOST} ==="

# 1. Create directory structure on server
echo ""
echo "[1/6] Creating /opt/lightrag directory structure..."
${SSH} "${OPENCLAW_HOST}" '
  sudo mkdir -p /opt/lightrag/data
  sudo mkdir -p /opt/lightrag/scripts
  sudo mkdir -p /opt/obsidian-vault
  sudo chown -R deploy:deploy /opt/lightrag /opt/obsidian-vault
  echo "  /opt/lightrag/       — ok"
  echo "  /opt/lightrag/data/  — ok"
  echo "  /opt/obsidian-vault/ — ok"
'

# 2. Clone LightRAG repo (or update if exists)
echo ""
echo "[2/6] Cloning/updating LightRAG from GitHub..."
${SSH} "${OPENCLAW_HOST}" '
  if [ -d /opt/lightrag/.git ]; then
    cd /opt/lightrag && git pull --ff-only
    echo "  LightRAG updated"
  else
    # Clone into temp, move files (dont overwrite data/)
    git clone --depth=1 https://github.com/hkuds/lightrag /tmp/lightrag-clone
    cp -n /tmp/lightrag-clone/docker-compose.yml /opt/lightrag/docker-compose.yml 2>/dev/null || true
    cp -n /tmp/lightrag-clone/Dockerfile.lite /opt/lightrag/Dockerfile.lite 2>/dev/null || true
    cp -rn /tmp/lightrag-clone/lightrag /opt/lightrag/lightrag 2>/dev/null || true
    cp -rn /tmp/lightrag-clone/lightrag_webui /opt/lightrag/lightrag_webui 2>/dev/null || true
    cp -n /tmp/lightrag-clone/pyproject.toml /opt/lightrag/pyproject.toml 2>/dev/null || true
    cp -n /tmp/lightrag-clone/README.md /opt/lightrag/README-upstream.md 2>/dev/null || true
    rm -rf /tmp/lightrag-clone
    echo "  LightRAG installed"
  fi
'

# 3. Upload our docker-compose override and .env
echo ""
echo "[3/6] Uploading docker-compose.override.yml and .env..."

# Write docker-compose override that mounts our volumes and sets port
${SSH} "${OPENCLAW_HOST}" 'cat > /opt/lightrag/docker-compose.override.yml' << 'COMPOSE_EOF'
services:
  lightrag:
    image: lightrag-local:latest
    networks:
      default:
      openclaw_default:
        aliases:
          - lightrag
    ports: !override
      - "127.0.0.1:8020:9621"
    volumes:
      - ./data:/app/data
      - /opt/obsidian-vault:/app/data/inputs/obsidian:ro
      - /opt/openclaw/workspace:/app/data/inputs/workspace:ro
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9621/health', timeout=5).read()"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 90s

networks:
  openclaw_default:
    external: true
COMPOSE_EOF

# Upload env file
${SCP} "${LIGHTRAG_ENV_FILE}" "${OPENCLAW_HOST}:/opt/lightrag/.env"
echo "  docker-compose.override.yml — uploaded"
echo "  .env — uploaded"

# 4. Upload ingestion script
echo ""
echo "[4/6] Uploading lightrag-ingest.sh..."
${SSH} "${OPENCLAW_HOST}" 'cat > /opt/lightrag/scripts/lightrag-ingest.sh' << 'INGEST_EOF'
#!/bin/bash
set -euo pipefail
API="http://127.0.0.1:8020"
LOG_FILE="/var/log/lightrag-ingest.log"
UPLOADED=0
FAILED=0

echo "[$(date '+%Y-%m-%d %H:%M:%S')] LightRAG ingest started" | tee -a "${LOG_FILE}"

# Check LightRAG is running
if ! curl -sf "${API}/health" > /dev/null 2>&1; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: LightRAG not reachable" | tee -a "${LOG_FILE}"
  exit 1
fi

upload_dir() {
  local DIR="$1"
  while IFS= read -r -d "" file; do
    curl -sf -X POST "${API}/documents/upload" \
      -F "file=@${file}" > /dev/null 2>&1 && UPLOADED=$((UPLOADED+1)) || FAILED=$((FAILED+1))
  done < <(find "${DIR}" -name "*.md" -not -path "*/archive/*" -print0)
}

upload_dir "/opt/openclaw/workspace"
upload_dir "/opt/obsidian-vault"

if [ "${FAILED}" -eq 0 ]; then
  curl -sf -X POST "${API}/documents/reprocess_failed" > /dev/null 2>&1 || true
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done: ${UPLOADED} uploaded, ${FAILED} failed" | tee -a "${LOG_FILE}"
INGEST_EOF

${SSH} "${OPENCLAW_HOST}" 'chmod +x /opt/lightrag/scripts/lightrag-ingest.sh'
echo "  lightrag-ingest.sh — uploaded"

# 5. Build and start LightRAG
echo ""
echo "[5/6] Building and starting LightRAG (from Dockerfile.lite)..."
${SSH} "${OPENCLAW_HOST}" '
  cd /opt/lightrag
  docker build -f Dockerfile.lite -t lightrag-local:latest . 2>&1 | tail -10
  echo "  Image built: lightrag-local:latest"
  docker compose -f docker-compose.yml -f docker-compose.override.yml up -d
  echo "  LightRAG container started"
  sleep 5
  # Quick health check
  if curl -sf http://127.0.0.1:8020/health > /dev/null 2>&1; then
    echo "  Health: OK"
  else
    echo "  Health: starting (may take 60-90s for first boot)"
  fi
'

# 6. Set up cron jobs
echo ""
echo "[6/6] Setting up cron jobs (ingestion every 30 min)..."
${SSH} "${OPENCLAW_HOST}" '
  # Add cron if not already present
  (crontab -l 2>/dev/null | grep -v lightrag-ingest; \
   echo "*/30 * * * * /opt/lightrag/scripts/lightrag-ingest.sh >> /var/log/lightrag-ingest.log 2>&1") | crontab -
  echo "  Cron installed: lightrag-ingest every 30 min"
'

echo ""
echo "=== LightRAG setup complete ==="
echo ""
echo "Verify:"
echo "  ssh deploy@<server> 'curl -sf http://127.0.0.1:8020/health | python3 -m json.tool'"
echo ""
echo "Trigger initial index:"
echo "  ssh deploy@<server> '/opt/lightrag/scripts/lightrag-ingest.sh'"
