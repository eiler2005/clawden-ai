"""
Persist processed digests into an Obsidian subtree and optionally promote
durable signals into curated notes for LightRAG.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

import aiohttp

from models import CuratedDigestNote, DigestDocument, DigestItem
from omniroute_client import call_chat_completion, extract_json_payload, has_markdown_fences

logger = logging.getLogger(__name__)

LIGHTRAG_URL = os.environ.get("LIGHTRAG_URL", "http://lightrag:9621")
OBSIDIAN_OUTPUT_DIR = os.environ.get("OBSIDIAN_OUTPUT_DIR", "/app/obsidian")
OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://omniroute:20129/v1")
OMNIROUTE_API_KEY = os.environ.get("OMNIROUTE_API_KEY", "")
CURATION_MODEL = "medium"


def _persistence_cfg(config: dict) -> dict:
    current = config.get("persistence", {}) or {}
    return {
        "enabled": current.get("enabled", True),
        "obsidian_root": current.get("obsidian_root", "Telegram Digest"),
        "persist_digest_types": current.get("persist_digest_types", ["interval", "editorial"]),
        "curation_enabled": current.get("curation_enabled", True),
        "immediate_lightrag_ingest": current.get("immediate_lightrag_ingest", True),
    }


def _obsidian_root(config: dict) -> Path:
    base = Path(OBSIDIAN_OUTPUT_DIR)
    relative = str(_persistence_cfg(config).get("obsidian_root", "Telegram Digest")).strip()
    if relative in {"", ".", "./"}:
        return base
    return base / relative


def _slugify(value: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^\wА-Яа-я.-]+", "-", value, flags=re.UNICODE).strip("-_.")
    return (slug or "note")[:max_len]


def _collect_reference_urls(document: DigestDocument) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()

    def _push(url: str | None):
        if url and url not in seen:
            seen.add(url)
            refs.append(url)

    for item in document.new_glance:
        _push(item.post_url)
        for extra_url in item.extra_post_urls:
            _push(extra_url)
        _push(item.channel_url)
    for item in document.must_read:
        _push(item.post_url)
        for extra_url in item.extra_post_urls:
            _push(extra_url)
        _push(item.channel_url)
    for section in document.sections:
        _push(section.folder_link)
        for item in section.items:
            _push(item.post_url)
            for extra_url in item.extra_post_urls:
                _push(extra_url)
            _push(item.channel_url)
    return refs


def _markdown_post_links(item: DigestItem) -> str:
    urls = [item.post_url, *item.extra_post_urls]
    arrows = [f"[→]({url})" for url in urls if url]
    if not arrows:
        return ""
    if len(arrows) == 1:
        return arrows[0]
    return f"({', '.join(arrows)})"


def _pluralize(count: int, one: str, few: str, many: str) -> str:
    mod10 = count % 10
    mod100 = count % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if mod10 in {2, 3, 4} and mod100 not in {12, 13, 14}:
        return few
    return many


def _message_count(item: DigestItem) -> int:
    return 1 + len(item.extra_post_urls)


def _section_message_count(section) -> int:
    return sum(_message_count(item) for item in section.items)


def _render_markdown_item(item: DigestItem) -> str:
    pin = "📌 " if item.pinned else ""
    links = _markdown_post_links(item)
    message_count = _message_count(item)
    return (
        f"**{pin}{item.channel}** · {message_count} "
        f"{_pluralize(message_count, 'сообщение', 'сообщения', 'сообщений')}\n"
        f"{item.summary} {links}"
    ).rstrip()


def _render_markdown_lead(item: str) -> str:
    match = re.match(r"^([^:]{2,80}):\s*(.+)$", re.sub(r"\s+", " ", item or "").strip())
    if not match:
        return f"- {item}"
    channel, summary = match.group(1), match.group(2)
    return f"- **{channel}**: {summary}"


def _shown_post_count(document: DigestDocument) -> int:
    seen: set[str] = set()
    for item in document.new_glance:
        if item.post_url:
            seen.add(item.post_url)
        for extra_url in item.extra_post_urls:
            seen.add(extra_url)
    for item in document.must_read:
        if item.post_url:
            seen.add(item.post_url)
        for extra_url in item.extra_post_urls:
            seen.add(extra_url)
    for section in document.sections:
        for item in section.items:
            if item.post_url:
                seen.add(item.post_url)
            for extra_url in item.extra_post_urls:
                seen.add(extra_url)
    return len(seen)


def _story_count(document: DigestDocument) -> int:
    section_items = sum(len(section.items) for section in document.sections)
    if section_items:
        return section_items
    return len(document.must_read) + len(document.new_glance)


def render_digest_markdown(document: DigestDocument) -> str:
    active_channels = document.stats.active_channels_seen or document.stats.channels_in_scope
    lines = [
        f"# {document.title} | {document.period_label} ({active_channels} {_pluralize(active_channels, 'канал', 'канала', 'каналов')}, {document.stats.posts_selected} {_pluralize(document.stats.posts_selected, 'пост', 'поста', 'постов')})",
        "",
    ]

    if document.digest_type == "editorial" and document.executive_summary:
        lines.append("## Executive summary")
        lines.extend(f"- {item}" for item in document.executive_summary)
        lines.append("")

    if document.lead:
        lines.append("## Главное")
        lines.extend(_render_markdown_lead(item) for item in document.lead)
        lines.append("")

    if document.themes:
        lines.append("## Пульс дня")
        lines.extend(f"- {item}" for item in document.themes)
        lines.append("")

    if document.new_glance:
        lines.append(
            f"## Новое · обработано {document.stats.new_posts_seen} "
            f"{_pluralize(document.stats.new_posts_seen, 'сообщение', 'сообщения', 'сообщений')}"
        )
        for item in document.new_glance:
            lines.append(_render_markdown_item(item))
            lines.append("")
        lines.append("")

    if document.must_read and document.digest_type in {"morning", "editorial"}:
        lines.append("## Must read")
        for item in document.must_read:
            lines.append(_render_markdown_item(item))
            lines.append("")
        lines.append("")

    if document.sections:
        lines.append("## Папки")
        for section in document.sections:
            if section.folder_link:
                lines.append(
                    f"### [{section.folder}]({section.folder_link}) · "
                    f"{len(section.items)} {_pluralize(len(section.items), 'канал', 'канала', 'каналов')} / "
                    f"{_section_message_count(section)} {_pluralize(_section_message_count(section), 'сообщение', 'сообщения', 'сообщений')}"
                )
            else:
                lines.append(
                    f"### {section.folder} · "
                    f"{len(section.items)} {_pluralize(len(section.items), 'канал', 'канала', 'каналов')} / "
                    f"{_section_message_count(section)} {_pluralize(_section_message_count(section), 'сообщение', 'сообщения', 'сообщений')}"
                )
            for item in section.items:
                lines.append(_render_markdown_item(item))
                lines.append("")
            lines.append("")

    if document.low_signal:
        lines.append("## Low signal")
        lines.extend(f"- {item}" for item in document.low_signal)
        lines.append("")

    if document.watchpoints:
        lines.append("## Watchpoints")
        lines.extend(f"- {item}" for item in document.watchpoints)
        lines.append("")

    lines.append("## Итоги")
    lines.append(
        f"- Просмотрено {document.stats.new_posts_seen} новых постов из {document.stats.channels_in_scope} каналов в скоупе."
    )
    shown_posts = _shown_post_count(document)
    reserve = max(document.stats.posts_selected - shown_posts, 0)
    lines.append(
        f"- В выпуск вошло {_story_count(document)} сюжетов и {shown_posts} прямых ссылок на посты; в резерве осталось около {reserve} сигналов."
    )
    if document.quiet_folders:
        lines.append(f"- В финальный обзор не вошли папки: {', '.join(document.quiet_folders)}.")
    lines.append("")

    references = _collect_reference_urls(document)
    if references:
        lines.append("## Source references")
        lines.extend(f"- {url}" for url in references)
        lines.append("")

    lines.append(
        f"_Model: {document.model_meta.tier} · {document.model_meta.model_id}"
        f"{' · local fallback' if document.model_meta.local_fallback else ''}_"
    )
    return "\n".join(lines).strip() + "\n"


def _frontmatter_lines(document: DigestDocument, period_start: datetime, period_end: datetime) -> list[str]:
    folders = [section.folder for section in document.sections]
    lines = [
        "---",
        f"type: {document.digest_type}",
        f"date: {period_end.date().isoformat()}",
        f"period_start: {period_start.isoformat()}",
        f"period_end: {period_end.isoformat()}",
        "folders:",
    ]
    if folders:
        lines.extend(f"  - {folder}" for folder in folders)
    else:
        lines.append("  - none")
    lines.extend(
        [
            f"channels_in_scope: {document.stats.channels_in_scope}",
            f"new_posts_seen: {document.stats.new_posts_seen}",
            f"posts_selected: {document.stats.posts_selected}",
            f"model: {document.model_meta.model_id}",
            f"fallback: {'true' if document.model_meta.local_fallback else 'false'}",
            "source: telegram-digest",
            "rag_eligible: true",
            "---",
            "",
        ]
    )
    return lines


def _derived_note_path(root: Path, document: DigestDocument, period_start: datetime, period_end: datetime) -> Path:
    directory = root / "Derived" / period_end.strftime("%Y-%m-%d")
    slug = f"{document.digest_type}-{period_start.strftime('%H%M')}-{period_end.strftime('%H%M')}"
    return directory / f"{slug}.md"


def _curated_note_path(root: Path, note: CuratedDigestNote) -> Path:
    directory = root / "Curated" / note.date
    return directory / f"{_slugify(note.title)}.md"


def _is_high_signal_interval(document: DigestDocument) -> bool:
    if document.must_read:
        return True
    for section in document.sections:
        if section.tier.upper() != "A":
            continue
        if any(item.kind.lower() != "low_signal" for item in section.items):
            return True
    return False


def should_persist_digest(document: DigestDocument, config: dict) -> bool:
    cfg = _persistence_cfg(config)
    if not cfg.get("enabled", False):
        return False
    allowed_types = set(cfg.get("persist_digest_types", ["interval", "editorial"]))
    if document.digest_type not in allowed_types:
        return False
    if document.digest_type == "editorial":
        return True
    if document.digest_type == "interval":
        return _is_high_signal_interval(document)
    return False


def _validate_curated_note(payload: dict) -> CuratedDigestNote:
    if not isinstance(payload, dict):
        raise ValueError("Curated note must be an object")

    def _require_string(field_name: str, default: str = "") -> str:
        value = payload.get(field_name, default)
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            raise ValueError(f"{field_name} is empty")
        return value

    def _string_list(field_name: str) -> list[str]:
        value = payload.get(field_name, [])
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list")
        result: list[str] = []
        for item in value[:8]:
            if not isinstance(item, str):
                raise ValueError(f"{field_name} items must be strings")
            cleaned = re.sub(r"\s+", " ", item).strip()
            if cleaned:
                result.append(cleaned)
        return result

    sensitivity = _require_string("sensitivity", "low").lower()
    if sensitivity not in {"low", "medium", "high"}:
        sensitivity = "medium"

    return CuratedDigestNote(
        title=_require_string("title"),
        domain=_require_string("domain"),
        source=_require_string("source"),
        date=_require_string("date"),
        summary=_require_string("summary"),
        claims=_string_list("claims"),
        decision=payload.get("decision", "") if isinstance(payload.get("decision", ""), str) else "",
        next_actions=_string_list("next_actions"),
        sensitivity=sensitivity,
        references=_string_list("references"),
    )


def _render_curated_note_markdown(note: CuratedDigestNote) -> str:
    lines = [
        "---",
        "type: curated-telegram-digest-note",
        f"title: {note.title}",
        f"domain: {note.domain}",
        f"date: {note.date}",
        f"source: {note.source}",
        f"sensitivity: {note.sensitivity}",
        "rag_eligible: true",
        "---",
        "",
        f"# {note.title}",
        "",
        f"**Summary:** {note.summary}",
        "",
    ]
    if note.claims:
        lines.append("## Claims")
        lines.extend(f"- {claim}" for claim in note.claims)
        lines.append("")
    if note.decision:
        lines.append("## Decision")
        lines.append(note.decision)
        lines.append("")
    if note.next_actions:
        lines.append("## Next actions")
        lines.extend(f"- {item}" for item in note.next_actions)
        lines.append("")
    if note.references:
        lines.append("## References")
        lines.extend(f"- {item}" for item in note.references)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


async def _extract_curated_notes(document: DigestDocument, config: dict) -> list[CuratedDigestNote]:
    cfg = _persistence_cfg(config)
    if not cfg.get("curation_enabled", False):
        return []
    if document.model_meta.local_fallback:
        return []

    system = (
        "Ты выделяешь из уже обработанного Telegram digest только долговечные, "
        "переиспользуемые знания. Возвращай только JSON-массив заметок или пустой массив []. "
        "Не включай commodity headlines, одноразовый шум, low-signal commentary. "
        "Подходящие заметки: сильные рыночные сигналы, durable work/AI/startup/fintech/property/"
        "career takeaways, повторяющиеся темы, полезные watchpoints. "
        "Каждый объект: title, domain, source, date, summary, claims[], decision, "
        "next_actions[], sensitivity, references[]."
    )
    user = json.dumps(document.to_dict(), ensure_ascii=False, indent=2)

    async with aiohttp.ClientSession() as session:
        completion = await call_chat_completion(
            session,
            url=OMNIROUTE_URL,
            api_key=OMNIROUTE_API_KEY,
            payload={
                "model": CURATION_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 1600,
                "temperature": 0.2,
                "stream": False,
            },
            timeout_seconds=90,
            default_model=CURATION_MODEL,
        )

    raw_text = completion.text.strip()
    if not raw_text or has_markdown_fences(raw_text):
        logger.warning("Skipping curated note extraction: invalid raw output")
        return []

    payload = extract_json_payload(raw_text)
    if not isinstance(payload, list):
        raise ValueError("Curated notes response is not a JSON array")

    notes: list[CuratedDigestNote] = []
    for note_payload in payload[:5]:
        try:
            notes.append(_validate_curated_note(note_payload))
        except Exception as exc:
            logger.warning("Skipping invalid curated note: %s", exc)
    return notes


async def _upload_paths_to_lightrag(paths: list[Path]) -> None:
    if not paths:
        return
    async with aiohttp.ClientSession() as session:
        for path in paths:
            form = aiohttp.FormData()
            form.add_field(
                "file",
                path.read_bytes(),
                filename=path.name,
                content_type="text/markdown",
            )
            try:
                async with session.post(
                    f"{LIGHTRAG_URL}/documents/upload",
                    data=form,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status >= 400:
                        logger.warning("LightRAG upload failed for %s: %s", path.name, resp.status)
                    else:
                        logger.info("LightRAG uploaded %s", path.name)
            except Exception as exc:
                logger.warning("LightRAG upload error for %s: %s", path.name, exc)

        try:
            async with session.post(
                f"{LIGHTRAG_URL}/documents/reprocess_failed",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    logger.warning("LightRAG reprocess_failed returned %s", resp.status)
        except Exception as exc:
            logger.warning("LightRAG reprocess_failed failed: %s", exc)


async def persist_digest(
    document: DigestDocument,
    *,
    config: dict,
    period_start: datetime,
    period_end: datetime,
) -> list[Path]:
    """
    Persist a validated digest into the dedicated Obsidian subtree and optionally
    upload it to LightRAG immediately.
    """
    if not should_persist_digest(document, config):
        logger.info("Digest persistence skipped for %s", document.digest_type)
        return []

    root = _obsidian_root(config)
    derived_path = _derived_note_path(root, document, period_start, period_end)
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived_body = "\n".join(_frontmatter_lines(document, period_start, period_end)) + render_digest_markdown(document)
    derived_path.write_text(derived_body)
    logger.info("Persisted derived digest note: %s", derived_path)

    written_paths = [derived_path]

    try:
        curated_notes = await _extract_curated_notes(document, config)
    except Exception as exc:
        curated_notes = []
        logger.warning("Curated note extraction failed: %s", exc)

    for note in curated_notes:
        note_path = _curated_note_path(root, note)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(_render_curated_note_markdown(note))
        written_paths.append(note_path)
        logger.info("Persisted curated digest note: %s", note_path)

    if _persistence_cfg(config).get("immediate_lightrag_ingest", False):
        await _upload_paths_to_lightrag(written_paths)

    return written_paths
