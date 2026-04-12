"""
Structured digest generation via OmniRoute.

All digest types produce one validated DigestDocument. The LLM returns strict
JSON; Telegram HTML and Markdown are rendered later from the structured object.
"""
import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime

import aiohttp
import pytz

from models import (
    DigestDocument,
    DigestItem,
    DigestSection,
    DigestStats,
    ModelMeta,
    Post,
)
from omniroute_client import (
    call_chat_completion,
    extract_json_payload,
    has_markdown_fences,
)
from pulse import build_pulse_lines

logger = logging.getLogger(__name__)

OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://omniroute:20129/v1")
OMNIROUTE_API_KEY = os.environ.get("OMNIROUTE_API_KEY", "")
MODEL = "medium"
MODEL_EDITORIAL = "smart"

_DEFAULT_TITLES = {
    "morning": "Утренний снимок",
    "interval": "Дайджест",
    "editorial": "Редакция дня",
}

_CLARIFICATION_MARKERS = (
    "мне нужна дополнительная информация",
    "что именно ты хочешь",
    "что мне не хватает",
    "как только уточнишь",
    "уточни структуру",
    "предоставь полный набор",
    "what exactly do you want",
    "i need more information",
    "what i need",
    "clarify",
)

_LOW_SIGNAL_PATTERNS = (
    "donor messages",
    "/start donate",
    "сообщение каналу",
    "цитата дня",
    "community pulse",
    "не пропустите отраслевые мероприятия",
    "paid group",
    "new subscribers",
    "channel posts:",
    "longreads in group",
    "мероприятия на следующей неделе",
)

_TECHISH_PATTERN = re.compile(
    r"\b(AI|LLM|GPT|Claude|Gemini|agent|automation|GenAI|SynthID|SWE-bench|Terminal-Bench|"
    r"HKUDS|OpenClaw|Managed Agents|Multica|Telegram|privacy|VPN|proxy|security)\b",
    re.I,
)
def _default_title(digest_type: str) -> str:
    return _DEFAULT_TITLES.get(digest_type, "Дайджест")


def _period_label(start: datetime, end: datetime, timezone_name: str) -> str:
    tz = pytz.timezone(timezone_name)
    return f"{start.astimezone(tz).strftime('%H:%M')}–{end.astimezone(tz).strftime('%H:%M')}"


def _folder_tier(folder_name: str, config: dict) -> str:
    tiers = config.get("folder_tiers", {})
    folder_lc = folder_name.lower()
    for tier_name, tier_cfg in tiers.items():
        folders = [f.lower() for f in tier_cfg.get("folders", [])]
        if folder_lc in folders:
            return tier_name
    return "C"


def _tier_rank(tier_name: str) -> int:
    return {"A": 0, "B": 1, "C": 2}.get(tier_name.upper(), 3)


def _position_bucket(position: int) -> str:
    if position <= 3:
        return "top_1_4"
    if position <= 7:
        return "top_5_8"
    if position <= 11:
        return "top_9_12"
    return "other"


def _clean_text(value: str, max_len: int = 240) -> str:
    text = value or ""
    text = re.sub(r"```.+?```", " ", text, flags=re.S)
    text = text.replace("```", " ")
    text = text.replace("`", " ")
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"www\.\S+", " ", text)
    text = re.sub(r"(?<!\w)#([A-Za-zА-Яа-я0-9_]+)", r"\1", text)
    text = re.sub(r"[*_~]+", " ", text)
    text = re.sub(r"\bmt\s+в\s+max\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bgithub\b", "GitHub", text, flags=re.IGNORECASE)
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _reason_from_post(post: Post, config: dict) -> str:
    reasons = []
    tier = _folder_tier(post.folder_name, config)
    if tier == "A":
        reasons.append("папка Tier A")
    elif tier == "B":
        reasons.append("папка Tier B")
    if post.is_pinned:
        reasons.append("пост из pinned-канала")
    bucket = _position_bucket(post.channel_position)
    if bucket != "other":
        reasons.append(bucket.replace("_", " "))
    if post.also_mentioned:
        reasons.append("тема повторялась в нескольких каналах")
    if not reasons:
        reasons.append("сигнал попал в top по score")
    return ", ".join(reasons)


