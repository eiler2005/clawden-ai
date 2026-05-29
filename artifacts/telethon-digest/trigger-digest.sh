#!/usr/bin/env bash
set -euo pipefail

digest_type="${1:?digest type required}"
slot_hour="${2:?slot hour required}"
slot_minute="${3:-0}"

case "$digest_type" in
  morning|interval|editorial) ;;
  *) echo "invalid digest type: $digest_type" >&2; exit 2 ;;
esac

cd /opt/telethon-digest
docker compose exec -T telethon-digest-cron-bridge python - "$digest_type" "$slot_hour" "$slot_minute" <<'PY'
import json
import os
import sys
import urllib.request

digest_type, slot_hour, slot_minute = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
token = os.environ.get("DIGEST_CRON_BRIDGE_TOKEN", "").strip()
if not token:
    raise SystemExit("DIGEST_CRON_BRIDGE_TOKEN is missing in bridge container")

payload = {
    "digest_type": digest_type,
    "slot_hour": slot_hour,
    "slot_minute": slot_minute,
}
req = urllib.request.Request(
    "http://127.0.0.1:8091/trigger",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=60) as resp:
    print(resp.read().decode("utf-8"))
PY
