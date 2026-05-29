#!/usr/bin/env bash
set -euo pipefail

digest_type="${1:?digest type required}"
lookback_minutes="${2:-}"

case "$digest_type" in
  morning|interval|editorial) ;;
  *) echo "invalid digest type: $digest_type" >&2; exit 2 ;;
esac

cd "$(dirname "$0")"
docker compose --env-file email.env exec -T agentmail-email-bridge python - "$digest_type" "$lookback_minutes" <<'PY'
import json
import os
import sys
import urllib.request

digest_type = sys.argv[1]
lookback_minutes = sys.argv[2].strip()
token = os.environ.get("EMAIL_BRIDGE_TOKEN", "").strip()
port = int(os.environ.get("EMAIL_BRIDGE_PORT", "8092") or 8092)
if not token:
    raise SystemExit("EMAIL_BRIDGE_TOKEN is missing in bridge container")

payload = {
    "job_type": "digest",
    "digest_type": digest_type,
}
if lookback_minutes:
    payload["lookback_minutes"] = lookback_minutes

req = urllib.request.Request(
    f"http://127.0.0.1:{port}/trigger",
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
