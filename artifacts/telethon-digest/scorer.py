"""
Rule-based post scoring (pure scoring module — no Telegram I/O, no LLM calls).

score = folder_tier_priority
      + channel_position_boost  (soft hint, not hard gate)
      + pin_boost               (soft hint, not hard gate)
      + relevance_boost         (keyword matching)

LLM dedup is handled by dedup.py.
LLM summarization is handled by summarizer.py.
"""
import logging
import re
from collections import defaultdict
from typing import List

from models import Post

logger = logging.getLogger(__name__)

# ── Relevance keywords ──────────────────────────────────────────────────────
_HIGH_RELEVANCE = re.compile(
    r"\b(AI|LLM|GPT|Claude|Gemini|стартап|инвестиц|funding|Series [A-Z]|IPO|M&A|"
    r"ставка ЦБ|ключевая ставка|Сбер|Тинькофф|рынок акций|крипто|Bitcoin|blockchain|"
    r"security|privacy|telegram|automation|agent|GenAI|EB1|visa|payment|payments|"
    r"growth|leadgen|SWE-bench|Terminal-Bench|SynthID)\b",
    re.IGNORECASE,
)
_MED_RELEVANCE = re.compile(
    r"\b(технолог|продукт|бизнес|экономик|финансы|рынок|маркет|аналитик|тренд|"
    r"карьер|work|продаж|банк|финтех|automation|AI|агент)\b",
    re.IGNORECASE,
)
_TECH_RELEVANCE = re.compile(
    r"\b(AI|LLM|GPT|Claude|Gemini|agent|automation|security|privacy|telegram|"
    r"SWE-bench|Terminal-Bench|SynthID|GitHub|API|benchmark|HKUDS|GenAI|developer)\b",
    re.IGNORECASE,
)
_STATUS_NOISE = re.compile(
    r"(community pulse|channel posts:\s*\d+|paid group:\s*\d+|new subscribers:\s*\d+|"
    r"shared:\s*\d+|longreads in group|last 24h ending|active\s*•|shared:\s*\d+\s*links)",
    re.IGNORECASE,
)
_PROMO_NOISE = re.compile(
    r"(не пропустите|отраслевые мероприятия|форум|конференц|вебинар|митап|"
    r"регистрац|скидк|партнерский материал|реклама|премия|мероприятия на следующей неделе|"
    r"практикум|open mic)",
    re.IGNORECASE,
)
_DIARY_NOISE = re.compile(
    r"(вижу ваш интерес|дропну|предыстория|сегодня был 1й день|мастер майнда|"
    r"я себе тут выписал|грустный в вечер пятницы|настроение поднялось|ловите инсайт|"
    r"пошел ебашить фабрики|выгоревший|хороших выходных|концерт)",
    re.IGNORECASE,
)

# ── Helpers ──────────────────────────────────────────────────────────────────

def _channel_position_score(position: int, config: dict) -> int:
    """Return boost based on channel's 0-based index within its Telegram folder."""
    boosts = config.get("channel_position_boost", {})
    if position <= 3:
        return boosts.get("top_1_4", 3)
    if position <= 7:
        return boosts.get("top_5_8", 2)
    if position <= 11:
        return boosts.get("top_9_12", 1)
    return boosts.get("other", 0)


def _relevance_boost(text: str) -> float:
    if _HIGH_RELEVANCE.search(text):
        return 2.0
    if _MED_RELEVANCE.search(text):
        return 1.0
    return 0.0


def _tech_boost(text: str) -> float:
    return 1.25 if _TECH_RELEVANCE.search(text) else 0.0


def _is_hard_noise(text: str) -> bool:
    return bool(_STATUS_NOISE.search(text or ""))


def _noise_penalty(text: str) -> float:
    content = text or ""
    penalty = 0.0
    if _PROMO_NOISE.search(content):
        penalty += 2.5
    if _DIARY_NOISE.search(content) and not _HIGH_RELEVANCE.search(content):
        penalty += 1.75
    return penalty


def _tier_priority(folder_name: str, config: dict) -> int:
    """Return tier priority (5/3/1) for a folder based on folder_tiers config."""
    tiers = config.get("folder_tiers", {})
    for tier_key, tier_cfg in tiers.items():
        folders = [f.lower() for f in tier_cfg.get("folders", [])]
        if folder_name.lower() in folders:
            return tier_cfg.get("priority", 1)
    # Tier C default
    return tiers.get("C", {}).get("priority", 1)