def _post_to_item(post: Post, config: dict, kind: str = "signal") -> DigestItem:
    return DigestItem(
        channel=post.channel_name,
        channel_url=post.channel_url,
        post_url=post.url or "",
        summary=_clean_text(post.text),
        why_important="",
        kind=kind,
        pinned=post.is_pinned,
        also_mentioned=post.also_mentioned[:4],
    )


def _is_low_signal_post(post: Post) -> bool:
    lowered = (post.text or "").lower()
    return any(pattern in lowered for pattern in _LOW_SIGNAL_PATTERNS)


def _looks_techish(text: str) -> bool:
    return bool(_TECHISH_PATTERN.search(text or ""))


def _quiet_folders(config: dict, sections: list[DigestSection], stats: DigestStats, max_items: int = 5) -> list[str]:
    shown = {section.folder.casefold() for section in sections}
    candidates = []
    active_folders = stats.folder_message_counts or {}
    for folder, message_count in active_folders.items():
        if folder.casefold() in shown:
            continue
        tier = _folder_tier(folder, config)
        if tier not in {"A", "B"} and folder not in {"personal", "work"}:
            continue
        candidates.append(
            (
                0 if folder in {"work", "personal", "eb1", "гребенюк"} else 1,
                _tier_rank(tier),
                -message_count,
                folder.lower(),
                folder,
            )
        )
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return [folder for *_, folder in candidates[:max_items]]


def _lead_from_sections(sections: list[DigestSection], max_items: int = 6) -> list[str]:
    candidates: list[tuple[tuple[int, int, int, str], str]] = []
    for section in sections:
        for item in section.items:
            key = (
                0 if _looks_techish(item.summary) else 1,
                _tier_rank(section.tier),
                -(1 + len(item.extra_post_urls)),
                item.channel.lower(),
            )
            candidates.append((key, f"{item.channel}: {item.summary}"))
    candidates.sort(key=lambda item: item[0])
    lead: list[str] = []
    seen_channels: set[str] = set()
    for _, line in candidates:
        channel = line.split(":", 1)[0].casefold()
        if channel in seen_channels:
            continue
        seen_channels.add(channel)
        lead.append(line)
        if len(lead) >= max_items:
            break
    return lead


def _pick_must_read_items(sections: list[DigestSection], max_items: int = 4) -> list[DigestItem]:
    candidates: list[tuple[tuple[int, int, int, str], DigestItem]] = []
    for section in sections:
        for item in section.items:
            key = (
                0 if _looks_techish(item.summary) else 1,
                _tier_rank(section.tier),
                -(len(item.also_mentioned) + len(item.extra_post_urls)),
                item.channel.lower(),
            )
            candidates.append((key, item))

    candidates.sort(key=lambda pair: pair[0])
    chosen: list[DigestItem] = []
    seen_channels: set[str] = set()
    for _, item in candidates:
        channel_key = item.channel.casefold()
        if channel_key in seen_channels:
            continue
        seen_channels.add(channel_key)
        chosen.append(item)
        if len(chosen) >= max_items:
            break
    return chosen


def _shown_post_urls(items: list[DigestItem]) -> set[str]:
    urls: set[str] = set()
    for item in items:
        if item.post_url:
            urls.add(item.post_url)
        for extra_url in item.extra_post_urls:
            if extra_url:
                urls.add(extra_url)
    return urls


def _build_new_glance(
    posts: list[Post],
    sections: list[DigestSection],
    must_read: list[DigestItem],
    *,
    max_items: int = 3,
) -> list[DigestItem]:
    shown_urls = _shown_post_urls(must_read)
    for section in sections:
        shown_urls.update(_shown_post_urls(section.items))

    leftovers = [
        post for post in sorted(posts, key=lambda current: (current.date.timestamp(), current.score), reverse=True)
        if post.url and post.url not in shown_urls and not _is_low_signal_post(post)
    ]

    by_channel: dict[str, list[Post]] = defaultdict(list)
    for post in leftovers:
        by_channel[post.channel_name].append(post)

    items: list[DigestItem] = []
    for channel_posts in by_channel.values():
        if len(items) >= max_items:
            break
        batch = channel_posts[:2]
        if len(batch) >= 2:
            items.append(_grouped_item(batch, {}))
        else:
            items.append(_post_to_item(batch[0], {}, kind="new"))
    return items


