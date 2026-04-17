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
DISPLAY_NAME = os.environ.get("EMAIL_DIGEST_DISPLAY_NAME", "Inbox Email").strip() or "Inbox Email"
MORNING_TITLE = os.environ.get("EMAIL_DIGEST_MORNING_TITLE", "Morning brief").strip() or "Morning brief"
INTERVAL_TITLE = os.environ.get("EMAIL_DIGEST_INTERVAL_TITLE", "Regular digest").strip() or "Regular digest"
EDITORIAL_TITLE = os.environ.get("EMAIL_DIGEST_EDITORIAL_TITLE", "Evening editorial").strip() or "Evening editorial"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_MSG_LEN = 3900

_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "code", "pre"}
_TAG_RE = re.compile(r"<(/?)(\w+)([^>]*)>", re.IGNORECASE)
_URL_RE = re.compile(r"https?://\S+")
_REPLY_PREFIX_RE = re.compile(r"^\s*(?:(?:re|fw|fwd)\s*:\s*)+", re.IGNORECASE)
_FORWARDED_META_RE = re.compile(r"(?im)^\s*(?:from|sent|to|subject|от|отправлено|кому|тема)\s*:\s*.*$")
_SEPARATOR_RE = re.compile(r"[_-]{6,}")
_MODEL_LABELS = {
    "agentmail-direct": "без LLM",
    "openclaw": "GPT-5.4",
    "gpt-5.4": "GPT-5.4",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-haiku-4.5": "Claude Haiku 4.5",
    "gemini-2.0-flash": "Gemini 2.0 Flash",
}
_TIER_LABELS = {
    "primary": "OpenClaw primary",
    "smart": "OmniRoute smart",
    "medium": "OmniRoute medium",
    "light": "OmniRoute light",
}
_COMPLEXITY_LABELS = {
    "simple": "простая",
    "standard": "обычная",
    "complex": "сложная",
    "template": "шаблонный обзор",
}
_MEMORY_MODE_LABELS = {
    "memory": "память: включена",
    "mailbox-window": "контекст: окно почты",
    "no-memory": "память: без memory-файлов",
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
    route = _TIER_LABELS.get(meta.tier.strip() or "primary", meta.tier.strip() or "primary")
    label = (meta.model_label or _MODEL_LABELS.get(meta.model_id) or meta.model_id).strip()
    if meta.model_id == "agentmail-direct":
        route = "прямой рендер"
    if label == "OpenClaw Agent":
        label = "GPT-5.4"
    parts = [f"маршрут: {route}", f"модель: {label or 'неизвестно'}"]
    if meta.provider_fallback:
        parts.append("резервная модель")
    if meta.local_fallback:
        parts.append("локальный fallback")
    if meta.score_pct is not None:
        parts.append(f"контекст: {meta.score_pct}%")
    if meta.complexity:
        parts.append(f"сложность: {_COMPLEXITY_LABELS.get(meta.complexity, meta.complexity)}")
    if meta.memory_mode:
        parts.append(_MEMORY_MODE_LABELS.get(meta.memory_mode, f"контекст: {meta.memory_mode}"))
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
        f"📬 <b>{escape(DISPLAY_NAME)}</b> | {_fmt_window(window_start, window_end)}",
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
        "morning": f"{DISPLAY_NAME} · {MORNING_TITLE}",
        "interval": f"{DISPLAY_NAME} · {INTERVAL_TITLE}",
        "editorial": f"{DISPLAY_NAME} · {EDITORIAL_TITLE}",
    }
    return titles.get(digest_type, DISPLAY_NAME)


def _sender_counts(messages: list[dict]) -> list[tuple[str, int]]:
    counter = Counter()
    for message in messages:
        sender = _normalize_sender_text(message.get("sender_display"))
        counter[sender] += 1
    return sorted(counter.items(), key=lambda item: (-item[1], item[0].lower()))


def _message_line(message: dict, *, include_preview: bool) -> list[str]:
    sender = _normalize_sender_text(message.get("sender_display"))
    timestamp = _fmt_clock(str(message.get("timestamp") or ""))
    summary = _message_summary(message, limit=170)
    attachment = ""
    if message.get("has_attachments"):
        attachment = f" Вложения: {int(message.get('attachment_count') or 0)}."
    lines = [f"• {timestamp} — <b>{escape(sender)}</b> — {escape(summary)}{escape(attachment)}"]
    if include_preview:
        preview = _message_snippet(message, limit=110)
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


def _clean_subject(subject: str | None) -> str:
    value = _compact_text(subject, limit=180)
    value = _REPLY_PREFIX_RE.sub("", value).strip()
    value = re.sub(r"^[^\wА-Яа-я0-9]+", "", value)
    return value.strip()


def _clean_preview_text(value: str | None, *, limit: int) -> str:
    text = str(value or "")
    text = _FORWARDED_META_RE.sub(" ", text)
    text = _SEPARATOR_RE.sub(" ", text)
    return _compact_text(text, limit=limit)


