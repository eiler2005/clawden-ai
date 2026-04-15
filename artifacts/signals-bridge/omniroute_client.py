"""
Cheap OmniRoute client with strict local fallback for signals enrichment.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from matching import local_event_from_candidate
from models import ModelMeta, PreparedSignalBatch, SignalCandidate, SignalEvent
from prompts import build_prepare_signal_batch_prompt


OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://omniroute:20129/v1/chat/completions").strip()
OMNIROUTE_API_KEY = os.environ.get("OMNIROUTE_API_KEY", "").strip()
OMNIROUTE_MODEL = os.environ.get("OMNIROUTE_MODEL", "light").strip() or "light"
OMNIROUTE_TIMEOUT_SECONDS = int(os.environ.get("OMNIROUTE_TIMEOUT_SECONDS", "45") or 45)
OMNIROUTE_MAX_TOKENS = int(os.environ.get("OMNIROUTE_MAX_TOKENS", "500") or 500)
OMNIROUTE_TEMPERATURE = float(os.environ.get("OMNIROUTE_TEMPERATURE", "0.1") or 0.1)


def prepare_signal_batch(
    *,
    ruleset_title: str,
    topic_name: str,
    candidates: list[SignalCandidate],
) -> PreparedSignalBatch:
    if not candidates:
        return PreparedSignalBatch(events=[], model_meta=ModelMeta(model_id="local", tier="light", local_fallback=True))
    try:
        payload = _run_omniroute_prompt(
            build_prepare_signal_batch_prompt(
                ruleset_title=ruleset_title,
                candidates=candidates,
                topic_name=topic_name,
            )
        )
        return _payload_to_batch(payload=payload, candidates=candidates, topic_name=topic_name)
    except Exception:
        return _local_fallback_batch(candidates=candidates, topic_name=topic_name)


def _run_omniroute_prompt(prompt: str) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": OMNIROUTE_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "max_tokens": OMNIROUTE_MAX_TOKENS,
            "temperature": OMNIROUTE_TEMPERATURE,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if OMNIROUTE_API_KEY:
        headers["Authorization"] = f"Bearer {OMNIROUTE_API_KEY}"
    req = urllib.request.Request(OMNIROUTE_URL, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=OMNIROUTE_TIMEOUT_SECONDS) as resp:
        raw = json.load(resp)
    choice = (((raw.get("choices") or [{}])[0]).get("message") or {}).get("content", "")
    text = choice if isinstance(choice, str) else json.dumps(choice, ensure_ascii=False)
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict) or parsed.get("ok") is False:
        raise ValueError("omniroute returned invalid payload")
    if "model_meta" not in parsed:
        parsed["model_meta"] = {
            "model_id": OMNIROUTE_MODEL,
            "tier": "light",
            "provider_fallback": False,
            "local_fallback": False,
        }
    return parsed


def _extract_json_object(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()[1:]
        while lines and lines[-1].strip() == "```":
            lines.pop()
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, char in enumerate(stripped):
            if char != "{":
                continue
            try:
                payload, _ = decoder.raw_decode(stripped[idx:])
                return payload
            except json.JSONDecodeError:
                continue
    raise ValueError("no json object found")


def _payload_to_batch(*, payload: dict[str, Any], candidates: list[SignalCandidate], topic_name: str) -> PreparedSignalBatch:
    by_ref = {candidate.external_ref: candidate for candidate in candidates}
    events: list[SignalEvent] = []
    dropped: list[str] = []
    for idx, item in enumerate(payload.get("items", []) or [], start=1):
        external_ref = str(item.get("external_ref", "")).strip()
        candidate = by_ref.get(external_ref)
        if candidate is None:
            continue
        if not item.get("keep", True):
            dropped.append(external_ref)
            continue
        title = str(item.get("title", "")).strip() or candidate.subject or candidate.author
        summary = str(item.get("summary", "")).strip() or candidate.excerpt
        tags = [str(tag) for tag in item.get("tags", []) if str(tag).strip()] or candidate.tags
        events.append(
            SignalEvent(
                event_id=f"{candidate.ruleset_id}:{idx:02d}:{external_ref}",
                ruleset_id=candidate.ruleset_id,
                rule_id=candidate.rule_id,
                source_type=candidate.source_type,
                source_id=candidate.source_id,
                external_ref=candidate.external_ref,
                occurred_at=candidate.occurred_at,
                captured_at=candidate.captured_at,
                author=candidate.author,
                title=title[:120],
                summary=summary[:280],
                source_link=str(candidate.metadata.get("message_link") or ""),
                source_excerpt=candidate.excerpt[:700],
                delivery_text=str(candidate.metadata.get("delivery_text") or candidate.excerpt or "")[:3500],
                source_chat_id=int(candidate.metadata.get("chat_id") or 0) if candidate.source_type == "telegram" else 0,
                source_message_id=int(candidate.metadata.get("message_id") or 0) if candidate.source_type == "telegram" else 0,
                tags=list(dict.fromkeys(tags)),
                confidence=float(item.get("confidence", 0.7) or 0.7),
                telegram_topic=topic_name,
            )
        )
    if not events and candidates:
        return _local_fallback_batch(candidates=candidates, topic_name=topic_name)
    return PreparedSignalBatch(
        events=events,
        model_meta=ModelMeta.from_payload(payload.get("model_meta")),
        dropped_external_refs=dropped,
    )


def _local_fallback_batch(*, candidates: list[SignalCandidate], topic_name: str) -> PreparedSignalBatch:
    events: list[SignalEvent] = []
    dropped: list[str] = []
    for idx, candidate in enumerate(candidates, start=1):
        event = local_event_from_candidate(
            candidate,
            event_id=f"{candidate.ruleset_id}:{idx:02d}:{candidate.external_ref}",
            topic_name=topic_name,
        )
        if event is None:
            dropped.append(candidate.external_ref)
            continue
        events.append(event)
    return PreparedSignalBatch(
        events=events,
        model_meta=ModelMeta(model_id="local", tier="light", local_fallback=True),
        dropped_external_refs=dropped,
    )
