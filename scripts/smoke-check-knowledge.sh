#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_HOST="${OPENCLAW_HOST:-}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_rsa}"
EXCLUDE_SOURCE_TITLES="${EXCLUDE_SOURCE_TITLES:-Denis_Faang}"
SSH_OPTS=(
  -i "$SSH_KEY"
  -o BatchMode=yes
  -o StrictHostKeyChecking=accept-new
  -o ConnectTimeout="${SSH_CONNECT_TIMEOUT:-15}"
  -o ConnectionAttempts=1
)

if [[ -z "$OPENCLAW_HOST" ]]; then
  echo "Set OPENCLAW_HOST, for example: export OPENCLAW_HOST=deploy@<server-host>" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

REMOTE_JSON_PATH="/tmp/knowledge-smoke-check.$$.json"

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "REMOTE_JSON_PATH='${REMOTE_JSON_PATH}' python3 -" > "${TMP_DIR}/remote-python.log" <<'PY'
import json
import os
from pathlib import Path

vault_root = Path("/opt/obsidian-vault")
research_root = vault_root / "wiki" / "research"
log_path = vault_root / "wiki" / "LOG.md"
queue_path = vault_root / "wiki" / "IMPORT-QUEUE.md"
output_path = Path(os.environ["REMOTE_JSON_PATH"])


def count_prefix(prefix: str) -> int:
    return len(list(research_root.glob(f"{prefix}*.md")))


def read_preview(path: Path, max_lines: int = 10) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lines:]


result = {
    "research_page_total": len(list(research_root.glob("*.md"))),
    "research_prefix_counts": {
        "denis_ai": count_prefix("denis-ai-"),
        "denis_toolsforlife": count_prefix("denis-toolsforlife-"),
        "denis_interesting": count_prefix("denis-interesting-"),
        "saved_messages": count_prefix("saved-messages-"),
        "denis_faang": count_prefix("denis-faang-"),
    },
    "wiki_log_tail": read_preview(log_path),
    "import_queue_tail": read_preview(queue_path),
}

output_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
print(output_path)
PY

scp "${SSH_OPTS[@]}" "${OPENCLAW_HOST}:${REMOTE_JSON_PATH}" "${TMP_DIR}/remote.json" >/dev/null
ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" "rm -f '${REMOTE_JSON_PATH}'" >/dev/null

EXCLUDE_SOURCE_TITLES="${EXCLUDE_SOURCE_TITLES}" \
OPENCLAW_HOST="${OPENCLAW_HOST}" \
SSH_KEY="${SSH_KEY}" \
bash "${ROOT_DIR}/scripts/backfill-denis-sources-to-wiki.sh" --dry-run > "${TMP_DIR}/backfill.txt"

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "curl -sf http://127.0.0.1:8020/health && echo && curl -sf http://127.0.0.1:8020/documents/status_counts" \
  > "${TMP_DIR}/lightrag-health.txt"

ssh "${SSH_OPTS[@]}" "$OPENCLAW_HOST" \
  "python3 - <<'PY'
import json
import re
import urllib.request
from pathlib import Path


VAULT_ROOT = Path('/opt/obsidian-vault')
RESEARCH_ROOT = VAULT_ROOT / 'wiki' / 'research'
LEDGER_PATH = VAULT_ROOT / '.ingest-ledgers' / 'telegram-post-imports.jsonl'


def telegram_deeplink(chat_id, message_id):
    chat = str(chat_id or '').strip()
    msg = str(message_id or '').strip()
    if not chat or not msg or chat == 'me':
        return None
    if chat.startswith('-100') and msg.isdigit():
        return f'https://t.me/c/{chat[4:]}/{msg}'
    return None


def load_ledger():
    records = {}
    if not LEDGER_PATH.exists():
        return records
    for line in LEDGER_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        research_path = str(payload.get('research_path') or '').strip()
        if research_path:
            records[Path(research_path).name] = payload
    return records


def parse_source_links(file_path, ledger):
    result = {
        'wiki': file_path,
        'source_links': [],
        'source_provenance': {},
    }
    page = RESEARCH_ROOT / file_path
    ledger_row = ledger.get(Path(file_path).name)
    if ledger_row:
        canonical = str(ledger_row.get('source') or '').strip()
        if canonical.startswith('http://') or canonical.startswith('https://'):
            result['source_links'].append(canonical)
        tg = telegram_deeplink(ledger_row.get('source_chat_id'), ledger_row.get('message_id'))
        if tg:
            result['source_links'].append(tg)
        result['source_provenance'] = {
            'source_title': ledger_row.get('source_title'),
            'message_id': ledger_row.get('message_id'),
            'post_date_utc': ledger_row.get('post_date_utc'),
        }
        return result

    if not page.exists():
        return result

    text = page.read_text(encoding='utf-8', errors='ignore')
    url_match = re.search(r'^source:\s*(https?://\S+)\s*$', text, flags=re.MULTILINE)
    if url_match:
        result['source_links'].append(url_match.group(1).strip())

    q_match = re.search(r'from ([A-Za-z0-9_ ]+) message (\d+) dated ([0-9T:+-]+)', text)
    if q_match:
        result['source_provenance'] = {
            'source_title': q_match.group(1).strip(),
            'message_id': int(q_match.group(2)),
            'post_date_utc': q_match.group(3).strip(),
        }
    return result


