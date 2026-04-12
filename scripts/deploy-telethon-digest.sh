#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
LOCAL_ENV="$ROOT_DIR/secrets/telethon-digest/telethon.env"
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

if [[ ! -f "$LOCAL_ENV" ]]; then
  echo "Missing $LOCAL_ENV" >&2
  exit 1
fi

missing=()
for key in TELEGRAM_API_ID TELEGRAM_API_HASH TELEGRAM_PHONE DIGEST_SUPERGROUP_ID DIGEST_TOPIC_ID; do
  if ! grep -Eq "^${key}=.+" "$LOCAL_ENV"; then
    missing+=("$key")
  fi
done

if (( ${#missing[@]} )); then
  printf 'Missing required values in %s: %s\n' "$LOCAL_ENV" "${missing[*]}" >&2
  exit 1
fi

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo mkdir -p /opt/telethon-digest
  sudo mkdir -p "/opt/obsidian-vault/Telegram Digest/Derived" "/opt/obsidian-vault/Telegram Digest/Curated"
  sudo chown -R deploy:deploy "/opt/obsidian-vault/Telegram Digest"
'

rsync -avz --delete --exclude config.json --exclude telethon.env \
  -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$ROOT_DIR/artifacts/telethon-digest/" \
  "$OPENCLAW_HOST":/opt/telethon-digest/

rsync -avz -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_ENV" \
  "$OPENCLAW_HOST":/opt/telethon-digest/telethon.env

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/telethon-digest
  if ! sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" telethon.env; then
    token=""
    if sudo test -f /opt/openclaw/.env; then
      token="$(sudo awk -F= "/^(TELEGRAM_BOT_TOKEN|OPENCLAW_TELEGRAM_BOT_TOKEN)=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    fi
    if [ -z "$token" ] && sudo test -f /opt/openclaw/config/openclaw.json; then
      token="$(sudo python3 - <<'"'"'PY'"'"'
import json
try:
    data = json.load(open("/opt/openclaw/config/openclaw.json"))
    print(data.get("channels", {}).get("telegram", {}).get("botToken", ""))
except Exception:
    print("")
PY
)"
    fi
    if [ -n "$token" ]; then
      sudo sed -i "/^TELEGRAM_BOT_TOKEN=/d" telethon.env
      printf "TELEGRAM_BOT_TOKEN=%s\n" "$token" | sudo tee -a telethon.env >/dev/null
    fi
  fi
  if ! sudo grep -Eq "^OMNIROUTE_API_KEY=.+" telethon.env && sudo test -f /opt/openclaw/.env; then
    key="$(sudo awk -F= "/^OMNIROUTE_API_KEY=/{print substr(\$0, length(\$1)+2)}" /opt/openclaw/.env | tail -n1)"
    if [ -n "$key" ]; then
      sudo sed -i "/^OMNIROUTE_API_KEY=/d" telethon.env
      printf "OMNIROUTE_API_KEY=%s\n" "$key" | sudo tee -a telethon.env >/dev/null
    fi
  fi
  sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" telethon.env || {
    echo "Missing TELEGRAM_BOT_TOKEN in telethon.env and /opt/openclaw/.env" >&2
    exit 1
  }
  if ! sudo grep -Eq "^DIGEST_CRON_BRIDGE_TOKEN=.+" telethon.env; then
    token="$(python3 - <<'"'"'PY'"'"'
import secrets
print(secrets.token_hex(24))
PY
)"
    printf "DIGEST_CRON_BRIDGE_TOKEN=%s\n" "$token" | sudo tee -a telethon.env >/dev/null
  fi
  sudo chmod 600 telethon.env
  sudo chmod +x /opt/telethon-digest/cron-digest.sh
  sudo chmod +x /opt/telethon-digest/sync-openclaw-cron-jobs.sh
  sudo test -f config.json || sudo cp config.example.json config.json
  sudo docker compose build

  # Stop old APScheduler daemon; digest runs are now triggered by OpenClaw Cron Jobs.
  sudo docker compose down 2>/dev/null || true
  sudo docker compose up -d telethon-digest-cron-bridge

  # Remove legacy system cron entry if present.
  sudo rm -f /etc/cron.d/telethon-digest

  # Register digest jobs in the OpenClaw gateway scheduler so they appear in Control UI.
  /opt/telethon-digest/sync-openclaw-cron-jobs.sh
'

cat <<'EOF'
Telethon Digest deployed. OpenClaw Cron Jobs are now the scheduler.

Scheduled: 08:00, 11:00, 14:00, 17:00, 21:00 MSK via OpenClaw Control -> Cron Jobs

Useful commands:
  # Run digest immediately
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo /opt/telethon-digest/cron-digest.sh'

  # Watch digest log
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'sudo tail -f /var/log/telethon-digest-cron.log'

  # Inspect jobs in OpenClaw
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec openclaw-openclaw-gateway-1 /usr/local/bin/openclaw cron list'

  # Re-sync channels
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'cd /opt/telethon-digest && sudo docker compose run --rm telethon-digest python sync_channels.py'
EOF