def _normalized_compare(value: str) -> str:
    return re.sub(r"[^a-zа-я0-9]+", "", value.lower())


def _ensure_sentence(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if text[-1] in ".!?…":
        return text
    return text + "."


def _capitalize_first(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _normalize_sender_text(value: str | None) -> str:
    sender = _compact_text(value, limit=160)
    if not sender:
        return "Unknown sender"
    sender = re.sub(r"(?<=[A-Za-zА-Яа-я])(?=(?:от имени|От имени))", " ", sender)
    sender = re.sub(r"(?<=[a-zа-я])(?=[A-ZА-Я])", " ", sender)
    sender = re.sub(r"(?<=[A-ZА-Я])(?=[A-ZА-Я][a-zа-я])", " ", sender)
    sender = re.sub(r"\bОт имени\b", "от имени", sender)
    sender = re.sub(r"\s+", " ", sender).strip()
    return sender or "Unknown sender"


def _sender_label(message: dict, *, include_email: bool) -> str:
    sender = _normalize_sender_text(message.get("sender_display"))
    if not include_email:
        return sender
    email = str(message.get("from_email") or "").strip()
    if not email:
        return sender
    if sender.lower() == email.lower():
        return email
    if email.lower() in sender.lower():
        return sender
    return f"{sender} ({email})"


def _strip_greeting(text: str) -> str:
    return re.sub(r"^(?:коллеги|добрый день|доброе утро|добрый вечер)[,!\s]+", "", text, flags=re.IGNORECASE).strip()


def _strip_copy_block(text: str) -> str:
    text = str(text or "")
    cleaned = re.sub(
        r"(?is)\bкопия\s*:\s*.*?(?=(?:коллеги|добрый день|доброе утро|добрый вечер|уважаемые|денис[,!\s]|$))",
        " ",
        text,
    )
    cleaned = re.sub(
        r"(?is)\bcc\s*:\s*.*?(?=(?:hello|hi|dear|коллеги|добрый день|доброе утро|добрый вечер|$))",
        " ",
        cleaned,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def _compact_clauses(text: str, *, limit: int = 170) -> str:
    cleaned = _strip_greeting(_strip_copy_block(text))
    parts = [part.strip(" ,;") for part in re.split(r"[.!?]+", cleaned) if part.strip(" ,;")]
    if not parts:
        return _compact_text(cleaned, limit=limit)
    summary = parts[0]
    if len(parts) > 1 and len(summary) < limit - 40:
        summary = f"{summary}; {parts[1]}"
    return _ensure_sentence(_capitalize_first(_compact_text(summary, limit=limit)))


def _extract_subject_date_range(subject: str) -> str:
    match = re.search(r"(\d{1,2}\s*[-–]\s*\d{1,2}\s+[А-Яа-яA-Za-z]+)", subject)
    if not match:
        return ""
    return re.sub(r"\s*[-–]\s*", "–", match.group(1).strip())


def _calendar_title(subject: str) -> str:
    title = subject
    if ":" in title:
        title = title.split(":", 1)[1].strip()
    title = re.sub(r"\s+@\s+Weekly.*$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s+@\s+(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b.*$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s*\([^)]+@[^)]+\)\s*$", "", title).strip()
    return _clean_subject(title)


def _calendar_message_summary(subject: str) -> str:
    title = _calendar_title(subject)
    if not title:
        return "Обновлён инвайт на встречу."
    return f"Обновлён инвайт на встречу «{title}»."


def _calendar_update_summary(subject: str) -> str:
    title = _calendar_title(subject)
    if not title:
        return "обновлён или переотправлен инвайт на встречу."
    return f"Обновлён или переотправлен инвайт на встречу «{title}»."


def _vacation_summary(subject: str, preview: str) -> str:
    date_range = _extract_subject_date_range(subject)
    contact_hint = ""
    preview_lower = preview.lower()
    if "срочн" in preview_lower and ("телефон" in preview_lower or "звон" in preview_lower):
        contact_hint = "по срочным вопросам лучше звонить"
    teams_hint = ""
    if "vk teams" in preview_lower:
        teams_hint = "в VK Teams будет появляться нерегулярно"

    parts: list[str] = []
    if date_range:
        parts.append(f"будет в отпуске {date_range}")
    else:
        parts.append("сообщил об отпуске")
    if contact_hint:
        parts.append(contact_hint)
    if teams_hint:
        parts.append(teams_hint)
    return _ensure_sentence(_capitalize_first("; ".join(parts)))


def _extract_project_code(text: str) -> str:
    match = re.search(r"\b(?:ПР|PR)[-\s]?\d{2,6}\b", text, flags=re.IGNORECASE)
    if not match:
        return ""
    value = match.group(0).upper().replace(" ", "-")
    if value.startswith("PR"):
        return value
    return value.replace("ПР", "ПР")


def _extract_role_label(text: str) -> str:
    role_patterns = [
        (r"\b(?:бизнес[-\s]?аналитик|business analyst|системн(?:ый|ого)? аналитик|аналитик)\b", "аналитик"),
        (r"\b(?:разработчик|developer|backend|frontend|fullstack)\b", "разработчик"),
        (r"\b(?:qa|qc|тестировщик)\b", "тестировщик"),
        (r"\b(?:devops)\b", "DevOps"),
        (r"\b(?:архитектор|architect)\b", "архитектор"),
        (r"\b(?:pm|project manager|менеджер проекта|руководитель проекта)\b", "менеджер проекта"),
        (r"\b(?:дизайнер|designer)\b", "дизайнер"),
    ]
    lowered = text.lower()
    for pattern, label in role_patterns:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return label
    return ""


def _resource_request_summary(subject: str, preview: str) -> str:
    haystack = " ".join([subject, preview])
    lowered = haystack.lower()
    if not any(token in lowered for token in ["ресурс", "ресурсы", "требуется", "нужен", "нужна", "нужны", "аналитик", "разработчик", "тестировщик"]):
        return ""
    project_code = _extract_project_code(haystack)
    role_label = _extract_role_label(haystack)
    if project_code and role_label:
        return f"Запрос на усиление команды по {project_code}: требуется {role_label}."
    if role_label:
        return f"Запрос на усиление команды: требуется {role_label}."
    if project_code:
        return f"Запрос по ресурсам для {project_code}."
    return ""


def _message_summary(message: dict, *, limit: int = 170) -> str:
    subject = _clean_subject(str(message.get("subject") or ""))
    snippet = _clean_preview_text(_strip_copy_block(message.get("preview")), limit=limit)
    lowered = " ".join([subject, snippet]).lower()
    if "updated invitation" in lowered:
        return _calendar_message_summary(subject)
    resource_summary = _resource_request_summary(subject, snippet)
    if resource_summary:
        return resource_summary
    if not subject and not snippet:
        return "(no subject)"
    if not subject:
        return _ensure_sentence(snippet)
    if not snippet:
        return _ensure_sentence(subject)

    normalized_subject = _normalized_compare(subject)
    normalized_snippet = _normalized_compare(snippet)
    if not normalized_snippet:
        return _ensure_sentence(subject)
    if normalized_subject and (normalized_snippet in normalized_subject or normalized_subject in normalized_snippet):
        return _ensure_sentence(subject)
    if len(normalized_subject) < 14:
        return _ensure_sentence(snippet)
    return _ensure_sentence(f"{subject}. {snippet}")


def _important_summary(message: dict, *, limit: int = 170) -> str:
    subject = _clean_subject(str(message.get("subject") or ""))
    preview = _clean_preview_text(_strip_copy_block(message.get("preview")), limit=260)
    lowered = " ".join([subject, preview]).lower()

    if "updated invitation" in lowered:
        return _calendar_update_summary(subject)
    if "отпуск" in lowered:
        return _vacation_summary(subject, preview)
    resource_summary = _resource_request_summary(subject, preview)
    if resource_summary:
        return resource_summary
    if preview:
        return _compact_clauses(preview, limit=limit)
    return _message_summary(message, limit=limit)


def _message_snippet(message: dict, *, limit: int = 120) -> str:
    preview = _clean_preview_text(message.get("preview"), limit=limit)
    if not preview:
        return ""
    preview = preview.replace("View this post on the web at", "Web:")
    preview = preview.replace("|", " · ")
    return _compact_text(preview, limit=limit)


def _important_line(message: dict) -> str:
    sender = _sender_label(message, include_email=True)
    timestamp = _fmt_clock(str(message.get("timestamp") or ""))
    summary = _important_summary(message, limit=170)
    return f"• {timestamp} — <b>{escape(sender)}</b> — {escape(summary)}"


def _supporting_insights(messages: list[dict], *, limit: int = 2) -> list[str]:
    low_signal_messages = [message for message in messages if bool(message.get("is_low_signal"))]
    if not low_signal_messages:
        return []

    senders = [_normalize_sender_text(message.get("sender_display")) for message in low_signal_messages]
    top_senders = ", ".join(escape(sender) for sender, _ in Counter(senders).most_common(3))
    low_signal_count = len(low_signal_messages)
    low_signal_label = _ru_plural(low_signal_count, "low-signal письмо", "low-signal письма", "low-signal писем")
    lines = [f"• Остальной фон окна: {low_signal_count} {low_signal_label}, в основном от {top_senders}."]

    if len(messages) > len(low_signal_messages):
        important_senders = len(
            {
                _normalize_sender_text(message.get("sender_display"))
                for message in messages
                if not bool(message.get("is_low_signal"))
            }
        )
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
        sender = _normalize_sender_text(message.get("sender_display"))
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

    lines.append("")
    lines.append("<b>Письма</b>")
    visible_messages = messages[:12]
    remaining_messages = messages[12:]
    for message in visible_messages:
        lines.extend(_message_line(message, include_preview=False))
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
