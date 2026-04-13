"""
Telegram posting helpers for inbox-email poll batches and digests.
"""
from __future__ import annotations

from collections import Counter
import logging
import os
import re
from datetime import datetime
from html import escape, unescape
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
_URL_RE = re.compile(r"https?://\S+")
_MODEL_LABELS = {
    "agentmail-direct": "OpenClaw Agent",
    "openclaw": "OpenClaw Agent",
}
_TAIL_TOPIC_RULES = [
    ("чеки", ["чек", "receipt", "invoice"]),
    ("подарки", ["подарок", "gift", "bonus"]),
    ("отмены", ["отмен", "cancel", "cancellation"]),
    ("возвраты", ["возврат", "refund", "returned money"]),
    ("покупки", ["order", "заказ", "ozon"]),
    ("вакансии", ["ваканс", "job", "hiring", "career opportunity"]),
    ("карьера", ["карьер", "career", "interview", "resume", "cv", "linkedin", "invitation", "message", "network", "getmatch"]),
    ("инвестиции", ["инвест", "broker", "finance", "market", "spx", "trade", "trading", "finam", "aton", "mancini", "wall st"]),
    ("обучение", ["course", "skill", "learn", "training", "study", "education", "edx", "vocabulary", "bytebytego"]),
    ("промо", ["sale", "discount", "promo", "new collection", "new arrival", "капсула", "поступление", "giglio", "brandshop", "lime shop"]),
    ("доставка", ["delivery", "shipment", "tracking", "order shipped"]),
    ("банкинг", ["bank", "card", "payment", "счёт", "счет", "пополнен", "payment received"]),
    ("дайджесты", ["newsletter", "digest", "weekly", "substack", "bitly"]),
    ("сервисы", ["grammarly", "uber", "bitly"]),
]


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


def _fmt_clock(value: str | None) -> str:
    if not value:
        return "--:--"
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return "--:--"
    return dt.astimezone(TIMEZONE).strftime("%H:%M")


def _model_line(meta: ModelMeta) -> str:
    label = (meta.model_label or _MODEL_LABELS.get(meta.model_id) or meta.model_id).strip()
    route = meta.tier.strip() or "primary"
    parts = [f"{route} ({label})" if label else route]
    if meta.provider_fallback:
        parts.append("fallback")
    if meta.local_fallback:
        parts.append("local")
    if meta.score_pct is not None:
        parts.append(f"{meta.score_pct}%")
    if meta.complexity:
        parts.append(meta.complexity)
    if meta.memory_mode:
        parts.append(meta.memory_mode)
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
            f"• Всего писем в окне: <b>{result.messages_scanned}</b>; "
            f"новых тредов: <b>{result.threads_selected}</b> из <b>{result.threads_considered}</b>; "
            f"low-signal: <b>{result.low_signal_count}</b>."
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


def _digest_title(digest_type: str) -> str:
    titles = {
        "morning": "Inbox Email · Morning brief",
        "interval": "Inbox Email · Regular digest",
        "editorial": "Inbox Email · Evening editorial",
    }
    return titles.get(digest_type, "Inbox Email")


def _sender_counts(messages: list[dict]) -> list[tuple[str, int]]:
    counter = Counter()
    for message in messages:
        sender = str(message.get("sender_display") or "Unknown sender").strip() or "Unknown sender"
        counter[sender] += 1
    return sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))


def _message_line(message: dict, *, include_preview: bool) -> list[str]:
    sender = str(message.get("sender_display") or "Unknown sender").strip() or "Unknown sender"
    subject = str(message.get("subject") or "(no subject)").strip() or "(no subject)"
    timestamp = _fmt_clock(str(message.get("timestamp") or ""))
    attachment = ""
    if message.get("has_attachments"):
        attachment = f" · вложения: {int(message.get('attachment_count') or 0)}"
    lines = [f"• {timestamp} — <b>{escape(sender)}</b> — {escape(subject)}{attachment}"]
    if include_preview:
        preview = str(message.get("preview") or "").strip()
        if preview:
            lines.append(escape(preview))
    return lines


