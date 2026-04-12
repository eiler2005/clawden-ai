"""
Telegram posting helpers for signals mini-batches.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import aiohttp

from models import ModelMeta, SignalEvent

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SUPERGROUP_ID = int(os.environ["SIGNALS_SUPERGROUP_ID"])
TOPIC_ID = int(os.environ["SIGNALS_TOPIC_ID"])
TIMEZONE = ZoneInfo(os.environ.get("SIGNALS_TIMEZONE", "Europe/Moscow"))

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


def _fmt_dt(value: str) -> str:
    try:
        current = datetime.fromisoformat(value)
    except ValueError:
        return value
    return current.astimezone(TIMEZONE).strftime("%d.%m %H:%M")


def _model_line(meta: ModelMeta) -> str:
    parts = [meta.tier, meta.model_id]
    if meta.provider_fallback:
        parts.append("fallback")
    if meta.local_fallback:
        parts.append("local")
    return f"<i>{' · '.join(parts)}</i>"


def _compact_excerpt(text: str, limit: int = 420) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def render_batch(*, ruleset_title: str, events: list[SignalEvent], model_meta: ModelMeta) -> str:
    lines = [
        f"📡 <b>{escape(ruleset_title)}</b> | {len(events)} {_pluralize(len(events), 'сигнал', 'сигнала', 'сигналов')}",
    ]
    for event in sorted(events, key=lambda item: item.occurred_at):
        source_label = "email" if event.source_type == "email" else "telegram"
        tags = ", ".join(escape(tag) for tag in event.tags[:4])
        lines.append("")
        lines.append(
            f"• <b>{escape(event.title)}</b> <i>[{escape(source_label)} · {_fmt_dt(event.occurred_at)}]</i>"
        )
        lines.append(f"{escape(event.summary)}")
        if event.source_type == "email" and event.source_excerpt:
            lines.append(f"<i>Текст письма:</i> {escape(_compact_excerpt(event.source_excerpt))}")
        if event.source_type == "telegram" and event.source_link:
            lines.append(f"<i>Ссылка:</i> {escape(event.source_link)}")
        meta_line = f"<i>{escape(event.author)}"
        if tags:
            meta_line += f" · {tags}"
        meta_line += f" · conf {event.confidence:.2f}</i>"
        lines.append(meta_line)
    lines.append("")
    lines.append(_model_line(model_meta))
    return _sanitize_html("\n".join(lines).strip())


def _pluralize(count: int, one: str, few: str, many: str) -> str:
    n = abs(count) % 100
    if 10 < n < 20:
        return many
    n %= 10
    if n == 1:
        return one
    if 1 < n < 5:
        return few
    return many


def _split_text(text: str) -> list[str]:
    if len(text) <= MAX_MSG_LEN:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        block = paragraph + "\n\n"
        if len(current) + len(block) > MAX_MSG_LEN and current:
            chunks.append(current.strip())
            current = block
        else:
            current += block
    if current.strip():
        chunks.append(current.strip())
    return chunks


async def post_html_message(text: str) -> bool:
    chunks = _split_text(text)
    async with aiohttp.ClientSession() as session:
        for chunk in chunks:
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
                        logger.error("Telegram API error: %s", data)
                        return False
            except Exception as exc:
                logger.error("Failed to post signals batch: %s", exc)
                return False
    return True
