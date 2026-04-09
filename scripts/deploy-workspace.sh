#!/usr/bin/env bash
# deploy-workspace.sh
# Deploys workspace template files to the OpenClaw server.
#
# Usage:
#   OPENCLAW_HOST=deploy@<server-host> ./scripts/deploy-workspace.sh
#
# The server host is defined in LOCAL_ACCESS.md (not committed to git).
# SSH key: ~/.ssh/id_rsa (adjust SSH_KEY below if different)
#
# What it does:
#   - Syncs all *.md files from ./workspace/ to /opt/openclaw/workspace/ on the server
#   - Skips the memory/ subdirectory (daily logs are managed by the bot itself)
#   - Does NOT delete existing files on the server (safe incremental deploy)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="${SCRIPT_DIR}/../workspace"
REMOTE_DIR="/opt/openclaw/workspace"
SSH_KEY="${SSH_KEY:-${HOME}/.ssh/id_rsa}"

if [[ -z "${OPENCLAW_HOST:-}" ]]; then
  echo "Error: OPENCLAW_HOST is not set."
  echo "Usage: OPENCLAW_HOST=deploy@<server-host> $0"
  exit 1
fi

echo "Deploying workspace files to ${OPENCLAW_HOST}:${REMOTE_DIR} ..."

rsync -avz \
  --include="*.md" \
  --exclude="memory/" \
  --exclude="*" \
  -e "ssh -i ${SSH_KEY}" \
  "${WORKSPACE_DIR}/" \
  "${OPENCLAW_HOST}:${REMOTE_DIR}/"

echo ""
echo "Done. Workspace files deployed."
echo ""
echo "Next step: open OpenClaw web UI and start a new session."
echo "Test: ask the bot 'Кто ты и что ты знаешь обо мне?'"
