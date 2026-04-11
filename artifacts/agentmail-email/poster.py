"""
Telegram posting helpers for inbox-email poll batches and digests.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import aiohttp

from models import DigestPrepResult, EmailEvent, ModelMeta, PollPrepResult

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SUPERGROUP_ID = int(os.environ["EMAIL_DIGEST_SUPERGROUP_ID"])
TOPIC_ID = int(os.environ["EMAIL_DIGEST_TOPIC_ID"])
TIMEZONE = ZoneInfo(os.environ.get("EMAIL_DIGEST_TIMEZONE", "Europe/Moscow"))

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_MSG_LEN = 3900

_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre"}
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)


def _sanitize_html(text: str) -> str:
    def _replace(match: re.Match) -> str:
        slash, tag = match.group(1), match.group(2).lower()
        if tag not in _ALLOWED_TAGS:
            return ""
        return f"<{slash}{tag}>"

    return _TAG_RE.sub(_replace, text)


def _fmt_window(start: datetime, end: datetime) -> str:
    local_start = start.astimezone(TIMEZONE)
    local_end = end.astimezone(TIMEZONE)
    return f"{local_start:%H:%M}–{local_end:%H:%M} {TIMEZONE.key}"


def _model_line(meta: ModelMeta) -> str:
    parts = [meta.tier, meta.model_id]
    if meta.provider_fallback:
        parts.append("fallback")
    if meta.local_fallback:
        parts.append("local")
    return f"<i>{' · '.join(parts)}</i>"


def _event_line(event: EmailEvent) -> str:
    sender = event.from_name or event.from_email or event.sender_domain or "Unknown sender"
    categories = ", ".join(escape(item) for item in event.categories[:3]) or "mail"
    attachment = ""
    if event.has_attachments:
        attachment = f" · вложения: {event.attachment_count}"
    return (
        f"• <b>{escape(sender)}</b> — {escape(event.subject)}\n"
        f"{escape(event.summary)}\n"
        f"<i>{categories}{attachment}</i>"
    )


def render_poll_batch(result: PollPrepResult, *, window_start: datetime, window_end: datetime) -> str:
    lines = [
        f"📬 <b>Inbox Email</b> | {_fmt_window(window_start, window_end)}",
        (
            f"• Новых тредов: <b>{result.threads_selected}</b> "
            f"из <b>{result.threads_considered}</b>; low-signal: <b>{result.low_signal_count}</b>."
        ),
    ]
    if result.batch_lead:
        lines.append("")
        lines.append("<b>Коротко</b>")
        lines.extend(f"• {escape(item)}" for item in result.batch_lead)

    if result.publish_events:
        lines.append("")
        lines.append("<b>Новые письма</b>")
        for idx, event in enumerate(result.publish_events):
            if idx:
                lines.append("")
            lines.append(_event_line(event))

    lines.append("")
    lines.append(_model_line(result.model_meta))
    return _sanitize_html("\n".join(lines).strip())


def _highlight_events(document: DigestPrepResult, events: list[EmailEvent]) -> list[EmailEvent]:
    by_id = {event.event_id: event for event in events}
    selected: list[EmailEvent] = [by_id[event_id] for event_id in document.important_event_ids if event_id in by_id]
    if selected:
        return selected[:5]
    return sorted(events, key=lambda item: item.importance, reverse=True)[:5]


def render_digest(document: DigestPrepResult, events: list[EmailEvent], *, window_start: datetime, window_end: datetime) -> str:
    lines = [
        f"📮 <b>{escape(document.title)}</b> | {escape(document.period_label or _fmt_window(window_start, window_end))}",
        f"• Окно: {_fmt_window(window_start, window_end)}",
        f"• Сигналов в derived buffer: <b>{len(events)}</b>",
    ]

    if document.lead:
        lines.append("")
        lines.append("<b>Главное</b>")
        lines.extend(f"• {escape(item)}" for item in document.lead)

    if document.themes:
        lines.append("")
        lines.append("<b>Темы</b>")
        lines.extend(f"• {escape(item)}" for item in document.themes)

    highlights = _highlight_events(document, events)
    if highlights:
        lines.append("")
        lines.append("<b>Ключевые треды</b>")
        for idx, event in enumerate(highlights):
            if idx:
                lines.append("")
            lines.append(_event_line(event))

    if document.actions:
        lines.append("")
        lines.append("<b>Действия</b>")
        lines.extend(f"• {escape(item)}" for item in document.actions)

    if document.watchpoints:
        lines.append("")
        lines.append("<b>Watchpoints</b>")
        lines.extend(f"• {escape(item)}" for item in document.watchpoints)

    if document.low_signal_recap:
        lines.append("")
        lines.append(f"<b>Low signal</b>\n• {escape(document.low_signal_recap)}")

    lines.append("")
    lines.append(_model_line(document.model_meta))
    return _sanitize_html("\n".join(lines).strip())


def _split_text(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        block = paragraph + "\n\n"
        if len(block) > MAX_MSG_LEN:
            if current:
                chunks.append(current.strip())
                current = ""
            for start in range(0, len(block), MAX_MSG_LEN):
                chunks.append(block[start : start + MAX_MSG_LEN].strip())
            continue
        if len(current) + len(block) > MAX_MSG_LEN:
            if current:
                chunks.append(current.strip())
            current = block
        else:
            current += block
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _apply_part_headers(chunks: list[str]) -> list[str]:
    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"<b>Часть {idx}/{total}</b>\n\n{chunk}" for idx, chunk in enumerate(chunks, start=1)]


async def post_html_message(text: str) -> bool:
    chunks = _apply_part_headers(_split_text(text))
    async with aiohttp.ClientSession() as session:
        for idx, chunk in enumerate(chunks, start=1):
            payload = {
                "chat_id": SUPERGROUP_ID,
                "message_thread_id": TOPIC_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                async with session.post(
                    f"{BASE_URL}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        logger.error("Telegram API error (chunk %s/%s): %s", idx, len(chunks), data)
                        return False
            except Exception as exc:
                logger.error("Failed to send chunk %s/%s: %s", idx, len(chunks), exc)
                return False
    return True