ledger = load_ledger()

query_specs = [
    {
        'query': 'life principles',
        'kind': 'thematic',
        'expected_ref_substrings': [
            'denis-interesting-2024-08-13-102',
            'denis-toolsforlife-2025-05-09-160',
        ],
    },
    {
        'query': 'Claude code best practices',
        'kind': 'factual',
        'expected_ref_substrings': [
            'denis-ai-2025-05-15-claude-code-best-practices',
            '2026-04-21-claude-code-guide',
            'denis-ai-2025-07-01-158-claude-code',
        ],
    },
    {
        'query': 'NOCONCEPT',
        'kind': 'entity_topic',
        'expected_ref_substrings': [
            'noconcept',
            'denis-interesting',
            'denis-ai',
        ],
    },
]
results = []
for spec in query_specs:
    query = spec['query']
    req = urllib.request.Request(
        'http://127.0.0.1:8020/query',
        data=json.dumps({'query': query, 'mode': 'hybrid'}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        payload = json.loads(response.read().decode('utf-8'))
    refs = payload.get('references') or payload.get('refs') or []
    ref_paths = [
        str(item.get('file_path') or item.get('path') or '')
        for item in refs
        if isinstance(item, dict)
    ]
    source_meta = [
        parse_source_links(path, ledger)
        for path in ref_paths[:5]
        if path
    ]
    results.append(
        {
            'query': query,
            'kind': spec['kind'],
            'references': len(refs),
            'response_preview': str(payload.get('response') or payload.get('answer') or '')[:240],
            'reference_preview': refs[:3],
            'all_reference_paths': ref_paths[:10],
            'source_link_preview': source_meta[:3],
            'expected_ref_substrings': spec['expected_ref_substrings'],
        }
    )
print(json.dumps(results, ensure_ascii=False))
PY" > "${TMP_DIR}/queries.json"

python3 - <<'PY' "${TMP_DIR}/remote.json" "${TMP_DIR}/backfill.txt" "${TMP_DIR}/lightrag-health.txt" "${TMP_DIR}/queries.json"
import json
import re
import sys
from pathlib import Path

remote = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
backfill_text = Path(sys.argv[2]).read_text(encoding="utf-8", errors="ignore")
health_lines = [line for line in Path(sys.argv[3]).read_text(encoding="utf-8").splitlines() if line.strip()]
queries = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))

candidates_match = re.search(r'"candidates"\s*:\s*(\d+)', backfill_text)
resume_match = re.search(r'"resume_skipped"\s*:\s*(\d+)', backfill_text)
dedupe_match = re.search(r'"dedupe_skipped"\s*:\s*(\d+)', backfill_text)

health = json.loads(health_lines[0]) if health_lines else {}
status_counts = json.loads(health_lines[1]).get("status_counts", {}) if len(health_lines) > 1 else {}

degraded_markers = (
    "do not have enough information",
    "cannot answer your question",
    "too broad",
    "does not contain information",
    "lightRAG unavailable".lower(),
)

for item in queries:
    preview = str(item.get("response_preview", "")).lower()
    refs = int(item.get("references", 0) or 0)
    ref_paths = [str(path).lower() for path in item.get("all_reference_paths", [])]
    expected = [str(marker).lower() for marker in item.get("expected_ref_substrings", [])]
    source_links = [
        link
        for entry in item.get("source_link_preview", [])
        for link in entry.get("source_links", [])
    ]
    expected_ref_hit = any(
        marker in path
        for marker in expected
        for path in ref_paths
    )
    item["quality_flags"] = {
        "has_refs": refs > 0,
        "degraded_answer": any(marker in preview for marker in degraded_markers),
        "expected_ref_hit": expected_ref_hit,
        "has_source_links": len(source_links) > 0,
        "targeted_factual_pass": (
            item.get("kind") != "factual"
            or (
                refs > 0
                and expected_ref_hit
                and len(source_links) > 0
                and not any(marker in preview for marker in degraded_markers)
            )
        ),
    }

quality_summary = {
    "targeted_factual_queries": [
        item["query"] for item in queries if item.get("kind") == "factual"
    ],
    "targeted_factual_pass": all(
        item["quality_flags"]["targeted_factual_pass"]
        for item in queries
        if item.get("kind") == "factual"
    ),
    "degraded_queries": [
        item["query"] for item in queries if item["quality_flags"]["degraded_answer"]
    ],
}

summary = {
    "wiki": {
        "research_page_total": remote["research_page_total"],
        "research_prefix_counts": remote["research_prefix_counts"],
        "dry_run": {
            "candidates": int(candidates_match.group(1)) if candidates_match else None,
            "resume_skipped": int(resume_match.group(1)) if resume_match else None,
            "dedupe_skipped": int(dedupe_match.group(1)) if dedupe_match else None,
        },
        "wiki_log_tail": remote["wiki_log_tail"][-5:],
        "import_queue_tail": remote["import_queue_tail"][-5:],
    },
    "lightrag": {
        "status": health.get("status"),
        "pipeline_busy": health.get("pipeline_busy"),
        "status_counts": status_counts,
        "queries": queries,
        "quality_summary": quality_summary,
    },
}

print(json.dumps(summary, ensure_ascii=False, indent=2))
PY