def _compact_text(value: str | None, *, limit: int) -> str:
    text = unescape(str(value or ""))
    text = text.replace("\xa0", " ").replace("\u200c", " ").replace("&zwnj;", " ")
    text = _URL_RE.sub("", text)
    text = " ".join(text.split())
    if not re.search(r"[A-Za-zА-Яа-я0-9]", text):
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _message_snippet(message: dict, *, limit: int = 120) -> str:
    preview = str(message.get("preview") or "").strip()
    if not preview:
        return ""
    preview = preview.replace("View this post on the web at", "Web:")
    preview = preview.replace("|", " · ")
    return _compact_text(preview, limit=limit)


def _important_line(message: dict) -> str:
    sender = str(message.get("sender_display") or "Unknown sender").strip() or "Unknown sender"
    subject = str(message.get("subject") or "(no subject)").strip() or "(no subject)"
    timestamp = _fmt_clock(str(message.get("timestamp") or ""))
    snippet = _message_snippet(message, limit=150)
    if snippet:
        return f"• {timestamp} — <b>{escape(sender)}</b>: {escape(subject)}. {escape(snippet)}"
    return f"• {timestamp} — <b>{escape(sender)}</b>: {escape(subject)}."


def _supporting_insights(messages: list[dict], *, limit: int = 2) -> list[str]:
    low_signal_messages = [message for message in messages if bool(message.get("is_low_signal"))]
    if not low_signal_messages:
        return []

    senders = [str(message.get("sender_display") or "Unknown sender").strip() or "Unknown sender" for message in low_signal_messages]
    top_senders = ", ".join(escape(sender) for sender, _ in Counter(senders).most_common(3))
    lines = [f"• Остальной фон окна: {len(low_signal_messages)} low-signal писем, в основном от {top_senders}."]

    if len(messages) > len(low_signal_messages):
        important_senders = len({str(message.get('sender_display') or '').strip() for message in messages if not bool(message.get('is_low_signal')) and str(message.get('sender_display') or '').strip()})
        useful_count = len(messages) - len(low_signal_messages)
        useful_label = "более полезное письмо" if useful_count == 1 else "более полезных письма" if useful_count < 5 else "более полезных писем"
        sender_label = "отправителя" if important_senders == 1 else "отправителей"
        lines.append(f"• Помимо шума, в окне было {useful_count} {useful_label} от {important_senders} {sender_label}.")

    return lines[:limit]


def _compact_subject(subject: str, *, limit: int = 42) -> str:
    return _compact_text(subject, limit=limit)


def _ru_plural(count: int, one: str, few: str, many: str) -> str:
    rem100 = count % 100
    rem10 = count % 10
    if rem10 == 1 and rem100 != 11:
        return one
    if rem10 in {2, 3, 4} and rem100 not in {12, 13, 14}:
        return few
    return many


def _tail_topics(messages: list[dict], *, limit: int = 4) -> list[str]:
    counter: Counter[str] = Counter()
    for message in messages:
        haystack = " ".join(
            [
                str(message.get("subject") or ""),
                str(message.get("preview") or ""),
                str(message.get("sender_display") or ""),
            ]
        ).lower()
        matched = False
        for label, tokens in _TAIL_TOPIC_RULES:
            if any(token in haystack for token in tokens):
                counter[label] += 1
                matched = True
        if not matched:
            counter["прочее"] += 1
    ordered = [label for label, _ in counter.most_common()]
    if "прочее" in ordered and len(ordered) > 1:
        ordered = [label for label in ordered if label != "прочее"]
    return ordered[:limit]


def _tail_sender_names(messages: list[dict], *, limit: int = 4) -> list[str]:
    return [sender for sender, _ in _sender_counts(messages)[:limit]]


def _remaining_tail_summary(messages: list[dict]) -> str:
    if not messages:
        return ""
    total = len(messages)
    topics = _tail_topics(messages, limit=4)
    senders = _tail_sender_names(messages, limit=4)
    total_senders = len(_sender_counts(messages))
    topics_text = ", ".join(escape(topic) for topic in topics)
    senders_text = ", ".join(escape(sender) for sender in senders)
    sender_suffix = " и других" if total_senders > len(senders) else ""
    return (
        f"остальные {total} — письма на темы: {topics_text} "
        f"от {senders_text}{sender_suffix}"
    )


def _topics_summary_for_messages(messages: list[dict], *, limit: int = 4) -> list[str]:
    return _tail_topics(messages, limit=limit)


