#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_CRON_AGENT="${OPENCLAW_CRON_AGENT:-main}"
OPENCLAW_CRON_TZ="${OPENCLAW_CRON_TZ:-Europe/Moscow}"
OPENCLAW_CRON_STORE="${OPENCLAW_CRON_STORE:-}"
EMAIL_ENV_FILE="${EMAIL_ENV_FILE:-/opt/agentmail-email/email.env}"
EMAIL_BRIDGE_URL="${EMAIL_BRIDGE_URL:-http://agentmail-email-bridge:8092/trigger}"
EMAIL_CRON_TIMEOUT_SECONDS="${EMAIL_CRON_TIMEOUT_SECONDS:-300}"

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

resolve_cron_store() {
  if [[ -n "$OPENCLAW_CRON_STORE" ]]; then
    echo "$OPENCLAW_CRON_STORE"
    return 0
  fi

  local candidate
  for candidate in \
    /opt/openclaw/config/cron/jobs.json \
    /home/deploy/.openclaw/cron/jobs.json
  do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
    if command -v sudo >/dev/null 2>&1 && sudo test -f "$candidate"; then
      echo "$candidate"
      return 0
    fi
  done

  echo "OpenClaw cron store not found. Set OPENCLAW_CRON_STORE explicitly." >&2
  exit 1
}

restart_gateway_if_present() {
  local gateway_name="openclaw-openclaw-gateway-1"
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "$gateway_name"; then
    docker restart "$gateway_name" >/dev/null
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo docker ps --format '{{.Names}}' | grep -qx "$gateway_name"; then
    sudo docker restart "$gateway_name" >/dev/null
  fi
}

CRON_STORE_PATH="$(resolve_cron_store)"

sudo env \
  CRON_STORE_PATH="$CRON_STORE_PATH" \
  OPENCLAW_CRON_AGENT="$OPENCLAW_CRON_AGENT" \
  OPENCLAW_CRON_TZ="$OPENCLAW_CRON_TZ" \
  EMAIL_CRON_TIMEOUT_SECONDS="$EMAIL_CRON_TIMEOUT_SECONDS" \
  EMAIL_BRIDGE_URL="$EMAIL_BRIDGE_URL" \
  EMAIL_BRIDGE_TOKEN="$EMAIL_BRIDGE_TOKEN" \
  python3 - <<'PYCODE_AGENTMAIL_SYNC'
import json
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

managed_prefix = "AgentMail Inbox"
store_path = Path(os.environ["CRON_STORE_PATH"]).expanduser()
agent_id = os.environ["OPENCLAW_CRON_AGENT"]
tz_name = os.environ["OPENCLAW_CRON_TZ"]
bridge_url = os.environ["EMAIL_BRIDGE_URL"]
bridge_token = os.environ["EMAIL_BRIDGE_TOKEN"]
timeout_seconds = int(os.environ["EMAIL_CRON_TIMEOUT_SECONDS"])

if not store_path.exists():
    raise SystemExit(f"Cron store not found: {store_path}")

raw = json.loads(store_path.read_text())
jobs = raw.get("jobs", raw if isinstance(raw, list) else [])

existing_by_name = {}
for job in jobs:
    name = str(job.get("name", ""))
    if name.startswith(managed_prefix):
        existing_by_name[name] = job
        if job.get("agentId"):
            agent_id = job["agentId"]

backup_path = store_path.with_name(store_path.name + ".bak-" + str(int(time.time())))
backup_path.write_text(store_path.read_text())


def next_run_ms(expr: str) -> int:
    now = datetime.now(ZoneInfo(tz_name))
    minute_s, hour_s, *_ = expr.split()
    if minute_s.startswith("*/"):
        step = int(minute_s[2:])
        candidate = now.replace(second=0, microsecond=0)
        remainder = candidate.minute % step
        candidate += timedelta(minutes=(step - remainder) if remainder else step)
        return int(candidate.timestamp() * 1000)

    hour = int(hour_s)
    minute = int(minute_s)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return int(candidate.timestamp() * 1000)


def build_message(job_type: str, digest_type: str | None) -> str:
    payload = {"job_type": job_type}
    if digest_type:
        payload["digest_type"] = digest_type
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""/compact Trigger the AgentMail inbox-email bridge and report only the enqueue result.

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

url = {bridge_url!r}
token = {bridge_token!r}
payload = {payload_json}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={{
        "Authorization": f"Bearer {{token}}",
        "Content-Type": "application/json",
    }},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    print(resp.read().decode("utf-8"))
PY

Report:
- job type
- digest type if present
- bridge HTTP result
- whether the job was enqueued"""


specs = [
    ("AgentMail Inbox · 08:00 Morning brief", "Morning inbox digest", "0 8 * * *", "digest", "morning", None),
    ("AgentMail Inbox · 13:00 Regular digest", "Midday inbox digest", "0 13 * * *", "digest", "interval", None),
    ("AgentMail Inbox · 16:00 Regular digest", "Afternoon inbox digest", "0 16 * * *", "digest", "interval", None),
    ("AgentMail Inbox · 20:00 Evening editorial", "Evening inbox digest", "0 20 * * *", "digest", "editorial", None),
]

filtered_jobs = [job for job in jobs if not str(job.get("name", "")).startswith(managed_prefix)]
now_ms = int(time.time() * 1000)
new_jobs = []
for name, description, expr, job_type, digest_type, model in specs:
    existing = existing_by_name.get(name, {})
    state = dict(existing.get("state", {})) if isinstance(existing, dict) else {}
    state["nextRunAtMs"] = next_run_ms(expr)

    payload = {
        "kind": "agentTurn",
        "message": build_message(job_type, digest_type),
        "timeoutSeconds": timeout_seconds,
        "lightContext": True,
        "toolsAllow": ["exec", "read"],
    }
    if model:
        payload["model"] = model

    new_jobs.append(
        {
            "id": existing.get("id") or str(uuid.uuid4()),
            "agentId": existing.get("agentId") or agent_id,
            "name": name,
            "description": description,
            "enabled": True,
            "createdAtMs": existing.get("createdAtMs") or now_ms,
            "updatedAtMs": now_ms,
            "schedule": {
                "kind": "cron",
                "expr": expr,
                "tz": tz_name,
                "staggerMs": 0,
            },
            "sessionTarget": "isolated",
            "wakeMode": "now",
            "payload": payload,
            "delivery": {
                "mode": "none",
                "channel": "last",
            },
            "state": state,
        }
    )

if isinstance(raw, dict):
    raw["jobs"] = filtered_jobs + new_jobs
    output = raw
else:
    output = filtered_jobs + new_jobs

store_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
print(f"Patched {store_path}")
for job in new_jobs:
    print(f"{job['name']} | {job['schedule']['expr']} | next={job['state']['nextRunAtMs']}")
PYCODE_AGENTMAIL_SYNC

restart_gateway_if_present
echo "OpenClaw cron jobs synced for AgentMail Inbox."