def _build_llm_context(
    posts: list[Post],
    config: dict,
    digest_type: str,
    period_start: datetime,
    period_end: datetime,
    stats: DigestStats,
) -> tuple[dict, str]:
    timezone_name = config.get("timezone", "Europe/Moscow")
    period = {
        "start": period_start.isoformat(),
        "end": period_end.isoformat(),
        "label": _period_label(period_start, period_end, timezone_name),
        "timezone": timezone_name,
    }
    folder_links = config.get("folder_links", {}) or {}
    by_folder: dict[str, list[Post]] = defaultdict(list)
    for post in posts:
        by_folder[post.folder_name].append(post)

    folders = []
    for folder_name in sorted(
        by_folder,
        key=lambda name: (
            _tier_rank(_folder_tier(name, config)),
            -max(post.score for post in by_folder[name]),
            name.lower(),
        ),
    ):
        folder_posts = sorted(
            by_folder[folder_name],
            key=lambda post: (post.score, post.date.timestamp()),
            reverse=True,
        )
        folders.append(
            {
                "name": folder_name,
                "tier": _folder_tier(folder_name, config),
                "folder_link": folder_links.get(folder_name),
                "items": [
                    {
                        "channel": post.channel_name,
                        "channel_url": post.channel_url,
                        "post_url": post.url,
                        "text": _clean_text(post.text, max_len=320),
                        "date": post.date.isoformat(),
                        "score": round(post.score, 2),
                        "pinned": post.is_pinned,
                        "position_bucket": _position_bucket(post.channel_position),
                        "folder": post.folder_name,
                        "tier": _folder_tier(post.folder_name, config),
                        "also_mentioned": post.also_mentioned[:4],
                    }
                    for post in folder_posts
                ],
            }
        )

    context = {
        "digest_type": digest_type,
        "title_hint": _default_title(digest_type),
        "period": period,
        "stats": {
            "channels_in_scope": stats.channels_in_scope,
            "new_posts_seen": stats.new_posts_seen,
            "posts_selected": stats.posts_selected,
        },
        "active_folders": [
            {
                "name": folder,
                "messages": stats.folder_message_counts.get(folder, 0),
                "channels": stats.folder_channel_counts.get(folder, 0),
                "tier": _folder_tier(folder, config),
            }
            for folder in sorted(
                stats.folder_message_counts,
                key=lambda name: (
                    _tier_rank(_folder_tier(name, config)),
                    -stats.folder_message_counts.get(name, 0),
                    name.lower(),
                ),
            )
        ],
        "allowed_folder_names": config.get("allowed_folder_names", []),
        "system_folders": config.get("system_folders", []),
        "folder_tiers": config.get("folder_tiers", {}),
        "folder_links": folder_links,
        "folders": folders,
    }
    return context, period["label"]


