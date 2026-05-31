#!/usr/bin/env bash
# create-lightrag-env.sh
# Creates scripts/lightrag.env by prompting for DeepSeek and wiki-import keys.
# DeepSeek is used as the current LightRAG extraction fallback after OmniRoute
# light timeouts; wiki-import provides local OpenAI-compatible embeddings.
#
# Usage:
#   ./scripts/create-lightrag-env.sh
#
# If DEEPSEEK_API_KEY and/or WIKI_IMPORT_TOKEN are already set in the
# environment, they are used automatically without prompting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/lightrag.env"
TEMPLATE="${SCRIPT_DIR}/lightrag.env.template"

if [[ -f "${ENV_FILE}" ]]; then
  echo "lightrag.env already exists at ${ENV_FILE}"
  read -p "Overwrite? [y/N] " confirm
  [[ "${confirm}" == "y" || "${confirm}" == "Y" ]] || { echo "Aborted."; exit 0; }
fi

# Get DeepSeek API key for LightRAG LLM extraction.
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  DEEPSEEK_KEY="${DEEPSEEK_API_KEY}"
  echo "Using DEEPSEEK_API_KEY from environment."
else
  echo ""
  echo "Enter your DeepSeek API key."
  echo "This is used for https://api.deepseek.com/v1 while OmniRoute light is timing out."
  echo ""
  read -rsp "DeepSeek API key: " DEEPSEEK_KEY
  echo ""
fi

if [[ -z "${DEEPSEEK_KEY}" ]]; then
  echo "Error: DeepSeek API key cannot be empty."
  exit 1
fi

# Get wiki-import token for local embeddings.
if [[ -n "${WIKI_IMPORT_TOKEN:-}" ]]; then
  WIKI_IMPORT_KEY="${WIKI_IMPORT_TOKEN}"
  echo "Using WIKI_IMPORT_TOKEN from environment."
else
  echo ""
  echo "Enter your wiki-import bearer token."
  echo "This is the same token used by /opt/wiki-import/wiki-import.env."
  echo ""
  read -rsp "wiki-import token: " WIKI_IMPORT_KEY
  echo ""
fi

if [[ -z "${WIKI_IMPORT_KEY}" ]]; then
  echo "Error: wiki-import token cannot be empty."
  exit 1
fi

# Write env file from template.
python3 - "$TEMPLATE" "$ENV_FILE" "$DEEPSEEK_KEY" "$WIKI_IMPORT_KEY" <<'PY'
import sys
from pathlib import Path

template, env_file, deepseek_key, wiki_import_key = sys.argv[1:5]
text = Path(template).read_text()
text = text.replace("<your-deepseek-api-key>", deepseek_key)
text = text.replace("<your-wiki-import-token>", wiki_import_key)
Path(env_file).write_text(text)
PY
chmod 600 "${ENV_FILE}"

echo ""
echo "Created: ${ENV_FILE}"
echo ""
echo "Next step:"
echo "  OPENCLAW_HOST=deploy@<server-host> LIGHTRAG_ENV_FILE=${ENV_FILE} ./scripts/setup-lightrag.sh"
