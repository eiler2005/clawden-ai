"""
Telethon polling adapter for rules-driven signals extraction.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from matching import match_telegram_rule, truncate
from models import SignalCandidate

if TYPE_CHECKING:
    from telethon import TelegramClient
    from telethon.tl.types import Message


async def collect_telegram_candidates(
    *,
    client: TelegramClient,
    source: dict,
    ruleset_id: str,
    ruleset_title: str,
    rules: list[dict],
    cursor: int,
    last_success: datetime | None,
    lookback_minutes: int | None,
    now: datetime,
) -> tuple[list[SignalCandidate], list[str], int]:
    since_dt = resolve_telegram_window(
        source=source,
        cursor=cursor,
        last_success=last_success,
        lookback_minutes=lookback_minutes,
        now=now,
    )
    limit = int(source.get("message_limit", 80) or 80)
    history = await client.get_messages(int(source["chat_id"]), limit=limit)
    candidates: list[SignalCandidate] = []
    max_seen_id = cursor
    scanned = 0
    from telethon.tl.types import Message

    for msg in history:
        if not isinstance(msg, Message) or not msg.message:
            continue
        scanned += 1
        sender_id = _sender_id(msg)
        msg_dt = msg.date.astimezone(timezone.utc)
        if msg.id <= cursor and msg_dt < since_dt:
            continue
        prepared = {
            "chat_id": int(source["chat_id"]),
            "chat_name": str(source.get("chat_name") or source["id"]),
            "chat_username": str(source.get("chat_username") or "").strip(),
            "message_id": msg.id,
            "sender_id": sender_id,
            "author": _author_name(msg, sender_id),
            "text": truncate(msg.message or "", 1800),
            "timestamp": msg_dt.isoformat(),
            "has_video": bool(getattr(msg, "video", None)),
        }
        max_seen_id = max(max_seen_id, msg.id)
        for rule in rules:
            candidate = match_telegram_rule(
                ruleset_id=ruleset_id,
                ruleset_title=ruleset_title,
                rule=rule,
                message=prepared,
            )
            if candidate is not None:
                candidates.append(candidate)
    tail = [
        f"telegram source={source['id']} scanned_messages={scanned}",
        f"telegram source={source['id']} matched={len(candidates)}",
    ]
    return candidates, tail, max_seen_id


def resolve_telegram_window(
    *,
    source: dict,
    cursor: int,
    last_success: datetime | None,
    lookback_minutes: int | None,
    now: datetime,
) -> datetime:
    if lookback_minutes:
        return now - timedelta(minutes=lookback_minutes)
    if last_success is None or cursor <= 0:
        bootstrap = int(source.get("bootstrap_lookback_minutes", 720) or 720)
        return now - timedelta(minutes=bootstrap)
    overlap = int(source.get("overlap_grace_minutes", 15) or 15)
    return last_success - timedelta(minutes=overlap)


def build_client() -> "TelegramClient":
    import os
    from telethon import TelegramClient

    return TelegramClient(
        os.environ.get("SIGNALS_TELETHON_SESSION_PATH", "/app/sessions/signals_bridge"),
        int(os.environ["TELEGRAM_API_ID"]),
        os.environ["TELEGRAM_API_HASH"],
    )


def _sender_id(message: "Message") -> int:
    value = getattr(message, "sender_id", None)
    if isinstance(value, int):
        return value
    if hasattr(value, "user_id"):
        return int(value.user_id)
    return 0


def _author_name(message: "Message", sender_id: int) -> str:
    display = " ".join(
        str(part).strip()
        for part in [getattr(message, "post_author", ""), getattr(message, "sender", None) and getattr(message.sender, "first_name", "")]
        if str(part).strip()
    ).strip()
    return display or str(sender_id or "Telegram")
