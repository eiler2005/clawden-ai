"""
Redis Streams helpers for derived email events.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from models import EmailEvent

STREAM_EVENTS = "ingest:events:email"


def _event_to_fields(event: EmailEvent) -> dict[str, str]:
    return {
        "event_id": event.event_id,
        "run_id": event.run_id,
        "inbox_ref": event.inbox_ref,
        "thread_id": event.thread_id,
        "message_ids": json.dumps(event.message_ids, ensure_ascii=False),
        "received_at": event.received_at,
        "from_name": event.from_name,
        "from_email": event.from_email,
        "sender_domain": event.sender_domain,
        "subject": event.subject,
        "summary": event.summary,
        "importance": str(event.importance),
        "categories": json.dumps(event.categories, ensure_ascii=False),
        "has_attachments": "1" if event.has_attachments else "0",
        "attachment_count": str(event.attachment_count),
        "internal_labels": json.dumps(event.internal_labels, ensure_ascii=False),
        "telegram_topic": event.telegram_topic,
    }


def _fields_to_event(data: dict[str, str]) -> EmailEvent:
    return EmailEvent(
        event_id=data.get("event_id", ""),
        run_id=data.get("run_id", ""),
        inbox_ref=data.get("inbox_ref", ""),
        thread_id=data.get("thread_id", ""),
        message_ids=[str(v) for v in json.loads(data.get("message_ids", "[]"))],
        received_at=data.get("received_at", ""),
        from_name=data.get("from_name", ""),
        from_email=data.get("from_email", ""),
        sender_domain=data.get("sender_domain", ""),
        subject=data.get("subject", ""),
        summary=data.get("summary", ""),
        importance=float(data.get("importance", "0") or 0),
        categories=[str(v) for v in json.loads(data.get("categories", "[]"))],
        has_attachments=data.get("has_attachments", "0") == "1",
        attachment_count=int(data.get("attachment_count", "0") or 0),
        internal_labels=[str(v) for v in json.loads(data.get("internal_labels", "[]"))],
        telegram_topic=data.get("telegram_topic", "inbox-email"),
    )


def _dedup_key(event: EmailEvent) -> str:
    joined = "|".join(sorted(event.message_ids)) or event.thread_id
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:20]
    return f"dedup:email-event:{event.inbox_ref}:{event.thread_id}:{digest}"


def append_events(r, events: list[EmailEvent], *, retention_days: int) -> list[str]:
    ids: list[str] = []
    for event in events:
        if not r.set(_dedup_key(event), event.event_id, nx=True, ex=retention_days * 86400):
            continue
        ids.append(r.xadd(STREAM_EVENTS, _event_to_fields(event)))
    return ids


def list_events(r, *, inbox_ref: str, start: datetime, end: datetime) -> list[EmailEvent]:
    min_id = f"{int(start.timestamp() * 1000)}-0"
    max_id = f"{int(end.timestamp() * 1000)}-999999"
    events: list[EmailEvent] = []
    for _, data in r.xrange(STREAM_EVENTS, min=min_id, max=max_id):
        if data.get("inbox_ref") != inbox_ref:
            continue
        events.append(_fields_to_event(data))
    return events


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
