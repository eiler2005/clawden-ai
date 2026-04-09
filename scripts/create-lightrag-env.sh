#!/usr/bin/env bash
# create-lightrag-env.sh
# Creates scripts/lightrag.env by prompting for the Anthropic API key.
# Everything else (embeddings, storage) is local — no extra keys needed.
#
# Usage:
#   ./scripts/create-lightrag-env.sh
#
# If ANTHROPIC_API_KEY is already set in the environment, it will be used
# automatically without prompting.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/lightrag.env"
TEMPLATE="${SCRIPT_DIR}/lightrag.env.template"

if [[ -f "${ENV_FILE}" ]]; then
  echo "lightrag.env already exists at ${ENV_FILE}"
  read -p "Overwrite? [y/N] " confirm
  [[ "${confirm}" == "y" || "${confirm}" == "Y" ]] || { echo "Aborted."; exit 0; }
fi

# Get API key
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  API_KEY="${GEMINI_API_KEY}"
  echo "Using GEMINI_API_KEY from environment."
else
  echo ""
  echo "Enter your Google Gemini API key."
  echo "Get it free at: https://aistudio.google.com/app/apikey"
  echo "It starts with 'AIza...'"
  echo ""
  read -rsp "Gemini API key: " API_KEY
  echo ""
fi

if [[ -z "${API_KEY}" ]]; then
  echo "Error: API key cannot be empty."
  exit 1
fi

# Write env file from template (replace both LLM and embedding key placeholders)
sed "s|<your-gemini-api-key>|${API_KEY}|g" "${TEMPLATE}" > "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

echo ""
echo "Created: ${ENV_FILE}"
echo ""
echo "Next step:"
echo "  OPENCLAW_HOST=deploy@<server-host> LIGHTRAG_ENV_FILE=${ENV_FILE} ./scripts/setup-lightrag.sh"