# ── Main scoring pass ────────────────────────────────────────────────────────

def score_posts(posts: List[Post], config: dict) -> List[Post]:
    configured_pin_boost = config.get("pin_boost", 4)
    configured_min_score = config.get("min_score", 2)
    configured_top_n = config.get("top_posts_for_llm", 30)
    pin_boost = configured_pin_boost * 0.4
    min_score = max(1, configured_min_score - 1)
    if len(posts) >= 50:
        top_n = max(configured_top_n, 42)
    elif len(posts) >= 30:
        top_n = max(configured_top_n, 36)
    else:
        top_n = configured_top_n

    for p in posts:
        tier_pri = _tier_priority(p.folder_name, config)
        pos_boost = _channel_position_score(getattr(p, "channel_position", 0), config) * 0.65
        pin = pin_boost if p.is_pinned else 0
        rel = _relevance_boost(p.text)
        tech = _tech_boost(p.text)
        penalty = _noise_penalty(p.text)
        p.score = tier_pri + pos_boost + pin + rel + tech - penalty

    filtered = [p for p in posts if p.score >= min_score and not _is_hard_noise(p.text)]

    if len(filtered) < len(posts):
        logger.info(
            f"Scoring: {len(posts)} posts → {len(filtered)} after min_score={min_score} filter"
        )

    filtered.sort(key=lambda p: (p.score, p.date.timestamp()), reverse=True)
    if len(filtered) <= top_n:
        logger.info(f"Scoring: top-{top_n} selected ({len(filtered)} posts)")
        return filtered

    selected: list[Post] = []
    channel_counts: dict[int, int] = defaultdict(int)
    folder_counts: dict[str, int] = defaultdict(int)
    folder_soft_cap = max(3, min(6, top_n // 6))
    folder_hard_cap = max(folder_soft_cap + 1, min(9, top_n // 4))
    primary_target = max(1, int(top_n * 0.7))

    # Coverage pass: keep at least one non-noise representative from each active
    # priority folder so important scopes do not disappear from the digest.
    best_per_folder: dict[str, Post] = {}
    for post in filtered:
        best_per_folder.setdefault(post.folder_name, post)

    folder_representatives = sorted(
        best_per_folder.values(),
        key=lambda post: (
            _tier_priority(post.folder_name, config) >= 5 and 0 or 1,
            _tier_priority(post.folder_name, config) >= 3 and 0 or 1,
            -post.score,
            post.folder_name.lower(),
        ),
    )

    coverage_limit = min(max(6, top_n // 2), top_n)
    for post in folder_representatives:
        tier_priority = _tier_priority(post.folder_name, config)
        if tier_priority < 3:
            continue
        if len(selected) >= coverage_limit:
            break
        selected.append(post)
        channel_counts[post.channel_id] += 1
        folder_counts[post.folder_name] += 1

    for post in filtered:
        if len(selected) >= primary_target:
            break
        if post in selected:
            continue
        if channel_counts[post.channel_id] >= 1:
            continue
        if folder_counts[post.folder_name] >= folder_soft_cap:
            continue
        selected.append(post)
        channel_counts[post.channel_id] += 1
        folder_counts[post.folder_name] += 1

    for post in filtered:
        if len(selected) >= top_n:
            break
        if post in selected:
            continue
        if channel_counts[post.channel_id] >= 2:
            continue
        if folder_counts[post.folder_name] >= folder_hard_cap:
            continue
        selected.append(post)
        channel_counts[post.channel_id] += 1
        folder_counts[post.folder_name] += 1

    for post in filtered:
        if len(selected) >= top_n:
            break
        if post in selected:
            continue
        if channel_counts[post.channel_id] >= 3:
            continue
        selected.append(post)
        channel_counts[post.channel_id] += 1
        folder_counts[post.folder_name] += 1

    logger.info(
        "Scoring: selected %s posts with diversity pass (target=%s, unique_channels=%s, folders=%s)",
        len(selected),
        top_n,
        len({post.channel_id for post in selected}),
        len({post.folder_name for post in selected}),
    )
    return selected
