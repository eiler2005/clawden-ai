#!/usr/bin/env bash
# OpenClaw Cron Jobs wrapper for Telethon Digest.
# Deploy to: /opt/telethon-digest/cron-digest.sh (chmod +x)
# Called by OpenClaw Cron Jobs via an isolated agent run.
set -euo pipefail

cd /opt/telethon-digest
echo "=== $(date '+%Y-%m-%d %H:%M:%S') digest start ==="
docker compose run --rm telethon-digest python digest_worker.py --now
echo "=== $(date '+%Y-%m-%d %H:%M:%S') digest done ==="
