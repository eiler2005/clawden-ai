"""
Prompt builders for cheap signals enrichment.
"""
from __future__ import annotations

import json

from models import SignalCandidate


def build_prepare_signal_batch_prompt(*, ruleset_title: str, candidates: list[SignalCandidate], topic_name: str) -> str:
    compact = [candidate.to_prompt_payload() for candidate in candidates]
    return f"""Prepare a low-cost normalized signals batch for Telegram topic {topic_name}.

Ruleset: {ruleset_title}

Use only the candidate items below.
Return strict JSON only. No markdown, no explanation.
Keep the output compact. Prefer one short title, one short summary, 1-4 tags, and a confidence score.

Important:
- These items already passed deterministic prefilter.
- Keep=true unless the text is clearly empty/noise.
- Do not invent facts not visible in the candidate text.

JSON schema:
{{
  "ok": true,
  "items": [
    {{
      "external_ref": "stable external ref",
      "keep": true,
      "title": "short human-readable title",
      "summary": "1 short sentence",
      "tags": ["si", "fx"],
      "confidence": 0.0
    }}
  ],
  "model_meta": {{
    "model_id": "model id",
    "tier": "light",
    "provider_fallback": false,
    "local_fallback": false
  }}
}}

Candidate JSON:
{json.dumps(compact, ensure_ascii=False, indent=2)}
"""

