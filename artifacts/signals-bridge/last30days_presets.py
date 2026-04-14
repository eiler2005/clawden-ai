"""
Preset helpers for last30days digests.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


WORLD_RADAR_PRESET_ID = "world-radar-v1"
PERSONAL_FEED_PRESET_ID = "personal-feed-v1"
PLATFORM_PULSE_PRESET_ID = "platform-pulse-v1"

DEFAULT_PRESET_ALIASES = {
    WORLD_RADAR_PRESET_ID: PERSONAL_FEED_PRESET_ID,
}

DEFAULT_PERSONAL_FEED_QUERY_BUNDLE = [
    "OpenAI Anthropic Google Meta xAI Nvidia Apple Microsoft Amazon launches product roadmap",
    "markets macro inflation tariffs antitrust regulation geopolitics elections trade oil chips",
    "X TikTok YouTube Instagram Reddit Bluesky consumer apps platform changes viral products",
    "creator economy Veo Runway Pika Sora Midjourney YouTube media workflows",
    "startup funding acquisitions IPO venture capital big tech deals unicorns",
    "robotics humanoids autonomous vehicles space biotech semiconductors frontier tech",
    "GitHub open source MCP agents developer tools infrastructure repos",
    "internet culture memes controversies movements essays podcasts viral narratives",
]

DEFAULT_PLATFORM_PULSE_QUERY_BUNDLE = [
    "AI models labs launches product updates frontier labs openai anthropic google xai meta",
    "developer tools open source agents MCP coding workflows repos builders",
    "robotics humanoids autonomous vehicles hardware frontier science",
    "consumer apps creator economy social platforms streaming internet products",
    "world news geopolitics economics markets regulation",
    "internet culture memes controversies movements podcasts narratives",
]

DEFAULT_PERSONAL_FEED_REDDIT_FEEDS = [
    "worldnews",
    "technology",
    "science",
    "Futurology",
    "economics",
    "geopolitics",
    "artificial",
    "MachineLearning",
    "OutOfTheLoop",
]

DEFAULT_PLATFORM_PULSE_REDDIT_SUBREDDITS = [
    "technology",
    "science",
    "Futurology",
    "MachineLearning",
    "artificial",
    "worldnews",
    "geopolitics",
    "economics",
    "OutOfTheLoop",
    "singularity",
    "robotics",
    "wallstreetbets",
    "modelcontextprotocol",
]

DEFAULT_PLATFORM_PULSE_CORE_SOURCES = ["reddit", "hackernews", "x", "bluesky"]
DEFAULT_PLATFORM_PULSE_EXPERIMENTAL_SOURCES = ["github", "youtube", "polymarket"]


def ensure_last30days_presets(current: dict[str, Any]) -> dict[str, Any]:
    result = dict(current or {})
    result.setdefault("preset_id", WORLD_RADAR_PRESET_ID)
    result.setdefault("preset_aliases", {})
    aliases = dict(DEFAULT_PRESET_ALIASES)
    aliases.update(dict(result.get("preset_aliases", {}) or {}))
    result["preset_aliases"] = aliases

    presets = dict(result.get("presets", {}) or {})
    presets.setdefault(PERSONAL_FEED_PRESET_ID, build_personal_feed_preset_from_legacy(result))
    presets.setdefault(PLATFORM_PULSE_PRESET_ID, build_default_platform_pulse_preset(result))
    result["presets"] = presets
    return result


def build_personal_feed_preset_from_legacy(current: dict[str, Any]) -> dict[str, Any]:
    topic_cfg = dict(current.get("telegram", {}) or {})
    obsidian_cfg = dict(current.get("obsidian", {}) or {})
    platform_sources = dict(current.get("platform_sources", {}) or {})
    reddit_cfg = dict(platform_sources.get("reddit", {}) or {})
    if not reddit_cfg.get("feeds"):
        reddit_cfg["feeds"] = list(DEFAULT_PERSONAL_FEED_REDDIT_FEEDS)
    if reddit_cfg:
        platform_sources["reddit"] = reddit_cfg
    return {
        "profile": "personal-feed",
        "display_name": "Personal Feed",
        "mode": str(current.get("mode", "compact")),
        "telegram": {
            "topic_name": str(topic_cfg.get("topic_name", "last30daysTrend")),
            "topic_id": int(topic_cfg.get("topic_id", 0) or 0),
        },
        "obsidian": {
            "root": str(obsidian_cfg.get("root", "Last30Days")),
        },
        "max_items": int(current.get("max_items", 10) or 10),
        "query_bundle": [str(item).strip() for item in current.get("query_bundle", []) if str(item).strip()] or list(DEFAULT_PERSONAL_FEED_QUERY_BUNDLE),
        "platform_sources": platform_sources,
    }


def build_default_platform_pulse_preset(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": "platform-pulse",
        "display_name": "Platform Pulse",
        "mode": "compact",
        "telegram": {
            "topic_name": "platformPulse",
            "topic_id": 0,
        },
        "obsidian": {
            "root": "PlatformPulse",
        },
        "max_items": 12,
        "query_bundle": list(DEFAULT_PLATFORM_PULSE_QUERY_BUNDLE),
        "core_sources": list(DEFAULT_PLATFORM_PULSE_CORE_SOURCES),
        "experimental_sources": list(DEFAULT_PLATFORM_PULSE_EXPERIMENTAL_SOURCES),
        "platform_sources": {
            "search": ",".join(DEFAULT_PLATFORM_PULSE_CORE_SOURCES + DEFAULT_PLATFORM_PULSE_EXPERIMENTAL_SOURCES),
            "reddit": {
                "feeds": list(DEFAULT_PLATFORM_PULSE_REDDIT_SUBREDDITS),
            },
            "github": {
                "trending": True,
            },
        },
    }


def resolve_last30days_preset(config: dict[str, Any], preset_id: str | None) -> tuple[str, str, dict[str, Any]]:
    current = ensure_last30days_presets(dict(config.get("last30days", {}) or {}))
    requested_id = str(preset_id or current.get("preset_id", WORLD_RADAR_PRESET_ID)).strip() or WORLD_RADAR_PRESET_ID
    canonical_id = str(current.get("preset_aliases", {}).get(requested_id, requested_id))
    presets = dict(current.get("presets", {}) or {})
    preset = deepcopy(dict(presets.get(canonical_id) or build_personal_feed_preset_from_legacy(current)))
    if canonical_id == PERSONAL_FEED_PRESET_ID:
        preset = _merge_personal_feed_override(preset, build_personal_feed_preset_from_legacy(current))
    preset.setdefault("profile", "platform-pulse" if canonical_id == PLATFORM_PULSE_PRESET_ID else "personal-feed")
    preset.setdefault("display_name", "Platform Pulse" if preset["profile"] == "platform-pulse" else "Personal Feed")
    preset.setdefault("mode", "compact")
    preset.setdefault("telegram", {})
    preset["telegram"].setdefault("topic_name", "platformPulse" if preset["profile"] == "platform-pulse" else "last30daysTrend")
    preset["telegram"].setdefault("topic_id", 0)
    preset.setdefault("obsidian", {})
    preset["obsidian"].setdefault("root", "PlatformPulse" if preset["profile"] == "platform-pulse" else "Last30Days")
    preset.setdefault("max_items", 12 if preset["profile"] == "platform-pulse" else 10)
    preset.setdefault("query_bundle", list(DEFAULT_PLATFORM_PULSE_QUERY_BUNDLE if preset["profile"] == "platform-pulse" else DEFAULT_PERSONAL_FEED_QUERY_BUNDLE))
    preset.setdefault("platform_sources", {})
    if preset["profile"] == "platform-pulse":
        preset.setdefault("core_sources", list(DEFAULT_PLATFORM_PULSE_CORE_SOURCES))
        preset.setdefault("experimental_sources", list(DEFAULT_PLATFORM_PULSE_EXPERIMENTAL_SOURCES))
    return requested_id, canonical_id, preset


def _merge_personal_feed_override(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key in ("mode", "display_name", "max_items", "query_bundle"):
        if key in override:
            merged[key] = deepcopy(override[key])
    for key in ("telegram", "obsidian", "platform_sources"):
        if key in override:
            current = dict(merged.get(key, {}) or {})
            current.update(deepcopy(dict(override.get(key, {}) or {})))
            merged[key] = current
    merged["profile"] = "personal-feed"
    return merged
