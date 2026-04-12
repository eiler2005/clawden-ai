"""
Pulse-of-the-day extraction and fallback storylines for Telegram Digest.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from models import DigestItem, DigestSection, Post

_THEME_STOPWORDS = {
    "сегодня", "вчера", "завтра", "последние", "месяцы", "недели", "года", "году",
    "новый", "новая", "новые", "главное", "коротко", "подробнее", "уровень", "версия",
    "канал", "каналы", "пост", "поста", "постов", "сообщение", "сообщения", "сообщений",
    "автор", "авторы", "канала", "канале", "данные", "детали", "обзор", "сводка",
    "рынок", "рынки", "система", "работа", "команда", "компании", "компания", "люди",
    "россия", "русский", "русская", "европа", "европа", "служба", "live", "news",
    "growth", "work", "personal", "startups", "evolution", "fintech", "investing",
    "faang", "coffee", "fashion", "property", "новости", "тема", "темы", "окно",
    "источник", "источником", "short", "medium", "smart", "open", "source", "version",
    "это", "этот", "эта", "эти", "того", "такой", "также", "которые", "который",
    "которых", "снова", "после", "вокруг", "сейчас", "почти", "просто", "были",
    "будет", "будут", "можно", "могут", "через", "очень", "почему", "какие",
    "какая", "какой", "южной", "северной", "внутри", "против", "должен", "как",
    "так", "если", "когда", "лишь", "тоже", "здесь", "последний", "последняя",
    "последние", "весь", "вся", "всё", "все", "которое", "которую", "однако",
    "между", "среди", "пока", "затем", "итоги", "итог", "часть",
}
_THEME_ALLOWED_LOWER = {
    "telegram", "телеграм", "блокировки", "приватность", "иран", "ормуз", "лидген",
    "банки", "визы", "рынки", "макро", "агенты", "privacy", "openclaw", "vpn",
    "proxy", "обход", "доступ", "трамп", "россия", "сша", "iran", "creator",
    "ai", "gemini",
}
_THEME_BLOCKED = {
    "news", "work", "personal", "evolution", "investing", "fintech", "startups",
    "growth me", "growth", "faang", "coffee", "fashion", "property", "eb1",
    "гребенюк", "digest", "дайджест",
}
_ANCHOR_PHRASE_RE = re.compile(
    r"(?:[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9+\-]{2,}|[A-Z]{2,}|[А-ЯЁ]{2,}|[A-Za-z]+[A-Z][A-Za-z0-9+\-]*)"
    r"(?:\s+(?:[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9+\-]{2,}|[A-Z]{2,}|[А-ЯЁ]{2,}|[A-Za-z]+[A-Z][A-Za-z0-9+\-]*)){0,2}"
)
_PULSE_HINTS = (
    (
        "Telegram / VPN",
        re.compile(r"\b(telegram|телеграм|vpn|proxy|прокси|блокиров|обход|ограничен|доступ)\b", re.I),
    ),
    (
        "Иран / Ормуз",
        re.compile(r"\b(иран|iran|ормуз|ormuz|пролив|переговор|санкц|эскалац|напряж|перемири)\b", re.I),
    ),
    (
        "Трамп / США",
        re.compile(r"\b(трамп|trump|белый дом|white house|кампан|выбор|администраци)\b", re.I),
    ),
    (
        "AI / агенты",
        re.compile(r"\b(open.?source|openclaw|managed agents|agents?|agentic|automation|автоматизац)\b", re.I),
    ),
    (
        "AI / SynthID",
        re.compile(r"\b(synthid|deepmind|gemini|watermark|водян|origin|provenance)\b", re.I),
    ),
    (
        "AI / безопасность",
        re.compile(r"\b(swe-bench|terminal-bench|security|уязв|взлом|hack)\b", re.I),
    ),
    (
        "Creator Economy",
        re.compile(r"\b(creator|creative|vetted|job board|джоб|ваканси|бренд|video creators?)\b", re.I),
    ),
    (
        "Банки / финтех",
        re.compile(r"\b(bank|банк|банки|payment|payments|visa|mastercard|securitize|tokeniz|rwa)\b", re.I),
    ),
    (
        "Россия",
        re.compile(r"\b(фсб|сизо|приложени|надзор|слежк|цифров|регулир)\b", re.I),
    ),
    (
        "Артемида-2",
        re.compile(r"\b(артемид|artemis|orion|мисси|капсул|nasa|океан|приводнен)\b", re.I),
    ),
)
_PULSE_SKIP_RE = re.compile(
    r"(community pulse|channel posts:|paid group:|new subscribers|shared:|longreads in group|"
    r"не пропустите|форум|конференц|вебинар|митап|практикум|регистрац|реклама|"
    r"сводка за|искусственный интеллект\s+[–-]\s+сводка)",
    re.I,
)
_PULSE_BAG_RE = re.compile(
    r"^[A-Za-zА-Яа-яЁё0-9+\-/]+(?:,\s*[A-Za-zА-Яа-яЁё0-9+\-/]+){2,}$"
)
_PULSE_VERBISH_RE = re.compile(
    r"\b(получил|получила|получили|прибыл|прибыла|прибыло|прилетел|прилетела|выпустил|"
    r"выпустила|запустил|запустила|приводнился|приводнилась|заявил|заявила|обсуждают|"
    r"усиливает|вышел|вышла|показал|показала|собрала|собрал|разбирают|жалуются|"
    r"готовит|готовят|продвигает|перешли|передали|взяла|получают|растёт|"
    r"объявил|объявила|объявили|смещается|снижается|снизилась|растет|запретил|запретила|"
    r"открывает|открыла|поднял|подняла|вернул|вернула|перешла|перешел|ускоряет|"
    r"accelerates|launched|released|announced|discussed|discusses|arrived)\b",
    re.I,
)
_PULSE_GENERIC_FACT_MARKERS = (
    "политическая борьба и сигналы",
    "платежи, токенизация, сделки",
    "внутренняя и цифровая повестка",
    "рынок креатива и вакансии",
    "open-source инструменты и агенты",
    "бенчмарки, хаки, уязвимости",
    "доступ, ограничения, обход",
    "переговоры на фоне напряженности",
)
_PULSE_GARBAGE_RE = re.compile(
    r"\b(allowed|absolut[eа]|абсолюте|call|and|white|белого|белый|версию)\b",
    re.I,
)
_STORYLINE_PREFIX_RE = re.compile(r"^([^:]{2,80}):\s*(.+)$")
_SOURCEISH_THEME_RE = re.compile(
    r"\b(ria|reuters|bloomberg|ft|wsj|cnn|bbc|tass|тасс|медуза|meduza|новости|news|media)\b",
    re.I,
)
_DIVERSITY_BUCKETS = (
    (
        "telegram",
        re.compile(r"\b(telegram|телеграм|vpn|proxy|прокси|блокиров|обход|приватност|privacy|доступ)\b", re.I),
        ("telegram", "телеграм", "vpn", "proxy", "прокси", "блокиров", "обход", "privacy", "доступ"),
    ),
    (
        "ai",
        re.compile(r"\b(ai|llm|gpt|claude|gemini|deepmind|synthid|agent|agents|agentic|automation|автоматизац|openclaw)\b", re.I),
        ("ai", "llm", "gpt", "claude", "gemini", "deepmind", "synthid", "agent", "agents", "automation", "openclaw"),
    ),
    (
        "geopolitics",
        re.compile(r"\b(трамп|trump|белый дом|white house|иран|iran|ормуз|ormuz|украин|венгри|орбан|санкц|переговор|выбор|администраци|росси|сша|европ|израил)\b", re.I),
        ("трамп", "trump", "иран", "iran", "ормуз", "украин", "венгр", "орбан", "санкц", "переговор", "росси", "сша", "европ", "израил"),
    ),
    (
        "fintech",
        re.compile(r"\b(bank|банк|банки|payment|payments|visa|mastercard|fintech|токениз|tokeniz|rwa|securitize|деньг|платеж)\b", re.I),
        ("bank", "банк", "банки", "payment", "payments", "visa", "mastercard", "fintech", "tokeniz", "rwa", "securitize", "платеж"),
    ),
    (
        "creator",
        re.compile(r"\b(creator|creative|бренд|brand|video creators?|job board|ваканси|маркетинг|реклам|контент)\b", re.I),
        ("creator", "creative", "бренд", "brand", "video", "job board", "ваканси", "маркетинг", "контент"),
    ),
    (
        "science",
        re.compile(r"\b(артемид|artemis|orion|nasa|космос|ракет|мисси|капсул|приводнен)\b", re.I),
        ("артемид", "artemis", "orion", "nasa", "космос", "ракет", "мисси", "капсул", "приводнен"),
    ),
    (
        "product",
        re.compile(r"\b(product|growth|startups?|founder|saas|b2b|команда|найм|sales|лидоген|лидген|работа|стартап)\b", re.I),
        ("product", "growth", "startup", "founder", "saas", "b2b", "команда", "найм", "sales", "лидоген", "лидген", "работа", "стартап"),
    ),
)
_PROFILE_PATH = Path(os.environ.get("PULSE_PROFILE_PATH", "/app/state/pulse-profile.json"))
_PROFILE_VERSION = 1
_RECENT_SIGNATURE_WINDOW_SEC = 72 * 3600
_MAX_RECENT_SIGNATURES = 80
_MAX_LEARNED_TERMS_PER_BUCKET = 24


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


def _default_profile() -> dict:
    return {
        "version": _PROFILE_VERSION,
        "updated_at": 0,
        "buckets": {
            bucket_name: {
                "momentum": 0.0,
                "last_seen_at": 0,
                "learned_terms": {},
            }
            for bucket_name, _, _ in _DIVERSITY_BUCKETS
        },
        "recent_signatures": [],
    }


def _load_profile() -> dict:
    profile = _default_profile()
    try:
        if _PROFILE_PATH.exists():
            loaded = json.loads(_PROFILE_PATH.read_text())
            if isinstance(loaded, dict):
                profile.update({key: value for key, value in loaded.items() if key in {"version", "updated_at", "recent_signatures"}})
                if isinstance(loaded.get("buckets"), dict):
                    for bucket_name, _, _ in _DIVERSITY_BUCKETS:
                        bucket_state = loaded["buckets"].get(bucket_name, {})
                        if isinstance(bucket_state, dict):
                            profile["buckets"][bucket_name].update(
                                {
                                    "momentum": float(bucket_state.get("momentum", 0.0) or 0.0),
                                    "last_seen_at": int(bucket_state.get("last_seen_at", 0) or 0),
                                    "learned_terms": dict(bucket_state.get("learned_terms", {}) or {}),
                                }
                            )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return _default_profile()
    return profile


def _save_profile(profile: dict):
    try:
        _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_PATH.write_text(json.dumps(profile, ensure_ascii=False, indent=2))
    except OSError:
        return


def _bucket_state(profile: dict, bucket_name: str) -> dict:
    return profile.setdefault("buckets", {}).setdefault(
        bucket_name,
        {"momentum": 0.0, "last_seen_at": 0, "learned_terms": {}},
    )


def _normalize_learning_term(value: str) -> str:
    term = _clean_text(value, max_len=80).casefold().strip(" -")
    term = re.sub(r"[^a-zа-яё0-9+\- ]+", " ", term)
    term = re.sub(r"\s+", " ", term).strip()
    if len(term) < 4:
        return ""
    if term in _THEME_STOPWORDS or term in _THEME_BLOCKED:
        return ""
    return term


def _normalize_theme_candidate(value: str) -> str:
    candidate = re.sub(r"[«»\"'`]+", "", value or "")
    candidate = re.sub(r"[\(\)\[\]\{\}]", " ", candidate)
    candidate = re.sub(r"[^A-Za-zА-Яа-я0-9+\- ]+", " ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip(" -")
    if not candidate:
        return ""
    words = candidate.split()
    if len(words) > 3:
        candidate = " ".join(words[:3])
    lowered = candidate.casefold()
    if lowered in _THEME_STOPWORDS or lowered in _THEME_BLOCKED or len(lowered) < 3:
        return ""
    if len(candidate.split()) == 1:
        word = candidate.split()[0]
        if not (word[0].isupper() or word.casefold() in _THEME_ALLOWED_LOWER or any(ch.isdigit() for ch in word)):
            return ""
    return candidate


def _theme_candidates(text: str) -> list[str]:
    cleaned = _clean_text(text, max_len=500)
    candidates: list[str] = []

    for match in _ANCHOR_PHRASE_RE.finditer(cleaned):
        candidate = _normalize_theme_candidate(match.group(0))
        if candidate:
            candidates.append(candidate)

    tokens = re.findall(r"[A-Za-zА-Яа-я0-9+\-]{4,}", cleaned)
    filtered_tokens = [token for token in tokens if token.casefold() not in _THEME_STOPWORDS]

    for token in filtered_tokens:
        if token[0].isupper() or token.casefold() in _THEME_ALLOWED_LOWER:
            candidate = _normalize_theme_candidate(token)
            if candidate:
                candidates.append(candidate)

    for idx in range(len(filtered_tokens) - 1):
        first = filtered_tokens[idx]
        second = filtered_tokens[idx + 1]
        if first.casefold() in _THEME_STOPWORDS or second.casefold() in _THEME_STOPWORDS:
            continue
        if not (first[0].isupper() or second[0].isupper() or first.casefold() in _THEME_ALLOWED_LOWER):
            continue
        candidate = _normalize_theme_candidate(f"{first} {second}")
        if candidate:
            candidates.append(candidate)

    return candidates


def _theme_token_stem(token: str) -> str:
    lowered = token.casefold().strip(" -")
    if not lowered:
        return ""
    for suffix in (
        "иями", "ями", "ами", "ого", "ему", "ому", "ыми", "ими", "его", "ого",
        "ия", "ие", "ий", "ый", "ой", "ая", "яя", "ое", "ее", "ых", "их",
        "ам", "ям", "ах", "ях", "ов", "ев", "ом", "ем", "ую", "юю", "а", "я",
        "ы", "и", "е", "о", "у", "ю", "ь",
    ):
        if len(lowered) > len(suffix) + 3 and lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
            break
    for suffix in ("ments", "ment", "ation", "ition", "ings", "ing", "ers", "ies", "ied", "ed", "es", "s"):
        if len(lowered) > len(suffix) + 3 and lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
            break
    return lowered


def _theme_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-zА-Яа-яЁё0-9+\-]{3,}", _clean_text(text, max_len=500))


def _is_plain_titlecase(token: str) -> bool:
    return (
        len(token) >= 4
        and token[:1].isupper()
        and any(ch.islower() for ch in token[1:])
        and not any(ch.isupper() for ch in token[1:])
        and not any(ch.isdigit() for ch in token)
    )


def _is_weak_theme_label(label: str) -> bool:
    words = label.split()
    if not words:
        return True
    if len(words) <= 2 and all(_is_plain_titlecase(word) for word in words):
        return True
    if len(words) == 1 and _is_plain_titlecase(words[0]):
        return True
    if len(words) == 1 and words[0].casefold() not in _THEME_ALLOWED_LOWER and len(words[0]) <= 4:
        return True
    return False


def _pulse_hint(posts: list[Post]) -> str:
    if not posts:
        return ""

    texts = [_clean_text(post.text, max_len=500) for post in posts]
    best: tuple[int, int, str] | None = None
    for label, pattern in _PULSE_HINTS:
        match_posts = sum(1 for text in texts if pattern.search(text))
        if not match_posts:
            continue
        match_channels = len({post.channel_id for post, text in zip(posts, texts) if pattern.search(text)})
        candidate = (match_channels, match_posts, label)
        if best is None or candidate > best:
            best = candidate

    if best is None:
        return ""
    match_channels, match_posts, label = best
    if match_posts < 2 and match_channels < 2:
        return ""
    return label


def _pulse_theme_label(label_display: str, cluster_posts: list[Post]) -> str:
    hint_label = _pulse_hint(cluster_posts)
    if hint_label:
        return hint_label
    if _is_weak_theme_label(label_display):
        return ""
    return label_display


def _strip_pulse_lead_noise(text: str) -> str:
    cleaned = re.sub(r"^\s*(ребят|коротко|главное|сегодня|кстати|срочно|итак)\s*[:,.-]?\s*", "", text, flags=re.I)
    cleaned = re.sub(r"^\s*\d{1,2}\.\d{1,2}\.\d{2,4}\s+\d{1,2}:\d{2}\s*", "", cleaned)
    cleaned = re.sub(r"^\s*(update|live)\s*[:.-]?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^\s*[📆🧠⚡️⚡🔥✅❗️❗]+\s*", "", cleaned)
    return cleaned.strip()


def _pulse_fact_from_posts(cluster_posts: list[Post], theme_label: str) -> str:
    theme_tokens = {
        _theme_token_stem(token)
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9+\-]+", theme_label)
        if token
    }
    ordered_posts = sorted(
        cluster_posts,
        key=lambda post: (post.score, len(post.also_mentioned), post.date.timestamp()),
        reverse=True,
    )
    for post in ordered_posts:
        text = _clean_text(post.text, max_len=260)
        if not text or _PULSE_SKIP_RE.search(text):
            continue
        for clause in re.split(r"[.;!?]\s+|\n+", text):
            candidate = _strip_pulse_lead_noise(clause)
            candidate = re.sub(r"\s+", " ", candidate).strip(" -")
            if len(candidate) < 28 or len(candidate) > 150:
                continue
            if _PULSE_BAG_RE.match(candidate):
                continue
            lowered = candidate.casefold()
            if lowered.startswith(("это ", "так ", "как ", "что ", "чтобы ")):
                continue
            if lowered in {"два поста", "три поста", "несколько постов"}:
                continue
            candidate_tokens = {
                _theme_token_stem(token)
                for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9+\-]+", candidate)
            }
            if candidate_tokens and candidate_tokens <= theme_tokens and len(candidate_tokens) <= 4:
                continue
            if _PULSE_VERBISH_RE.search(candidate):
                return candidate
    return ""


def _normalize_pulse_signature(line: str) -> str:
    parts = re.split(r"\s+[—-]\s+", line, maxsplit=1)
    if len(parts) == 2:
        line = parts[1]
    else:
        match = _STORYLINE_PREFIX_RE.match(line.strip())
        if match and len(match.group(1).split()) <= 5:
            line = match.group(2)
    lowered = line.casefold()
    lowered = re.sub(r"[^a-zа-яё0-9 ]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    tokens = [_theme_token_stem(token) for token in lowered.split() if token]
    return " ".join(tokens[:8])


def _theme_quality(line: str) -> tuple[int, int, int]:
    parts = re.split(r"\s+[—-]\s+", line, maxsplit=1)
    theme = parts[0].strip() if parts else line.strip()
    source_penalty = 1 if _SOURCEISH_THEME_RE.search(theme) else 0
    weak_penalty = 1 if _is_weak_theme_label(theme) else 0
    return (-source_penalty - weak_penalty, len(theme.split()), len(theme))


def _is_fact_like_pulse(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", text or "").strip(" •-")
    if len(cleaned) < 18 or len(cleaned) > 170:
        return False
    if _PULSE_BAG_RE.match(cleaned):
        return False
    if _PULSE_SKIP_RE.search(cleaned) or _PULSE_GARBAGE_RE.search(cleaned):
        return False
    lowered = cleaned.casefold()
    if any(marker in lowered for marker in _PULSE_GENERIC_FACT_MARKERS):
        return False
    if "," in cleaned and not (_PULSE_VERBISH_RE.search(cleaned) or re.search(r"\d", cleaned)):
        return False
    if not (_PULSE_VERBISH_RE.search(cleaned) or re.search(r"\d", cleaned)):
        return False
    return len(cleaned.split()) >= 4


def _sanitize_theme_line(line: str) -> str:
    cleaned = _clean_text(line, max_len=220).lstrip("• ").strip()
    if not cleaned:
        return ""
    parts = re.split(r"\s+[—-]\s+", cleaned, maxsplit=1)
    if len(parts) != 2:
        return ""
    theme, fact = parts[0].strip(), parts[1].strip()
    if not theme or not fact or len(theme) > 42 or _PULSE_GARBAGE_RE.search(theme):
        return ""
    if not _is_fact_like_pulse(fact):
        return ""
    return f"{theme} — {fact}"


def _sanitize_theme_lines(lines: list[str], max_items: int = 6) -> list[str]:
    best_by_signature: dict[str, str] = {}
    for line in lines:
        cleaned = _sanitize_theme_line(line)
        if not cleaned:
            continue
        signature = _normalize_pulse_signature(cleaned)
        if not signature:
            continue
        current = best_by_signature.get(signature)
        if current is None or _theme_quality(cleaned) > _theme_quality(current):
            best_by_signature[signature] = cleaned
    cleaned_lines: list[str] = []
    for line in best_by_signature.values():
        cleaned_lines.append(line)
        if len(cleaned_lines) >= max_items:
            break
    return cleaned_lines


def _bucket_match_score(text: str, bucket_name: str, profile: dict | None = None) -> float:
    lowered = text.casefold()
    score = 0.0
    for candidate_name, pattern, seed_terms in _DIVERSITY_BUCKETS:
        if candidate_name != bucket_name:
            continue
        if pattern.search(text):
            score += 3.0
        score += sum(0.35 for term in seed_terms if term in lowered)
        if profile:
            learned_terms = _bucket_state(profile, bucket_name).get("learned_terms", {})
            for term, term_score in learned_terms.items():
                if term in lowered:
                    score += min(1.6, float(term_score) * 0.25)
        break
    return score


def _diversity_bucket(line: str, profile: dict | None = None) -> str:
    best_bucket = "other"
    best_score = 0.0
    for bucket_name, _, _ in _DIVERSITY_BUCKETS:
        bucket_score = _bucket_match_score(line, bucket_name, profile)
        if bucket_score > best_score:
            best_bucket = bucket_name
            best_score = bucket_score
    return best_bucket


def _interest_weight(bucket_name: str, profile: dict | None) -> float:
    if not profile or bucket_name == "other":
        return 1.0
    state = _bucket_state(profile, bucket_name)
    momentum = float(state.get("momentum", 0.0) or 0.0)
    learned_count = len(state.get("learned_terms", {}) or {})
    return 1.0 + min(0.45, momentum * 0.05) + min(0.2, learned_count * 0.01)


def _repeat_penalty(signature: str, profile: dict | None) -> float:
    if not profile or not signature:
        return 0.0
    now_ts = int(time.time())
    penalty = 0.0
    for item in profile.get("recent_signatures", []):
        if not isinstance(item, dict):
            continue
        if item.get("signature") != signature:
            continue
        age_sec = max(0, now_ts - int(item.get("seen_at", 0) or 0))
        if age_sec <= 24 * 3600:
            penalty = max(penalty, 2.2)
        elif age_sec <= _RECENT_SIGNATURE_WINDOW_SEC:
            penalty = max(penalty, 1.1)
    return penalty


def _theme_quality_score(line: str) -> float:
    quality, word_count, theme_len = _theme_quality(line)
    return float(quality * 2 + min(word_count, 5) * 0.3 + min(theme_len, 32) * 0.02)


def _rank_line(line: str, profile: dict | None, *, order_hint: int = 0) -> dict:
    signature = _normalize_pulse_signature(line)
    bucket = _diversity_bucket(line, profile)
    return {
        "line": line,
        "signature": signature,
        "bucket": bucket,
        "score": (
            10.0
            - min(order_hint, 12) * 0.35
            + _theme_quality_score(line)
            + _interest_weight(bucket, profile)
            - _repeat_penalty(signature, profile)
        ),
    }


def _select_diverse_lines(lines: list[str], profile: dict | None, max_items: int) -> list[str]:
    ranked = [_rank_line(line, profile, order_hint=index) for index, line in enumerate(lines) if line]
    ranked.sort(key=lambda item: (item["score"], _theme_quality_score(item["line"])), reverse=True)
    if len(ranked) <= 2:
        return [item["line"] for item in ranked[:max_items]]

    best_per_bucket: dict[str, dict] = {}
    remainder: list[dict] = []
    for item in ranked:
        bucket = item["bucket"]
        if bucket not in best_per_bucket:
            best_per_bucket[bucket] = item
        else:
            remainder.append(item)

    selected: list[str] = []
    selected_signatures: set[str] = set()
    bucket_counts: Counter[str] = Counter()

    for item in sorted(best_per_bucket.values(), key=lambda current: current["score"], reverse=True):
        if item["signature"] and item["signature"] in selected_signatures:
            continue
        selected.append(item["line"])
        if item["signature"]:
            selected_signatures.add(item["signature"])
        bucket_counts[item["bucket"]] += 1
        if len(selected) >= max_items:
            return selected

    for item in remainder:
        if item["signature"] and item["signature"] in selected_signatures:
            continue
        if bucket_counts[item["bucket"]] >= 2:
            continue
        selected.append(item["line"])
        if item["signature"]:
            selected_signatures.add(item["signature"])
        bucket_counts[item["bucket"]] += 1
        if len(selected) >= max_items:
            break
    return selected


def _diversify_lines(lines: list[str], max_items: int) -> list[str]:
    return lines[:max_items]


def _extract_learning_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for candidate in _theme_candidates(text):
        normalized = _normalize_learning_term(candidate)
        if normalized:
            terms.add(normalized)
    for token in _theme_tokens(text):
        normalized = _normalize_learning_term(token)
        if normalized:
            terms.add(normalized)
    return terms


def _prune_recent_signatures(profile: dict):
    now_ts = int(time.time())
    kept: list[dict] = []
    for item in profile.get("recent_signatures", []):
        if not isinstance(item, dict):
            continue
        seen_at = int(item.get("seen_at", 0) or 0)
        if now_ts - seen_at <= _RECENT_SIGNATURE_WINDOW_SEC:
            kept.append(item)
    profile["recent_signatures"] = kept[-_MAX_RECENT_SIGNATURES:]


def _update_interest_profile(profile: dict, posts: list[Post], selected_lines: list[str]):
    now_ts = int(time.time())
    bucket_hits: Counter[str] = Counter()
    bucket_terms: dict[str, Counter[str]] = defaultdict(Counter)

    for post in posts:
        bucket = _diversity_bucket(post.text, profile)
        if bucket == "other":
            continue
        bucket_hits[bucket] += max(1, min(4, int(round(post.score)) or 1))
        for term in _extract_learning_terms(post.text):
            bucket_terms[bucket][term] += 1

    for bucket_name, _, _ in _DIVERSITY_BUCKETS:
        state = _bucket_state(profile, bucket_name)
        state["momentum"] = round(float(state.get("momentum", 0.0) or 0.0) * 0.72 + bucket_hits.get(bucket_name, 0), 3)
        if bucket_hits.get(bucket_name, 0):
            state["last_seen_at"] = now_ts

        learned_terms = {
            term: round(float(score) * 0.9, 3)
            for term, score in dict(state.get("learned_terms", {}) or {}).items()
        }
        for term, count in bucket_terms.get(bucket_name, {}).items():
            if count < 2:
                continue
            learned_terms[term] = round(learned_terms.get(term, 0.0) + count * 1.1, 3)

        ordered_terms = sorted(
            learned_terms.items(),
            key=lambda item: (-item[1], -len(item[0].split()), item[0]),
        )
        state["learned_terms"] = {
            term: score
            for term, score in ordered_terms[:_MAX_LEARNED_TERMS_PER_BUCKET]
            if score >= 1.5
        }

    _prune_recent_signatures(profile)
    recent_signatures = list(profile.get("recent_signatures", []))
    for line in selected_lines:
        signature = _normalize_pulse_signature(line)
        if not signature:
            continue
        recent_signatures.append(
            {
                "signature": signature,
                "bucket": _diversity_bucket(line, profile),
                "seen_at": now_ts,
            }
        )
    profile["recent_signatures"] = recent_signatures[-_MAX_RECENT_SIGNATURES:]
    profile["updated_at"] = now_ts


def _best_theme_partner(
    anchor_key: str,
    cluster_posts: list[Post],
    post_anchor_keys: dict[tuple[int, int], list[str]],
    anchor_post_sets: dict[str, set[tuple[int, int]]],
    anchor_display: dict[str, str],
) -> str:
    partner_counts: Counter[str] = Counter()
    partner_channels: dict[str, set[int]] = defaultdict(set)
    anchor_tokens = {_theme_token_stem(token) for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9+\-]+", anchor_key)}
    for post in cluster_posts:
        post_key = (post.channel_id, post.msg_id)
        for candidate in post_anchor_keys.get(post_key, []):
            if candidate == anchor_key:
                continue
            candidate_tokens = {_theme_token_stem(token) for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9+\-]+", candidate)}
            if not candidate_tokens or candidate_tokens & anchor_tokens:
                continue
            partner_counts[candidate] += 1
            partner_channels[candidate].add(post.channel_id)

    ordered = sorted(
        partner_counts,
        key=lambda candidate: (
            -len(partner_channels[candidate]),
            -partner_counts[candidate],
            -len(anchor_post_sets.get(candidate, set())),
            len(anchor_display.get(candidate, candidate).split()),
            anchor_display.get(candidate, candidate).lower(),
        ),
    )
    for candidate in ordered:
        if partner_counts[candidate] >= 2 or len(partner_channels[candidate]) >= 2:
            return anchor_display.get(candidate, candidate)
    return ""


def _extract_themes(posts: list[Post], max_items: int = 6) -> list[str]:
    counts: Counter[str] = Counter()
    weighted: dict[str, float] = {}
    max_score: dict[str, float] = {}
    display: dict[str, str] = {}
    candidate_posts: dict[str, list[Post]] = defaultdict(list)
    candidate_channels: dict[str, set[int]] = defaultdict(set)
    post_anchor_keys: dict[tuple[int, int], list[str]] = defaultdict(list)

    for post in posts:
        seen: set[str] = set()
        for candidate in _theme_candidates(post.text):
            normalized = candidate.casefold()
            if normalized in seen or normalized in _THEME_BLOCKED:
                continue
            seen.add(normalized)
            counts[normalized] += 1
            weighted[normalized] = weighted.get(normalized, 0.0) + max(post.score, 1.0)
            max_score[normalized] = max(max_score.get(normalized, 0.0), post.score)
            display.setdefault(normalized, candidate)
            candidate_posts[normalized].append(post)
            candidate_channels[normalized].add(post.channel_id)
            post_anchor_keys[(post.channel_id, post.msg_id)].append(normalized)

    ordered = sorted(
        counts,
        key=lambda key: (
            -len(candidate_channels[key]),
            -counts[key],
            -weighted.get(key, 0.0),
            len(display[key].split()),
            display[key].lower(),
        ),
    )

    selected: list[str] = []
    used_tokens: list[set[str]] = []
    selected_post_sets: list[set[tuple[int, int]]] = []
    selected_signatures: set[str] = set()
    anchor_post_sets = {
        anchor_key: {(post.channel_id, post.msg_id) for post in posts_for_anchor}
        for anchor_key, posts_for_anchor in candidate_posts.items()
    }
    for key in ordered:
        label = display[key]
        channel_count = len(candidate_channels[key])
        if counts[key] < 2 and channel_count < 2 and max_score.get(key, 0.0) < 8:
            continue
        token_set = {_theme_token_stem(token) for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9+\-]+", label)}
        if not token_set:
            continue
        if any(token_set <= existing or existing <= token_set for existing in used_tokens):
            continue
        post_set = {(post.channel_id, post.msg_id) for post in candidate_posts[key]}
        if any(
            len(post_set & existing) / max(1, min(len(post_set), len(existing))) >= 0.6
            for existing in selected_post_sets
        ):
            continue

        label_display = label
        cluster_posts = sorted(
            candidate_posts[key],
            key=lambda post: (post.score, post.date.timestamp()),
            reverse=True,
        )
        partner_display = _best_theme_partner(
            key,
            cluster_posts,
            post_anchor_keys,
            anchor_post_sets,
            display,
        )
        if partner_display:
            partner_tokens = {_theme_token_stem(token) for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9+\-]+", partner_display)}
            if partner_tokens and not (partner_tokens & token_set):
                label_display = f"{label} / {partner_display}"
                token_set |= partner_tokens

        label_display = _pulse_theme_label(label_display, cluster_posts)
        if not label_display:
            continue

        fact_line = _pulse_fact_from_posts(cluster_posts, label_display)
        if not fact_line:
            continue

        line = _sanitize_theme_line(f"{label_display} — {fact_line}")
        if not line:
            continue
        signature = _normalize_pulse_signature(line)
        if not signature or signature in selected_signatures:
            continue

        selected.append(line)
        selected_signatures.add(signature)
        used_tokens.append(token_set)
        selected_post_sets.append(post_set)
        if len(selected) >= max_items:
            break

    return _sanitize_theme_lines(selected, max_items=max_items)


def _storyline_from_text(value: str, *, channel: str = "") -> str:
    cleaned = _clean_text(value, max_len=220).lstrip("• ").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*[📌✨🧭🗂]+\s*", "", cleaned)
    match = _STORYLINE_PREFIX_RE.match(cleaned)
    if match and len(match.group(1).split()) <= 5:
        cleaned = match.group(2).strip()
    if channel:
        prefix = f"{channel}:"
        if cleaned.casefold().startswith(prefix.casefold()):
            cleaned = cleaned[len(prefix):].strip()
    cleaned = _strip_pulse_lead_noise(cleaned)
    cleaned = re.sub(r"^\s*(пульс дня|главное|сюжет|тема)\s*[:.-]\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    if len(cleaned) < 24 or len(cleaned) > 200:
        return ""
    if _PULSE_SKIP_RE.search(cleaned) or _PULSE_GARBAGE_RE.search(cleaned):
        return ""
    return cleaned


def _iter_item_summaries(items: list[DigestItem]) -> list[str]:
    return [_storyline_from_text(item.summary, channel=item.channel) for item in items]


def _fallback_storylines(
    posts: list[Post],
    *,
    profile: dict | None,
    lead: list[str],
    must_read: list[DigestItem],
    sections: list[DigestSection],
    new_glance: list[DigestItem],
    max_items: int,
) -> list[str]:
    candidates: list[str] = []
    candidates.extend(_storyline_from_text(item) for item in lead)
    candidates.extend(_iter_item_summaries(must_read))
    for section in sections:
        candidates.extend(_iter_item_summaries(section.items))
    candidates.extend(_iter_item_summaries(new_glance))

    ordered_posts = sorted(
        posts,
        key=lambda post: (post.score, len(post.also_mentioned), post.date.timestamp()),
        reverse=True,
    )
    for post in ordered_posts:
        text = _clean_text(post.text, max_len=260)
        if not text or _PULSE_SKIP_RE.search(text):
            continue
        for clause in re.split(r"[.;!?]\s+|\n+", text):
            storyline = _storyline_from_text(clause, channel=post.channel_name)
            if storyline:
                candidates.append(storyline)

    results: list[str] = []
    seen_signatures: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        signature = _normalize_pulse_signature(candidate)
        if not signature or signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        results.append(candidate)
    return _select_diverse_lines(results, profile, max_items=max_items)


def build_pulse_lines(
    posts: list[Post],
    *,
    raw_themes: list[str] | None = None,
    lead: list[str] | None = None,
    must_read: list[DigestItem] | None = None,
    sections: list[DigestSection] | None = None,
    new_glance: list[DigestItem] | None = None,
    max_items: int = 6,
) -> list[str]:
    profile = _load_profile()

    themes = _select_diverse_lines(
        _sanitize_theme_lines(list(raw_themes or []), max_items=max_items * 4),
        profile,
        max_items=max_items,
    )
    if themes:
        _update_interest_profile(profile, posts, themes)
        _save_profile(profile)
        return themes

    themes = _select_diverse_lines(
        _extract_themes(posts, max_items=max_items * 4),
        profile,
        max_items=max_items,
    )
    if themes:
        _update_interest_profile(profile, posts, themes)
        _save_profile(profile)
        return themes

    themes = _fallback_storylines(
        posts,
        profile=profile,
        lead=list(lead or []),
        must_read=list(must_read or []),
        sections=list(sections or []),
        new_glance=list(new_glance or []),
        max_items=max_items,
    )
    _update_interest_profile(profile, posts, themes)
    _save_profile(profile)
    return themes
