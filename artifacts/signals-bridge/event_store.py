"""
Redis Streams helpers for derived signals events.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from models import SignalEvent

STREAM_EVENTS = "ingest:events:signals"


def _event_to_fields(event: SignalEvent) -> dict[str, str]:
    return {
        "event_id": event.event_id,
        "ruleset_id": event.ruleset_id,
        "rule_id": event.rule_id,
        "source_type": event.source_type,
        "source_id": event.source_id,
        "external_ref": event.external_ref,
        "occurred_at": event.occurred_at,
        "captured_at": event.captured_at,
        "author": event.author,
        "title": event.title,
        "summary": event.summary,
        "source_link": event.source_link,
        "source_excerpt": event.source_excerpt,
        "tags": json.dumps(event.tags, ensure_ascii=False),
        "confidence": str(event.confidence),
        "telegram_topic": event.telegram_topic,
    }


def event_dedup_key(event: SignalEvent) -> str:
    return f"dedup:signals:{event.source_type}:{event.source_id}:{event.external_ref}"


def append_new_events(
    r,
    events: list[SignalEvent],
    *,
    retention_days: int,
) -> tuple[list[str], list[SignalEvent], list[SignalEvent]]:
    ids: list[str] = []
    appended: list[SignalEvent] = []
    skipped: list[SignalEvent] = []
    seen_keys: set[str] = set()
    for event in events:
        dedup_key = event_dedup_key(event)
        if dedup_key in seen_keys:
            skipped.append(event)
            continue
        seen_keys.add(dedup_key)
        if not r.set(dedup_key, event.event_id, nx=True, ex=retention_days * 86400):
            skipped.append(event)
            continue
        appended.append(event)
        ids.append(r.xadd(STREAM_EVENTS, _event_to_fields(event)))
    return ids, appended, skipped


def append_events(r, events: list[SignalEvent], *, retention_days: int) -> list[str]:
    ids, _, _ = append_new_events(r, events, retention_days=retention_days)
    return ids


def trim_old_events(r, *, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_id = f"{int(cutoff.timestamp() * 1000)}-0"
    deleted = 0
    while True:
        batch = r.xrange(STREAM_EVENTS, min="-", max=cutoff_id, count=200)
        if not batch:
            break
        ids = [item_id for item_id, _ in batch]
        if ids:
            deleted += r.xdel(STREAM_EVENTS, *ids)
        if len(batch) < 200:
            break
    return deleted