def _remaining_messages_line(messages: list[dict]) -> str:
    if not messages:
        return ""

    grouped: dict[str, list[dict]] = {}
    for message in messages:
        sender = str(message.get("sender_display") or "Unknown sender").strip() or "Unknown sender"
        grouped.setdefault(sender, []).append(message)

    ordered = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].lower()))
    parts: list[str] = []
    covered_messages = 0
    covered_senders = 0

    for sender, sender_messages in ordered[:3]:
        covered_messages += len(sender_messages)
        covered_senders += 1
        subjects: list[str] = _topics_summary_for_messages(sender_messages, limit=4)
        if not subjects:
            seen_subjects: set[str] = set()
            fallback_subjects: list[str] = []
            for message in sender_messages:
                subject = str(message.get("subject") or "(no subject)").strip() or "(no subject)"
                normalized = subject.lower()
                if normalized in seen_subjects:
                    continue
                seen_subjects.add(normalized)
                compact = _compact_subject(subject, limit=32)
                if compact:
                    fallback_subjects.append(compact)
                if len(fallback_subjects) == 3:
                    break
            subjects = fallback_subjects
        topic_suffix = ""
        if subjects:
            topic_suffix = f" ({', '.join(escape(subject) for subject in subjects)})"
        parts.append(f"{escape(sender)} — {len(sender_messages)}{topic_suffix}")

    remaining_messages = len(messages) - covered_messages
    remaining_senders = len(grouped) - covered_senders
    if remaining_messages > 0 and remaining_senders > 0:
        tail_messages = [
            message
            for _, sender_messages in ordered[covered_senders:]
            for message in sender_messages
        ]
        tail_summary = _remaining_tail_summary(tail_messages)
        if tail_summary:
            parts.append(tail_summary)

    total = len(messages)
    return f"• Ещё {total} {_ru_plural(total, 'письмо', 'письма', 'писем')}: " + "; ".join(parts)


def render_mailbox_digest(
    *,
    digest_type: str,
    window_start: datetime,
    window_end: datetime,
    messages: list[dict],
    important_messages: list[dict],
    model_meta: ModelMeta,
) -> str:
    total_threads = len({str(message.get("thread_id") or "") for message in messages if str(message.get("thread_id") or "").strip()})
    total_senders = len(_sender_counts(messages))
    low_signal_count = sum(1 for message in messages if bool(message.get("is_low_signal")))

    lines = [
        f"📮 <b>{escape(_digest_title(digest_type))}</b> | {_fmt_window(window_start, window_end)}",
        f"• Окно: {_fmt_window(window_start, window_end)}",
        f"• Всего писем: <b>{len(messages)}</b>",
        f"• Всего тредов: <b>{total_threads}</b>",
        f"• Отправителей: <b>{total_senders}</b>",
        f"• Важных: <b>{len(important_messages)}</b> · low-signal: <b>{low_signal_count}</b>",
    ]

    if not messages:
        lines.append("")
        lines.append("<b>Главное</b>")
        lines.append("• Новых писем за это окно не было.")
        lines.append("")
        lines.append(_model_line(model_meta))
        return _sanitize_html("\n".join(lines).strip())

    sender_counts = _sender_counts(messages)
    lines.append("")
    lines.append("<b>От кого</b>")
    for sender, count in sender_counts[:10]:
        suffix = "писем" if count != 1 else "письмо"
        lines.append(f"• <b>{escape(sender)}</b> — {count} {suffix}")
    if len(sender_counts) > 10:
        lines.append(f"• Ещё отправителей: {len(sender_counts) - 10}")

    lines.append("")
    lines.append("<b>Письма</b>")
    visible_messages = messages[:12]
    remaining_messages = messages[12:]
    for message in visible_messages:
        lines.extend(_message_line(message, include_preview=False))
        snippet = _message_snippet(message, limit=110)
        if snippet:
            lines.append(escape(snippet))
    if remaining_messages:
        remaining_line = _remaining_messages_line(remaining_messages)
        if remaining_line:
            lines.append(remaining_line)

    lines.append("")
    lines.append("<b>Что важного</b>")
    if important_messages:
        for line in [_important_line(message) for message in important_messages[:4]]:
            lines.append(line)
        for line in _supporting_insights(messages):
            lines.append(line)
    else:
        for line in _supporting_insights(messages, limit=3):
            lines.append(line)
        if lines[-1] == "<b>Что важного</b>":
            lines.append("• Явно важных писем в этом окне не вижу.")

    lines.append("")
    lines.append(_model_line(model_meta))
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
