"""
AgentMail polling adapter for rules-driven signals extraction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agentmail_api import AgentMailApiClient
from matching import match_email_rule, truncate
from models import SignalCandidate


def collect_email_candidates(
    *,
    api: AgentMailApiClient,
    source: dict,
    ruleset_id: str,
    ruleset_title: str,
    rules: list[dict],
    since_dt: datetime,
    until_dt: datetime,
) -> tuple[list[SignalCandidate], list[str]]:
    page_token: str | None = None
    seen_threads: set[str] = set()
    messages: list[dict] = []
    pages = 0
    max_pages = int(source.get("max_message_pages", 5) or 5)
    page_size = int(source.get("message_page_size", 100) or 100)

    while pages < max_pages:
        pages += 1
        page = api.list_messages(
            source["inbox_ref"],
            limit=page_size,
            page_token=page_token,
            after=since_dt,
            before=until_dt,
        )
        batch = list(page.get("messages", []) or [])
        messages.extend(batch)
        page_token = page.get("next_page_token")
        if not page_token or not batch:
            break

    candidates: list[SignalCandidate] = []
    for message in messages:
        thread_id = str(message.get("thread_id", "")).strip()
        if not thread_id or thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        thread = api.get_thread(source["inbox_ref"], thread_id)
        for prepared in _window_messages(thread=thread, since_dt=since_dt, until_dt=until_dt):
            for rule in rules:
                candidate = match_email_rule(
                    ruleset_id=ruleset_id,
                    ruleset_title=ruleset_title,
                    rule=rule,
                    message=prepared,
                )
                if candidate is not None:
                    candidates.append(candidate)
    tail = [
        f"email source={source['id']} scanned_messages={len(messages)}",
        f"email source={source['id']} matched={len(candidates)}",
    ]
    return candidates, tail


def resolve_email_window(*, source: dict, last_success: datetime | None, lookback_minutes: int | None, now: datetime) -> tuple[datetime, datetime]:
    until_dt = now
    if lookback_minutes:
        return until_dt - timedelta(minutes=lookback_minutes), until_dt
    bootstrap = int(source.get("bootstrap_lookback_minutes", 720) or 720)
    grace = int(source.get("lag_grace_minutes", 15) or 15)
    if last_success is None:
        return until_dt - timedelta(minutes=bootstrap), until_dt
    return last_success - timedelta(minutes=grace), until_dt


def _window_messages(*, thread: dict, since_dt: datetime, until_dt: datetime) -> list[dict]:
    prepared: list[dict] = []
    for item in thread.get("messages", []) or []:
        timestamp = _parse_dt(item.get("timestamp"))
        if timestamp is None or timestamp < since_dt or timestamp > until_dt:
            continue
        full_text = _resolve_text_excerpt(item=item, thread=thread)
        raw_from = str(item.get("from") or "").strip()
        from_name, from_email, sender_domain = _parse_sender(raw_from)
        prepared.append(
            {
                "message_id": str(item.get("message_id", "")).strip(),
                "thread_id": str(item.get("thread_id", "")).strip(),
                "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
                "from_name": from_name,
                "from_email": from_email,
                "sender_domain": sender_domain,
                "subject": str(item.get("subject") or thread.get("subject") or "(no subject)"),
                "preview": truncate(str(item.get("preview") or thread.get("preview") or ""), 320),
                "text_excerpt": truncate(full_text, 1200),
                "delivery_text": truncate(full_text, 3500),
            }
        )
    return prepared


def _resolve_text_excerpt(*, item: dict, thread: dict) -> str:
    for key in ("text_excerpt", "extracted_text", "text", "body_text", "body_plain", "plain_text", "content_text"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return str(item.get("preview") or thread.get("preview") or "").strip()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _parse_sender(raw: str | None) -> tuple[str, str, str]:
    value = (raw or "").strip()
    if not value:
        return "", "", ""
    if "<" in value and ">" in value:
        name, email = value.split("<", 1)
        email = email.split(">", 1)[0]
        name = name.strip().strip('"')
    elif "@" in value and " " not in value:
        name, email = "", value
    else:
        name, email = value, ""
    domain = email.split("@", 1)[1].lower() if "@" in email else ""
    return name.strip(), email.strip().lower(), domain
