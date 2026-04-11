#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
LOCAL_ENV="$ROOT_DIR/secrets/agentmail-email/email.env"
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
for key in AGENTMAIL_API_KEY AGENTMAIL_INBOX_REF EMAIL_DIGEST_SUPERGROUP_ID EMAIL_DIGEST_TOPIC_ID; do
  if ! grep -Eq "^${key}=.+" "$LOCAL_ENV"; then
    missing+=("$key")
  fi
done

if (( ${#missing[@]} )); then
  printf 'Missing required values in %s: %s\n' "$LOCAL_ENV" "${missing[*]}" >&2
  exit 1
fi

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  sudo mkdir -p /opt/agentmail-email
'

rsync -avz --delete --exclude config.json --exclude email.env \
  -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$ROOT_DIR/artifacts/agentmail-email/" \
  "$OPENCLAW_HOST":/opt/agentmail-email/

rsync -avz -e "$RSYNC_SSH" --rsync-path="sudo rsync" \
  "$LOCAL_ENV" \
  "$OPENCLAW_HOST":/opt/agentmail-email/email.env

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" '
  set -euo pipefail
  cd /opt/agentmail-email

  if ! sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" email.env; then
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
      sudo sed -i "/^TELEGRAM_BOT_TOKEN=/d" email.env
      printf "TELEGRAM_BOT_TOKEN=%s\n" "$token" | sudo tee -a email.env >/dev/null
    fi
  fi

  if ! sudo grep -Eq "^OPENCLAW_EXEC_CONTAINER=.+" email.env; then
    printf "OPENCLAW_EXEC_CONTAINER=openclaw-openclaw-gateway-1\n" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^OPENCLAW_AGENT_ID=.+" email.env; then
    printf "OPENCLAW_AGENT_ID=main\n" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^OPENCLAW_AGENT_FALLBACK_ID=.+" email.env; then
    printf "OPENCLAW_AGENT_FALLBACK_ID=main\n" | sudo tee -a email.env >/dev/null
  fi

  if ! sudo grep -Eq "^EMAIL_BRIDGE_TOKEN=.+" email.env; then
    token="$(python3 - <<'"'"'PY'"'"'
import secrets
print(secrets.token_hex(24))
PY
)"
    printf "EMAIL_BRIDGE_TOKEN=%s\n" "$token" | sudo tee -a email.env >/dev/null
  fi

  sudo grep -Eq "^TELEGRAM_BOT_TOKEN=.+" email.env || {
    echo "Missing TELEGRAM_BOT_TOKEN in email.env and /opt/openclaw/.env" >&2
    exit 1
  }

  agentmail_key="$(sudo awk -F= "/^AGENTMAIL_API_KEY=/{print substr(\$0, length(\$1)+2)}" email.env | tail -n1)"
  if [ -n "$agentmail_key" ] && sudo test -f /opt/openclaw/.env; then
    sudo sed -i "/^AGENTMAIL_API_KEY=/d" /opt/openclaw/.env
    printf "AGENTMAIL_API_KEY=%s\n" "$agentmail_key" | sudo tee -a /opt/openclaw/.env >/dev/null
  fi

  sudo python3 - <<'"'"'PY'"'"'
from pathlib import Path

path = Path("/opt/openclaw/docker-compose.yml")
text = path.read_text()

needle_gateway = "      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN}\n"
replace_gateway = needle_gateway + "      AGENTMAIL_API_KEY: ${AGENTMAIL_API_KEY}\n"
if "      AGENTMAIL_API_KEY: ${AGENTMAIL_API_KEY}\n" not in text:
    text = text.replace(needle_gateway, replace_gateway, 1)

needle_cli = "      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN}\n      BROWSER: echo\n"
replace_cli = "      OPENCLAW_GATEWAY_TOKEN: ${OPENCLAW_GATEWAY_TOKEN}\n      AGENTMAIL_API_KEY: ${AGENTMAIL_API_KEY}\n      BROWSER: echo\n"
if replace_cli not in text:
    text = text.replace(needle_cli, replace_cli, 1)

path.write_text(text)
PY

  sudo python3 - <<'"'"'PY'"'"'
import json
from pathlib import Path

path = Path("/opt/openclaw/config/openclaw.json")
data = json.loads(path.read_text())
mcp = data.setdefault("mcp", {})
servers = mcp.setdefault("servers", {})
servers["agentmail"] = {
    "command": "npx",
    "args": [
        "-y",
        "agentmail-mcp",
        "--tools",
        "list_inboxes,list_threads,get_thread,update_message",
    ],
    "env": {
        "AGENTMAIL_API_KEY": "${AGENTMAIL_API_KEY}",
    },
}
path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
PY

  sudo chmod 600 email.env
  sudo chmod +x /opt/agentmail-email/entrypoint.sh
  sudo chmod +x /opt/agentmail-email/sync-openclaw-cron-jobs.sh
  sudo test -f config.json || sudo cp config.example.json config.json
  sudo rm -rf /opt/agentmail-email/openclaw-config 2>/dev/null || true

  cd /opt/openclaw
  sudo docker compose up -d openclaw-gateway

  ready=0
  for _ in $(seq 1 30); do
    if sudo docker exec openclaw-openclaw-gateway-1 /usr/local/bin/openclaw --version >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "OpenClaw gateway did not become ready in time." >&2
    exit 1
  fi

  cd /opt/agentmail-email
  sudo docker compose build
  sudo docker compose down 2>/dev/null || true
  sudo docker compose up -d agentmail-email-bridge
  sudo docker image prune -f >/dev/null 2>&1 || true
  sudo docker builder prune -f >/dev/null 2>&1 || true
  /opt/agentmail-email/sync-openclaw-cron-jobs.sh
'

cat <<'EOF'
AgentMail inbox-email pipeline deployed.

Scheduled:
  - poll every 5 minutes
  - digests at 08:00 / 13:00 / 16:00 / 20:00 MSK

Useful commands:
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'cd /opt/agentmail-email && sudo docker compose logs --tail=100 agentmail-email-bridge'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'curl -s http://127.0.0.1:8092/health && echo && curl -s http://127.0.0.1:8092/status'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:jobs:email'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec integration-bus-redis redis-cli XLEN ingest:events:email'
  ssh -i "$SSH_KEY" "$OPENCLAW_HOST" 'docker exec openclaw-openclaw-gateway-1 /usr/local/bin/openclaw cron list'
EOF