def _system_prompt(digest_type: str) -> str:
    common = (
        "Ты персональный редактор Telegram Digest для Дениса.\n"
        "У тебя УЖЕ есть весь нужный контекст. Никогда не проси дополнительные данные, "
        "не задавай уточняющих вопросов, не обсуждай нехватку информации, не пересказывай правила.\n"
        "Работай только по переданному JSON-контексту и возвращай только валидный JSON-объект.\n"
        "Запрещено: markdown fences, HTML, пояснения до/после JSON, фразы вроде "
        "«мне нужна дополнительная информация».\n"
        "Правила:\n"
        "1. Не искажай факты. Если это мнение автора — явно маркируй как мнение.\n"
        "2. История важнее источника: сначала что произошло, потом кто это дал.\n"
        "3. Не дублируй тему в нескольких пунктах, если она уже покрыта.\n"
        "4. Не пиши «два поста», «три поста», не пересказывай экспорт каналов.\n"
        "5. Пиши как редактор компактной новостной сводки: короткие сюжетные линии, чистый язык, минимум шума.\n"
        "6. В lead делай storyline bullets, а не raw excerpts и не channel-first narration.\n"
        "7. В themes делай 4-6 строк формата «Тема — конкретный факт / развитие». "
        "Никаких abstract labels, keyword cloud, bags of nouns или строк без проверяемого сюжета.\n"
        "8. В must_read верни 2-4 источника, которые действительно стоит открыть первыми.\n"
        "9. Sections — это радар по папкам, а не второй полный фид.\n"
        "10. Не копируй посты целиком, не вставляй внешние ссылки, raw URL или служебный мусор.\n"
        "11. Можно объединять 2-3 поста одного канала в один пункт. В таком случае summary должно звучать "
        "как короткий обзор, а дополнительные Telegram-ссылки верни в extra_post_urls.\n"
        "12. Не включай технические status dumps, сервисные сводки, анонсы мероприятий, рекламные посты "
        "и дневниковые тизеры без полезного сигнала.\n"
        "13. Если выбор неоднозначный, слегка предпочитай technology / AI / automation / product / work-сигналы.\n"
        "14. Используй только реальные Telegram-ссылки из контекста. Не придумывай folder_link/channel_url/"
        "post_url/extra_post_urls.\n"
        "15. Если окно слабое, честно отрази это в low_signal или в lead.\n"
        "16. JSON должен строго соответствовать структуре, все массивы должны существовать.\n"
        "17. У каждого DigestItem обязателен post_url.\n"
    )

    if digest_type == "morning":
        return (
            common
            + "Сделай короткий утренний снимок: lead 3-5 bullets, must_read 2-3 пункта, "
            "sections только по самым важным папкам, low_signal коротко при необходимости.\n"
            'Верни объект с полями: title, period_label, lead, new_glance, must_read, sections, low_signal, model_meta, themes, quiet_folders.\n'
        )
    if digest_type == "editorial":
        return (
            common
            + "Сделай полный вечерний editorial digest: executive_summary 2-5 bullets, "
            "themes 2-6 bullets, must_read 3-10, sections по сильным папкам, low_signal, watchpoints 2-5.\n"
            'Верни объект с полями: title, period_label, lead, must_read, sections, low_signal, model_meta, '
            "executive_summary, themes, quiet_folders, new_glance, watchpoints.\n"
        )
    return (
        common
        + "Сделай подробный interval digest: lead 3-6 storyline bullets, must_read 2-4 пункта "
        "в логике «что открыть первым», sections по папкам с реальным сигналом, больше разнообразия "
        "по каналам, low_signal коротко, themes 4-6 тем окна.\n"
        'Верни объект с полями: title, period_label, lead, new_glance, must_read, sections, low_signal, model_meta, themes, quiet_folders.\n'
    )


