#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_CRON_AGENT="${OPENCLAW_CRON_AGENT:-main}"
OPENCLAW_CRON_TZ="${OPENCLAW_CRON_TZ:-Europe/Moscow}"
EMAIL_ENV_FILE="${EMAIL_ENV_FILE:-/opt/agentmail-email/email.env}"
EMAIL_BRIDGE_URL="${EMAIL_BRIDGE_URL:-http://agentmail-email-bridge:8092/trigger}"
EMAIL_CRON_TIMEOUT_SECONDS="${EMAIL_CRON_TIMEOUT_SECONDS:-300}"
declare -a OPENCLAW_CMD=()

EMAIL_BRIDGE_TOKEN="${EMAIL_BRIDGE_TOKEN:-}"
if [[ -z "$EMAIL_BRIDGE_TOKEN" && -r "$EMAIL_ENV_FILE" ]]; then
  EMAIL_BRIDGE_TOKEN="$(awk -F= '/^EMAIL_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$EMAIL_ENV_FILE" | tail -n1)"
fi
if [[ -z "$EMAIL_BRIDGE_TOKEN" && -f "$EMAIL_ENV_FILE" ]] && command -v sudo >/dev/null 2>&1; then
  EMAIL_BRIDGE_TOKEN="$(sudo awk -F= '/^EMAIL_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$EMAIL_ENV_FILE" | tail -n1)"
fi
if [[ -z "$EMAIL_BRIDGE_TOKEN" ]]; then
  echo "EMAIL_BRIDGE_TOKEN is missing. Set it in $EMAIL_ENV_FILE or the environment." >&2
  exit 1
fi

if [[ -n "${OPENCLAW_BIN:-}" ]]; then
  OPENCLAW_CMD=("$OPENCLAW_BIN")
elif command -v openclaw >/dev/null 2>&1; then
  OPENCLAW_CMD=(openclaw)
else
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx 'openclaw-openclaw-gateway-1'; then
    OPENCLAW_CMD=(docker exec openclaw-openclaw-gateway-1 /usr/local/bin/openclaw)
  else
    echo "openclaw CLI not found in PATH and gateway container fallback is unavailable." >&2
    exit 1
  fi
fi

run_openclaw() {
  "${OPENCLAW_CMD[@]}" "$@"
}

read_existing_job_ids() {
  local cron_list
  cron_list="$(run_openclaw cron list 2>/dev/null)"

  CRON_LIST="$cron_list" python3 - <<'PY'
import json
import os
import re

MANAGED_PREFIX = "AgentMail Inbox"
uuid_re = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I
)

raw = os.environ.get("CRON_LIST", "").strip()
if not raw:
    raise SystemExit(0)

try:
    data = json.loads(raw)
    jobs = data.get("jobs", []) if isinstance(data, dict) else data if isinstance(data, list) else []
    for job in jobs:
        if isinstance(job, dict) and str(job.get("name", "")).startswith(MANAGED_PREFIX):
            jid = job.get("jobId") or job.get("id")
            if jid:
                print(jid)
    raise SystemExit(0)
except (json.JSONDecodeError, KeyError):
    pass

for line in raw.splitlines():
    if MANAGED_PREFIX in line:
        m = uuid_re.search(line)
        if m:
            print(m.group(0))
PY
}

remove_old_jobs() {
  while IFS= read -r job_id; do
    [[ -n "$job_id" ]] || continue
    run_openclaw cron remove "$job_id" >/dev/null
  done < <(read_existing_job_ids)
}

add_job() {
  local name="$1"
  local cron_expr="$2"
  local job_type="$3"
  local digest_type="${4:-}"
  local description="$5"
  local payload
  payload="{\"job_type\": ${job_type@Q}"
  if [[ -n "$digest_type" ]]; then
    payload+=", \"digest_type\": ${digest_type@Q}"
  fi
  payload+="}"

  local message
  printf -v message '%s' "/compact Trigger the AgentMail inbox-email bridge and report only the enqueue result.

Rules:
- Work only on this task.
- Use exec for exactly one command.
- Do not modify files.
- Do not ask clarifying questions.
- Keep the reply to 2-4 factual lines.

Command:
python3 - <<'PY'
import json
import urllib.request

url = ${EMAIL_BRIDGE_URL@Q}
token = ${EMAIL_BRIDGE_TOKEN@Q}
payload = ${payload}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode(\"utf-8\"),
    headers={
        \"Authorization\": f\"Bearer {token}\",
        \"Content-Type\": \"application/json\",
    },
    method=\"POST\",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    print(resp.read().decode(\"utf-8\"))
PY

Report:
- job type
- digest type if present
- bridge HTTP result
- whether the job was enqueued"

  run_openclaw cron add \
    --name "$name" \
    --description "$description" \
    --cron "$cron_expr" \
    --tz "$OPENCLAW_CRON_TZ" \
    --exact \
    --session isolated \
    --agent "$OPENCLAW_CRON_AGENT" \
    --tools exec,read \
    --light-context \
    --timeout-seconds "$EMAIL_CRON_TIMEOUT_SECONDS" \
    --message "$message" \
    --no-deliver
}

remove_old_jobs

add_job "AgentMail Inbox · Poll every 5m" "*/5 * * * *" "poll" "" "Near-real-time inbox poll"
add_job "AgentMail Inbox · 08:00 Morning brief" "0 8 * * *" "digest" "morning" "Morning inbox digest"
add_job "AgentMail Inbox · 13:00 Regular digest" "0 13 * * *" "digest" "interval" "Midday inbox digest"
add_job "AgentMail Inbox · 16:00 Regular digest" "0 16 * * *" "digest" "interval" "Afternoon inbox digest"
add_job "AgentMail Inbox · 20:00 Evening editorial" "0 20 * * *" "digest" "editorial" "Evening inbox digest"

echo "OpenClaw cron jobs synced for AgentMail Inbox."
