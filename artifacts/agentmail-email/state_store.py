"""
Redis-backed state keys and locks for the AgentMail inbox pipeline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _normalize_inbox_ref(inbox_ref: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in inbox_ref)


def last_poll_key(inbox_ref: str) -> str:
    return f"state:email:{_normalize_inbox_ref(inbox_ref)}:last_poll_at"


def last_digest_key(inbox_ref: str) -> str:
    return f"state:email:{_normalize_inbox_ref(inbox_ref)}:last_digest_at"


def last_poll_success_key(inbox_ref: str) -> str:
    return f"state:email:{_normalize_inbox_ref(inbox_ref)}:last_poll_success_at"


def next_poll_due_key(inbox_ref: str) -> str:
    return f"state:email:{_normalize_inbox_ref(inbox_ref)}:next_poll_due_at"


def lock_key(inbox_ref: str, job_type: str) -> str:
    return f"lock:email:{_normalize_inbox_ref(inbox_ref)}:{job_type}"


def status_key() -> str:
    return "status:email:latest"


def get_dt(r, key: str) -> datetime | None:
    value = r.get(key)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def set_dt(r, key: str, value: datetime) -> None:
    r.set(key, value.astimezone(timezone.utc).isoformat())


def acquire_lock(r, key: str, holder: str, ttl_seconds: int) -> bool:
    return bool(r.set(key, holder, nx=True, ex=ttl_seconds))


def release_lock(r, key: str, holder: str) -> None:
    current = r.get(key)
    if current == holder:
        r.delete(key)


def set_status(r, payload: dict) -> None:
    r.set(status_key(), json.dumps(payload, ensure_ascii=False))