def _user_prompt(context: dict) -> str:
    schema = {
        "title": "string",
        "period_label": "string",
        "lead": ["string"],
        "new_glance": ["DigestItem"],
        "must_read": [
            {
                "channel": "string",
                "channel_url": "string|null",
                "post_url": "string",
                "extra_post_urls": ["string"],
                "summary": "string",
                "kind": "string",
                "pinned": "bool",
                "also_mentioned": ["string"],
            }
        ],
        "sections": [
            {
                "folder": "string",
                "tier": "A|B|C",
                "folder_link": "string|null",
                "items": "DigestItem[]",
            }
        ],
        "low_signal": ["string"],
        "model_meta": {},
        "executive_summary": ["string"],
        "themes": ["string"],
        "quiet_folders": ["string"],
        "watchpoints": ["string"],
    }
    return (
        "Контекст запуска Telegram Digest в JSON. Используй только его.\n"
        "Если поле не нужно для этого digest_type, верни пустой массив.\n"
        "Схема ответа:\n"
        f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        "Контекст:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _has_retry_markers(raw_text: str) -> bool:
    lowered = raw_text.lower()
    if has_markdown_fences(raw_text):
        return True
    return any(marker in lowered for marker in _CLARIFICATION_MARKERS)


def _require_non_empty_string(value, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    cleaned = _clean_text(value, max_len=600)
    if not cleaned:
        raise ValueError(f"{field_name} is empty")
    return cleaned


def _require_string_list(value, field_name: str, max_items: int = 10) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for item in value[:max_items]:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} items must be strings")
        cleaned = _clean_text(item, max_len=400)
        if cleaned:
            result.append(cleaned)
    return result


def _validate_item(value: dict, field_name: str) -> DigestItem:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    channel = _require_non_empty_string(value.get("channel", ""), f"{field_name}.channel")
    post_url = _require_non_empty_string(value.get("post_url", ""), f"{field_name}.post_url")
    summary = _require_non_empty_string(value.get("summary", ""), f"{field_name}.summary")
    kind = _require_non_empty_string(value.get("kind", "signal"), f"{field_name}.kind")
    channel_url = value.get("channel_url")
    if channel_url is not None and not isinstance(channel_url, str):
        raise ValueError(f"{field_name}.channel_url must be string|null")
    extra_post_urls = _require_string_list(value.get("extra_post_urls", []), f"{field_name}.extra_post_urls", max_items=4)
    folder_item = DigestItem(
        channel=channel,
        channel_url=channel_url or None,
        post_url=post_url,
        summary=summary,
        extra_post_urls=extra_post_urls,
        why_important="",
        kind=kind,
        pinned=bool(value.get("pinned", False)),
        also_mentioned=_require_string_list(value.get("also_mentioned", []), f"{field_name}.also_mentioned", max_items=6),
    )
    return folder_item


def _validate_sections(value, folder_links: dict[str, str]) -> list[DigestSection]:
    if not isinstance(value, list):
        raise ValueError("sections must be a list")
    sections: list[DigestSection] = []
    for idx, section in enumerate(value):
        if not isinstance(section, dict):
            raise ValueError("section must be an object")
        folder = _require_non_empty_string(section.get("folder", ""), f"sections[{idx}].folder")
        tier = _require_non_empty_string(section.get("tier", "C"), f"sections[{idx}].tier").upper()
        folder_link = section.get("folder_link")
        if folder_link is not None and not isinstance(folder_link, str):
            raise ValueError(f"sections[{idx}].folder_link must be string|null")
        items_value = section.get("items", [])
        if not isinstance(items_value, list):
            raise ValueError(f"sections[{idx}].items must be a list")
        items = [_validate_item(item, f"sections[{idx}].items[{item_idx}]") for item_idx, item in enumerate(items_value)]
        if not items:
            continue
        sections.append(
            DigestSection(
                folder=folder,
                tier=tier,
                folder_link=folder_link or folder_links.get(folder),
                items=items,
            )
        )
    return sections


def _validate_document_payload(
    payload: dict,
    *,
    digest_type: str,
    period_label: str,
    stats: DigestStats,
    model_meta: ModelMeta,
    config: dict,
    posts: list[Post],
) -> DigestDocument:
    if not isinstance(payload, dict):
        raise ValueError("Digest response is not an object")
    folder_links = config.get("folder_links", {}) or {}
    lead = _require_string_list(payload.get("lead", []), "lead", max_items=6)
    if not lead:
        raise ValueError("lead is empty")
    new_glance = [_validate_item(item, f"new_glance[{idx}]") for idx, item in enumerate(payload.get("new_glance", []))]
    must_read = [_validate_item(item, f"must_read[{idx}]") for idx, item in enumerate(payload.get("must_read", []))]
    sections = _validate_sections(payload.get("sections", []), folder_links)
    if not sections and not must_read:
        raise ValueError("Digest has neither sections nor must_read items")
    low_signal = _require_string_list(payload.get("low_signal", []), "low_signal", max_items=6)

    executive_summary = []
    themes = build_pulse_lines(
        posts,
        raw_themes=_require_string_list(payload.get("themes", []), "themes", max_items=8),
        lead=lead,
        must_read=must_read,
        sections=sections,
        new_glance=new_glance,
        max_items=6,
    )
    quiet_folders = _quiet_folders(config, sections, stats)
    watchpoints = []
    if digest_type == "editorial":
        executive_summary = _require_string_list(payload.get("executive_summary", []), "executive_summary", max_items=6)
        watchpoints = _require_string_list(payload.get("watchpoints", []), "watchpoints", max_items=6)
        if not executive_summary:
            raise ValueError("editorial digest is missing executive_summary")

    title = _clean_text(payload.get("title", "") or _default_title(digest_type), max_len=120)
    raw_period_label = payload.get("period_label")
    if not isinstance(raw_period_label, str) or not raw_period_label.strip():
        raw_period_label = period_label

    return DigestDocument(
        digest_type=digest_type,
        title=title,
        period_label=period_label if raw_period_label != period_label else raw_period_label,
        lead=lead,
        new_glance=new_glance[:4],
        must_read=must_read[:10],
        sections=sections,
        low_signal=low_signal,
        model_meta=model_meta,
        stats=stats,
        executive_summary=executive_summary,
        themes=themes,
        quiet_folders=quiet_folders,
        watchpoints=watchpoints,
    )


def _count_label(count: int) -> str:
    if count == 2:
        return "Два поста"
    if count == 3:
        return "Три поста"
    return "Несколько постов"


def _group_summary(posts: list[Post]) -> str:
    snippets = [_clean_text(post.text, max_len=88) for post in posts[:3]]
    snippets = [snippet for snippet in snippets if snippet]
    unique_snippets: list[str] = []
    seen: set[str] = set()
    for snippet in snippets:
        normalized = snippet.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_snippets.append(snippet)

    snippets = unique_snippets
    if not snippets:
        return "Короткие обновления без сильного сигнала."
    if len(snippets) == 1:
        return snippets[0]
    return "; ".join(snippets[:3])


def _grouped_item(posts: list[Post], config: dict) -> DigestItem:
    lead_post = posts[0]
    extra_urls = [post.url for post in posts[1:4] if post.url]
    return DigestItem(
        channel=lead_post.channel_name,
        channel_url=lead_post.channel_url,
        post_url=lead_post.url or "",
        extra_post_urls=extra_urls,
        summary=_group_summary(posts),
        why_important="",
        kind="roundup" if len(posts) > 1 else "signal",
        pinned=any(post.is_pinned for post in posts),
        also_mentioned=lead_post.also_mentioned[:4],
    )


def _fallback_items(posts: list[Post], config: dict, limit_per_folder: int) -> list[DigestItem]:
    by_channel: dict[str, list[Post]] = defaultdict(list)
    for post in sorted(posts, key=lambda current: (current.score, current.date.timestamp()), reverse=True):
        by_channel[post.channel_name].append(post)

    channel_groups = sorted(
        by_channel.values(),
        key=lambda group: (
            group[0].score,
            len(group),
            group[0].date.timestamp(),
        ),
        reverse=True,
    )

    items: list[DigestItem] = []
    for group in channel_groups:
        if len(items) >= limit_per_folder:
            break
        grouped_posts = [post for post in group if post.url][:3]
        if not grouped_posts:
            continue
        if len(grouped_posts) >= 2:
            items.append(_grouped_item(grouped_posts, config))
        else:
            items.append(_post_to_item(grouped_posts[0], config))
    return items


def _fallback_sections(posts: list[Post], config: dict, limit_per_folder: int) -> list[DigestSection]:
    by_folder: dict[str, list[Post]] = defaultdict(list)
    for post in posts:
        by_folder[post.folder_name].append(post)

    sections: list[DigestSection] = []
    folder_links = config.get("folder_links", {}) or {}
    for folder_name in sorted(
        by_folder,
        key=lambda name: (
            _tier_rank(_folder_tier(name, config)),
            -sum(
                post.score
                for post in sorted(
                    by_folder[name],
                    key=lambda current: (current.score, current.date.timestamp()),
                    reverse=True,
                )[:3]
            ),
            name.lower(),
        ),
    ):
        items = _fallback_items(by_folder[folder_name], config, limit_per_folder=limit_per_folder)
        if items:
            sections.append(
                DigestSection(
                    folder=folder_name,
                    tier=_folder_tier(folder_name, config),
                    folder_link=folder_links.get(folder_name),
                    items=items,
                )
            )
    return sections


def _local_fallback(
    posts: list[Post],
    *,
    digest_type: str,
    period_label: str,
    stats: DigestStats,
    config: dict,
) -> DigestDocument:
    filtered_posts = [post for post in posts if not _is_low_signal_post(post)] or posts
    max_sections = 4 if digest_type == "morning" else 7
    limit_per_folder = 2 if digest_type == "morning" else 4
    sections = _fallback_sections(filtered_posts, config, limit_per_folder=limit_per_folder)[:max_sections]
    must_read = _pick_must_read_items(sections, max_items=3 if digest_type == "morning" else 4)
    if not must_read and digest_type in {"morning", "editorial", "interval"}:
        must_read = [_post_to_item(post, config, kind="must_read") for post in filtered_posts[: min(4, len(filtered_posts))]]

    lead = _lead_from_sections(sections)[:6]
    low_signal = []
    if len(filtered_posts) <= 4:
        low_signal.append("Окно было тихим: сильных новых сигналов немного.")

    executive_summary = []
    new_glance = _build_new_glance(filtered_posts, sections, must_read)
    themes = build_pulse_lines(
        filtered_posts,
        lead=lead,
        must_read=must_read,
        sections=sections,
        new_glance=new_glance,
        max_items=6,
    )
    quiet_folders = _quiet_folders(config, sections, stats)
    watchpoints = []
    if digest_type == "editorial":
        executive_summary = lead[:3]
        watchpoints = [
            f"Следить за развитием темы из папки {section.folder.lower()}."
            for section in sections[:3]
        ]

    return DigestDocument(
        digest_type=digest_type,
        title=_default_title(digest_type),
        period_label=period_label,
        lead=lead or ["Новых сильных сигналов мало."],
        new_glance=new_glance,
        must_read=must_read,
        sections=sections,
        low_signal=low_signal,
        model_meta=ModelMeta(
            model_id="local",
            tier=MODEL_EDITORIAL if digest_type == "editorial" else MODEL,
            local_fallback=True,
        ),
        stats=stats,
        executive_summary=executive_summary,
        themes=themes,
        quiet_folders=quiet_folders,
        watchpoints=watchpoints,
    )


async def summarize(
    posts: list[Post],
    *,
    config: dict,
    digest_type: str,
    period_start: datetime,
    period_end: datetime,
    stats: DigestStats,
) -> DigestDocument:
    """
    Produce one validated structured digest document for any digest type.
    """
    context, period_label = _build_llm_context(
        posts,
        config,
        digest_type,
        period_start,
        period_end,
        stats,
    )
    model = MODEL_EDITORIAL if digest_type == "editorial" else MODEL
    system = _system_prompt(digest_type)
    user = _user_prompt(context)
    retry_note = (
        "\n\nНапоминание: ты уже получил полный контекст. "
        "Запрещено задавать вопросы, обсуждать нехватку данных, "
        "возвращать markdown fences или что-либо кроме JSON."
    )

    async with aiohttp.ClientSession() as session:
        for attempt in range(2):
            try:
                completion = await call_chat_completion(
                    session,
                    url=OMNIROUTE_URL,
                    api_key=OMNIROUTE_API_KEY,
                    payload={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user + (retry_note if attempt else "")},
                        ],
                        "max_tokens": 2200 if digest_type == "editorial" else 1600,
                        "temperature": 0.2,
                        "stream": False,
                    },
                    timeout_seconds=120,
                    default_model=model,
                )
            except Exception as exc:
                logger.warning("Digest LLM call failed on attempt %s: %s", attempt + 1, exc)
                continue

            raw_text = completion.text.strip()
            if not raw_text:
                logger.warning("Empty digest response on attempt %s", attempt + 1)
                continue
            if _has_retry_markers(raw_text):
                logger.warning("Digest response contained retry markers on attempt %s", attempt + 1)
                continue

            try:
                payload = extract_json_payload(raw_text)
                return _validate_document_payload(
                    payload,
                    digest_type=digest_type,
                    period_label=period_label,
                    stats=stats,
                    model_meta=ModelMeta(
                        model_id=completion.model_id,
                        tier=model,
                        prompt_tokens=completion.prompt_tokens,
                        completion_tokens=completion.completion_tokens,
                        provider_fallback=completion.provider_fallback,
                        local_fallback=False,
                    ),
                    config=config,
                    posts=posts,
                )
            except Exception as exc:
                logger.warning("Digest validation failed on attempt %s: %s", attempt + 1, exc)

    logger.error("Falling back to deterministic local digest for %s", digest_type)
    return _local_fallback(
        posts,
        digest_type=digest_type,
        period_label=period_label,
        stats=stats,
        config=config,
    )
