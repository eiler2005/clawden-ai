#!/usr/bin/env bash
# create-lightrag-env.sh
# Creates scripts/lightrag.env by prompting for OmniRoute and Google Gemini keys.
# OmniRoute is used for LightRAG extraction; Gemini is used for embeddings.
# DeepSeek can be an OmniRoute LLM reserve, but it cannot replace embeddings.
#
# Usage:
#   ./scripts/create-lightrag-env.sh
#
# If OMNIROUTE_API_KEY and/or GEMINI_API_KEY are already set in the environment,
# they are used automatically without prompting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/lightrag.env"
TEMPLATE="${SCRIPT_DIR}/lightrag.env.template"

if [[ -f "${ENV_FILE}" ]]; then
  echo "lightrag.env already exists at ${ENV_FILE}"
  read -p "Overwrite? [y/N] " confirm
  [[ "${confirm}" == "y" || "${confirm}" == "Y" ]] || { echo "Aborted."; exit 0; }
fi

# Get OmniRoute API key for LightRAG LLM extraction.
if [[ -n "${OMNIROUTE_API_KEY:-}" ]]; then
  OMNIROUTE_KEY="${OMNIROUTE_API_KEY}"
  echo "Using OMNIROUTE_API_KEY from environment."
else
  echo ""
  echo "Enter your OmniRoute API key."
  echo "This is the key configured for http://omniroute:20129/v1."
  echo ""
  read -rsp "OmniRoute API key: " OMNIROUTE_KEY
  echo ""
fi

if [[ -z "${OMNIROUTE_KEY}" ]]; then
  echo "Error: OmniRoute API key cannot be empty."
  exit 1
fi

# Get Gemini API key for embeddings.
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  GEMINI_KEY="${GEMINI_API_KEY}"
  echo "Using GEMINI_API_KEY from environment."
else
  echo ""
  echo "Enter your Google Gemini API key for embeddings."
  echo "Get it free at: https://aistudio.google.com/app/apikey"
  echo "It starts with 'AIza...'"
  echo ""
  read -rsp "Gemini API key: " GEMINI_KEY
  echo ""
fi

if [[ -z "${GEMINI_KEY}" ]]; then
  echo "Error: Gemini API key cannot be empty."
  exit 1
fi

# Write env file from template.
python3 - "$TEMPLATE" "$ENV_FILE" "$OMNIROUTE_KEY" "$GEMINI_KEY" <<'PY'
import sys
from pathlib import Path

template, env_file, omniroute_key, gemini_key = sys.argv[1:5]
text = Path(template).read_text()
text = text.replace("<your-omniroute-api-key>", omniroute_key)
text = text.replace("<your-gemini-api-key>", gemini_key)
Path(env_file).write_text(text)
PY
chmod 600 "${ENV_FILE}"

echo ""
echo "Created: ${ENV_FILE}"
echo ""
echo "Next step:"
echo "  OPENCLAW_HOST=deploy@<server-host> LIGHTRAG_ENV_FILE=${ENV_FILE} ./scripts/setup-lightrag.sh"
