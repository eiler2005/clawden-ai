#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
COMMAND=$(
  printf '%s' "$INPUT" | python3 -c '
import json
import sys

try:
    payload = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)

print(payload.get("tool_input", {}).get("command", ""))
' 2>/dev/null || true
)

LOWER_COMMAND=$(printf '%s' "$COMMAND" | tr '[:upper:]' '[:lower:]')

INSTALL_PATTERN='(apt(-get)?[[:space:]]+install|pip3?[[:space:]]+install|python3[[:space:]]+-m[[:space:]]+pip[[:space:]]+install|brew[[:space:]]+install|npm[[:space:]]+install[[:space:]]+-g)'
OPENCLAW_RUNTIME_PATTERN='(openclaw|openai-whisper|whisper|ffmpeg|ffprobe|torch)'
CONTAINER_CONTEXT_PATTERN='(docker[[:space:]]+compose[[:space:]]+(exec|run|build)|docker[[:space:]]+build|dockerfile\.iproute2|/opt/openclaw/)'

if printf '%s\n' "$LOWER_COMMAND" | grep -Eq "$INSTALL_PATTERN" \
  && printf '%s\n' "$LOWER_COMMAND" | grep -Eq "$OPENCLAW_RUNTIME_PATTERN" \
  && ! printf '%s\n' "$LOWER_COMMAND" | grep -Eq "$CONTAINER_CONTEXT_PATTERN"; then
  cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"OpenClaw runtime dependencies in this project are container-only by policy. Install them in /opt/openclaw/Dockerfile.iproute2 or run them via docker compose exec inside openclaw-gateway, not on the Hetzner host OS."}}
EOF
fi
