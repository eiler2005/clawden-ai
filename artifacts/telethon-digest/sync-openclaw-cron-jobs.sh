#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_CRON_AGENT="${OPENCLAW_CRON_AGENT:-main}"
OPENCLAW_CRON_TZ="${OPENCLAW_CRON_TZ:-Europe/Moscow}"
TELETHON_ENV_FILE="${TELETHON_ENV_FILE:-/opt/telethon-digest/telethon.env}"
DIGEST_CRON_BRIDGE_URL="${DIGEST_CRON_BRIDGE_URL:-http://telethon-digest-cron-bridge:8091/trigger}"
DIGEST_CRON_TIMEOUT_SECONDS="${DIGEST_CRON_TIMEOUT_SECONDS:-1800}"
declare -a OPENCLAW_CMD=()

DIGEST_CRON_BRIDGE_TOKEN="${DIGEST_CRON_BRIDGE_TOKEN:-}"
if [[ -z "$DIGEST_CRON_BRIDGE_TOKEN" && -r "$TELETHON_ENV_FILE" ]]; then
  DIGEST_CRON_BRIDGE_TOKEN="$(awk -F= '/^DIGEST_CRON_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$TELETHON_ENV_FILE" | tail -n1)"
fi
if [[ -z "$DIGEST_CRON_BRIDGE_TOKEN" && -f "$TELETHON_ENV_FILE" ]] && command -v sudo >/dev/null 2>&1; then
  DIGEST_CRON_BRIDGE_TOKEN="$(sudo awk -F= '/^DIGEST_CRON_BRIDGE_TOKEN=/{print substr($0, length($1)+2)}' "$TELETHON_ENV_FILE" | tail -n1)"
fi
if [[ -z "$DIGEST_CRON_BRIDGE_TOKEN" ]]; then
  echo "DIGEST_CRON_BRIDGE_TOKEN is missing. Set it in $TELETHON_ENV_FILE or the environment." >&2
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

  # Pass via env var: piping into a heredoc-fed python3 causes heredoc to win over pipe
  CRON_LIST="$cron_list" python3 - <<'PY'
import os
import json
import re

# Prefix shared by all managed jobs — works even when names are truncated in text output
MANAGED_PREFIX = "Telethon Digest"

uuid_re = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I
)

raw = os.environ.get("CRON_LIST", "").strip()
if not raw:
    raise SystemExit(0)

# Try JSON parse first (if openclaw cron list returns JSON)
try:
    data = json.loads(raw)
    jobs = (
        data.get("jobs", []) if isinstance(data, dict)
        else data if isinstance(data, list)
        else []
    )
    for job in jobs:
        if isinstance(job, dict) and str(job.get("name", "")).startswith(MANAGED_PREFIX):
            jid = job.get("jobId") or job.get("id")
            if jid:
                print(jid)
    raise SystemExit(0)
except (json.JSONDecodeError, KeyError):
    pass

# Fallback: text table — match any line containing the managed prefix, extract leading UUID
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
  local digest_type="$3"
  local description="$4"
  local message

  printf -v message '%s' "/compact Trigger the Telegram digest bridge and report the outcome in 3-5 plain lines.

Rules:
- Work only on this task.
- Use exec for exactly one command.
- Do not modify files.
- Do not ask clarifying questions.
- Keep the reply short and factual.

Command:
python3 - <<'PY'
import json
import urllib.request

url = ${DIGEST_CRON_BRIDGE_URL@Q}
token = ${DIGEST_CRON_BRIDGE_TOKEN@Q}
payload = {\"digest_type\": ${digest_type@Q}}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode(\"utf-8\"),
    headers={
        \"Authorization\": f\"Bearer {token}\",
        \"Content-Type\": \"application/json\",
    },
    method=\"POST\",
)
with urllib.request.urlopen(req, timeout=3600) as resp:
    print(resp.read().decode(\"utf-8\"))
PY

Report:
- digest type
- bridge HTTP result
- whether Telegram posting appears successful from the bridge response
- first actionable error if the run failed

If the bridge returns 409 digest_already_running, report that another digest is still in progress instead of calling it a hang."

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
    --timeout-seconds "$DIGEST_CRON_TIMEOUT_SECONDS" \
    --message "$message" \
    --no-deliver
}

remove_old_jobs

add_job "Telethon Digest · 08:00 Morning brief" "0 8 * * *" "morning" "Morning brief for Telegram Digest"
add_job "Telethon Digest · 11:00 Regular digest" "0 11 * * *" "interval" "Regular interval digest"
add_job "Telethon Digest · 14:00 Regular digest" "0 14 * * *" "interval" "Regular interval digest"
add_job "Telethon Digest · 17:00 Regular digest" "0 17 * * *" "interval" "Regular interval digest"
add_job "Telethon Digest · 21:00 Evening editorial" "0 21 * * *" "editorial" "Evening editorial digest"

echo "OpenClaw cron jobs synced for Telethon Digest."
