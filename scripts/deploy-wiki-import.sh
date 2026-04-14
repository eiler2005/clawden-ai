#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-15}"
  -o ConnectionAttempts=1
)
RSYNC_SSH="ssh -i $SSH_KEY -o BatchMode=yes -o ConnectTimeout=${SSH_CONNECT_TIMEOUT:-15} -o ConnectionAttempts=1"

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: export OPENCLAW_HOST=deploy@<server-host>" >&2
  exit 1
fi

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo mkdir -p /opt/wiki-import
'

rsync -avz --delete \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'tests/' \
  -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$ROOT_DIR/artifacts/wiki-import/" \
  "$OPENCLAW_HOST":/opt/wiki-import/

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  sudo mkdir -p /opt/wiki-import
  cd /opt/wiki-import

  if ! sudo test -f wiki-import.env; then
    token="$(python3 - <<'"'"'PY'"'"'
import secrets
print(secrets.token_hex(24))
PY
)"
    sudo tee wiki-import.env >/dev/null <<EOF
WIKI_IMPORT_PORT=8095
WIKI_IMPORT_TOKEN=${token}
WIKI_IMPORT_OBSIDIAN_ROOT=/app/obsidian
WIKI_IMPORT_HOST_OPT_ROOT=/host-opt
WIKI_IMPORT_STATE_ROOT=/app/state
EOF
  fi

  sudo chmod 600 wiki-import.env
  sudo chmod +x /opt/wiki-import/entrypoint.sh
  sudo docker compose build
  sudo docker compose down 2>/dev/null || true
  sudo docker compose up -d wiki-import

  ready=0
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8095/health >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "wiki-import did not become healthy in time." >&2
    exit 1
  fi
'

cat <<'EOF'
wiki-import deployed.

Useful commands:
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'cd /opt/wiki-import && sudo docker compose logs --tail=100 wiki-import'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'grep ^WIKI_IMPORT_TOKEN= /opt/wiki-import/wiki-import.env'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'curl -s http://127.0.0.1:8095/health && echo'
EOF
