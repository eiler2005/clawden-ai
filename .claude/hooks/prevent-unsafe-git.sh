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

if printf '%s\n' "$COMMAND" | grep -Eiq '(^|[;&|[:space:]])git[[:space:]]+add[[:space:]]+(\.|-A|--all)([[:space:];&|]|$)|(^|[;&|[:space:]])git[[:space:]]+commit([[:space:]][^;&|]*)?[[:space:]]+(-a|--all)([[:space:];&|]|$)'; then
  cat <<'EOF'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Use explicit staging in this repository. Avoid broad Git commands such as git add ., git add -A, git add --all, and git commit -a because secrets/ and LOCAL_ACCESS.md must never be staged accidentally."}}
EOF
fi
