"""
Run pinned last30days queries and fold them into one compact daily digest.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from models import Last30DaysCategorySection, Last30DaysDigest, Last30DaysTheme


DEFAULT_QUERY_BUNDLE = [
    "OpenAI Anthropic Google DeepMind xAI Nvidia Apple Microsoft product launches AI research breakthroughs",
    "AI policy regulation antitrust government tech industry economy inflation tariffs geopolitics",
    "open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks",
    "machine learning research papers models benchmarks reasoning agents multimodal academic",
    "startup funding rounds acquisitions mergers venture capital unicorns IPO deals exits",
    "robotics autonomous vehicles space biotech semiconductors hardware frontier science",
    "content platforms creator economy streaming social media viral culture internet trends",
    "semiconductors chips supply chain trade war Taiwan defense cybersecurity national security",
]

RESCUE_QUERY_BUNDLE = {
    "OpenAI Anthropic Google DeepMind xAI Nvidia Apple Microsoft product launches AI research breakthroughs": [
        "OpenAI",
        "Anthropic",
        "Google AI",
        "DeepMind",
        "xAI",
        "Nvidia AI",
        "Microsoft AI",
    ],
    "AI policy regulation antitrust government tech industry economy inflation tariffs geopolitics": [
        "AI regulation",
        "antitrust tech",
        "inflation",
        "tariffs",
        "geopolitics",
        "AI policy government",
    ],
    "open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks": [
        "GitHub open source",
        "MCP protocol",
        "AI agents open source",
        "developer tools",
        "infrastructure repos",
        "open source frameworks",
    ],
    "machine learning research papers models benchmarks reasoning agents multimodal academic": [
        "AI research papers",
        "machine learning models",
        "benchmarks AI",
        "reasoning models",
        "multimodal AI",
    ],
    "startup funding rounds acquisitions mergers venture capital unicorns IPO deals exits": [
        "startup funding",
        "acquisitions tech",
        "IPO",
        "venture capital",
        "unicorns",
    ],
    "robotics autonomous vehicles space biotech semiconductors hardware frontier science": [
        "robotics",
        "autonomous vehicles",
        "space tech",
        "biotech",
        "semiconductors hardware",
    ],
    "content platforms creator economy streaming social media viral culture internet trends": [
        "creator economy",
        "streaming platforms",
        "social media trends",
        "viral internet",
        "content creators",
    ],
    "semiconductors chips supply chain trade war Taiwan defense cybersecurity national security": [
        "semiconductors chips",
        "supply chain tech",
        "trade war tech",
        "Taiwan chips",
        "cybersecurity",
    ],
}

GITHUB_REPO_HINTS = {
    "open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks": [
        "openclaw/openclaw",
        "modelcontextprotocol/servers",
        "openziti/mcp-gateway",
        "isteamhq/mcp-servers",
        "openai/codex",
        "google-gemini/gemini-cli",
        "langchain-ai/langgraph",
        "microsoft/markitdown",
    ],
    "GitHub open source": [
        "openclaw/openclaw",
        "openai/codex",
        "google-gemini/gemini-cli",
    ],
    "MCP protocol": [
        "modelcontextprotocol/servers",
        "openziti/mcp-gateway",
        "isteamhq/mcp-servers",
    ],
    "AI agents open source": [
        "openclaw/openclaw",
        "langchain-ai/langgraph",
    ],
    "developer tools": [
        "openai/codex",
        "google-gemini/gemini-cli",
        "microsoft/markitdown",
    ],
    "infrastructure repos": [
        "openziti/mcp-gateway",
        "modelcontextprotocol/servers",
    ],
    "open source frameworks": [
        "langchain-ai/langgraph",
        "microsoft/autogen",
    ],
}

CATEGORY_BIG_TECH = "Big Tech & AI"
CATEGORY_MARKETS = "Markets / Regulation / Geopolitics"
CATEGORY_CONSUMER = "Consumer Platforms"
CATEGORY_CREATOR = "Creator / Media"
CATEGORY_STARTUPS = "Startups / Deals"
CATEGORY_SCIENCE = "Science / Hardware"
CATEGORY_OPEN_SOURCE = "Open Source / Builders"
CATEGORY_WORLD = "World / Culture"

CATEGORY_ORDER = [
    CATEGORY_BIG_TECH,
    CATEGORY_MARKETS,
    CATEGORY_CONSUMER,
    CATEGORY_CREATOR,
    CATEGORY_STARTUPS,
    CATEGORY_SCIENCE,
    CATEGORY_OPEN_SOURCE,
    CATEGORY_WORLD,
]

QUERY_CATEGORY_MAP = {
    # Main query bundle
    "OpenAI Anthropic Google DeepMind xAI Nvidia Apple Microsoft product launches AI research breakthroughs": CATEGORY_BIG_TECH,
    "AI policy regulation antitrust government tech industry economy inflation tariffs geopolitics": CATEGORY_MARKETS,
    "open source developer tools MCP protocol agents GitHub trending repos infrastructure frameworks": CATEGORY_OPEN_SOURCE,
    "machine learning research papers models benchmarks reasoning agents multimodal academic": CATEGORY_BIG_TECH,
    "startup funding rounds acquisitions mergers venture capital unicorns IPO deals exits": CATEGORY_STARTUPS,
    "robotics autonomous vehicles space biotech semiconductors hardware frontier science": CATEGORY_SCIENCE,
    "content platforms creator economy streaming social media viral culture internet trends": CATEGORY_CONSUMER,
    "semiconductors chips supply chain trade war Taiwan defense cybersecurity national security": CATEGORY_MARKETS,
    # Big Tech rescue sub-queries
    "OpenAI": CATEGORY_BIG_TECH,
    "Anthropic": CATEGORY_BIG_TECH,
    "Google AI": CATEGORY_BIG_TECH,
    "DeepMind": CATEGORY_BIG_TECH,
    "Meta AI": CATEGORY_BIG_TECH,
    "xAI": CATEGORY_BIG_TECH,
    "Nvidia AI": CATEGORY_BIG_TECH,
    "Microsoft AI": CATEGORY_BIG_TECH,
    # ML research rescue sub-queries
    "AI research papers": CATEGORY_BIG_TECH,
    "machine learning models": CATEGORY_BIG_TECH,
    "benchmarks AI": CATEGORY_BIG_TECH,
    "reasoning models": CATEGORY_BIG_TECH,
    "multimodal AI": CATEGORY_BIG_TECH,
    # Markets rescue sub-queries
    "AI regulation": CATEGORY_MARKETS,
    "antitrust tech": CATEGORY_MARKETS,
    "inflation": CATEGORY_MARKETS,
    "tariffs": CATEGORY_MARKETS,
    "geopolitics": CATEGORY_MARKETS,
    "elections": CATEGORY_MARKETS,
    "AI policy government": CATEGORY_MARKETS,
    "semiconductors chips": CATEGORY_MARKETS,
    "supply chain tech": CATEGORY_MARKETS,
    "trade war tech": CATEGORY_MARKETS,
    "Taiwan chips": CATEGORY_MARKETS,
    "cybersecurity": CATEGORY_MARKETS,
    # Open source rescue sub-queries
    "GitHub open source": CATEGORY_OPEN_SOURCE,
    "MCP": CATEGORY_OPEN_SOURCE,
    "MCP protocol": CATEGORY_OPEN_SOURCE,
    "AI agents open source": CATEGORY_OPEN_SOURCE,
    "developer tools": CATEGORY_OPEN_SOURCE,
    "infrastructure repos": CATEGORY_OPEN_SOURCE,
    "open source frameworks": CATEGORY_OPEN_SOURCE,
    # Startups rescue sub-queries
    "startup funding": CATEGORY_STARTUPS,
    "acquisitions": CATEGORY_STARTUPS,
    "acquisitions tech": CATEGORY_STARTUPS,
    "IPO": CATEGORY_STARTUPS,
    "venture capital": CATEGORY_STARTUPS,
    "unicorns": CATEGORY_STARTUPS,
    # Science rescue sub-queries
    "robotics": CATEGORY_SCIENCE,
    "humanoids": CATEGORY_SCIENCE,
    "autonomous vehicles": CATEGORY_SCIENCE,
    "space tech": CATEGORY_SCIENCE,
    "biotech": CATEGORY_SCIENCE,
    "semiconductors hardware": CATEGORY_SCIENCE,
    # Consumer / creator rescue sub-queries
    "creator economy": CATEGORY_CREATOR,
    "streaming platforms": CATEGORY_CONSUMER,
    "social media trends": CATEGORY_CONSUMER,
    "content creators": CATEGORY_CREATOR,
    "Veo 3": CATEGORY_CREATOR,
    "Runway": CATEGORY_CREATOR,
    "Pika": CATEGORY_CREATOR,
    "Sora": CATEGORY_CREATOR,
    "Midjourney": CATEGORY_CREATOR,
    "YouTube creators": CATEGORY_CREATOR,
    # World / culture rescue sub-queries
    "viral internet": CATEGORY_WORLD,
    "internet culture": CATEGORY_WORLD,
    "memes": CATEGORY_WORLD,
    "controversies": CATEGORY_WORLD,
    "essays": CATEGORY_WORLD,
    "podcasts": CATEGORY_WORLD,
    "viral narratives": CATEGORY_WORLD,
}

CATEGORY_KEYWORDS = {
    CATEGORY_BIG_TECH: ["openai", "anthropic", "google", "deepmind", "xai", "meta", "nvidia", "microsoft", "amazon", "apple", "grok", "gemini", "claude", "gpt", "llama"],
    CATEGORY_MARKETS: ["market", "macro", "inflation", "tariff", "antitrust", "regulation", "geopolit", "election", "trade", "oil", "chip", "sanction", "sec", "eu", "china"],
    CATEGORY_CONSUMER: ["tiktok", "youtube", "instagram", "reddit", "bluesky", "consumer app", "platform", "viral product", "app update"],
    CATEGORY_CREATOR: ["creator", "veo", "runway", "pika", "sora", "midjourney", "film", "video", "image", "workflow", "media"],
    CATEGORY_STARTUPS: ["startup", "funding", "acquisition", "ipo", "venture", "unicorn", "valuation", "deal", "seed round", "series a", "series b"],
    CATEGORY_SCIENCE: ["robot", "humanoid", "autonomous", "space", "biotech", "semiconductor", "hardware", "drone", "frontier tech"],
    CATEGORY_OPEN_SOURCE: ["github", "open source", "mcp", "repo", "developer tool", "infrastructure", "agent framework", "oss"],
    CATEGORY_WORLD: ["meme", "controvers", "movement", "essay", "podcast", "viral", "internet culture", "narrative"],
}

CATEGORY_SIGNIFICANCE = {
    CATEGORY_BIG_TECH: 9.0,
    CATEGORY_MARKETS: 10.0,
    CATEGORY_CONSUMER: 7.0,
    CATEGORY_CREATOR: 7.0,
    CATEGORY_STARTUPS: 8.0,
    CATEGORY_SCIENCE: 8.0,
    CATEGORY_OPEN_SOURCE: 5.0,
    CATEGORY_WORLD: 6.0,
}

PRIMARY_SOURCE_PRIORITY = {
    "hn": 0,
    "web": 1,
    "reddit": 2,
    "youtube": 3,
    "bluesky": 4,
    "github": 5,
    "polymarket": 6,
    "x": 7,
}

# Quality sources get scoring bonuses
QUALITY_SOURCES = {"hn", "web", "reddit", "youtube"}

WORLD_RADAR_PRESET_ID = "world-radar-v1"
TELEGRAM_GLOBAL_LIMIT_DEFAULT = 10
OBSIDIAN_GLOBAL_LIMIT = 15
CATEGORY_SECTION_LIMIT = 10
GLOBAL_CATEGORY_CAP = 3
_DEFAULT_SOURCE_CAP = 3
_SOURCE_CAPS = {
    "hn": 5,
    "web": 5,
    "reddit": 5,
    "youtube": 4,
    "bluesky": 3,
    "github": 4,
    "polymarket": 2,
    "x": 2,
}

LAST30DAYS_ROOT = os.environ.get("LAST30DAYS_ROOT", "/opt/last30days-skill")
LAST30DAYS_SCRIPT = f"{LAST30DAYS_ROOT}/scripts/last30days.py"
LAST30DAYS_TIMEOUT_SECONDS = int(os.environ.get("LAST30DAYS_TIMEOUT_SECONDS", "420") or 420)
LAST30DAYS_LOOKBACK_DAYS = int(os.environ.get("LAST30DAYS_LOOKBACK_DAYS", "30") or 30)

_SOURCE_LABELS = {
    "grounding": "web",
    "hackernews": "hn",
}


def build_digest(config: dict, *, preset_id: str, now: datetime | None = None) -> Last30DaysDigest:
    now = now or datetime.now(timezone.utc)
    current = dict(config.get("last30days", {}) or {})
    topic_cfg = dict(current.get("telegram", {}) or {})
    query_bundle = [str(item).strip() for item in current.get("query_bundle", []) if str(item).strip()]
    if not query_bundle:
        query_bundle = list(DEFAULT_QUERY_BUNDLE)
    compact_limit = int(current.get("max_items", TELEGRAM_GLOBAL_LIMIT_DEFAULT) or TELEGRAM_GLOBAL_LIMIT_DEFAULT)
    global_limit = max(compact_limit, OBSIDIAN_GLOBAL_LIMIT)
    platform_sources = dict(current.get("platform_sources", {}) or {})

    digest = Last30DaysDigest(
        preset_id=preset_id or str(current.get("preset_id", WORLD_RADAR_PRESET_ID)),
        mode=str(current.get("mode", "compact")),
        generated_at=now.isoformat(),
        topic_name=str(topic_cfg.get("topic_name", "last30daysTrend")),
        topic_id=int(topic_cfg.get("topic_id", 0) or 0),
        query_bundle=query_bundle,
        total_queries=len(query_bundle),
        suggestions=_default_suggestions(),
    )

    aggregated_source_counts: dict[str, int] = defaultdict(int)
    aggregated_errors: dict[str, str] = {}
    merged_themes: dict[str, dict[str, Any]] = {}

    for query in query_bundle:
        result = _run_query_with_rescue(query, platform_sources=platform_sources)
        digest.reports.append(result)
        if result["status"] != "completed":
            digest.query_errors[query] = result.get("error", "last30days query failed")
            continue

        digest.successful_queries += 1
        for source, count in result.get("source_counts", {}).items():
            aggregated_source_counts[source] += int(count)
        aggregated_errors.update(result.get("errors_by_source", {}))

        for theme in result.get("themes", []):
            key = _theme_key(theme)
            existing = merged_themes.get(key)
            if not existing:
                merged_themes[key] = dict(theme)
                continue
            existing["score"] = max(float(existing.get("score", 0.0)), float(theme.get("score", 0.0)))
            existing["sources"] = sorted(set(existing.get("sources", [])) | set(theme.get("sources", [])))
            existing["queries"] = sorted(set(existing.get("queries", [])) | set(theme.get("queries", [])))
            existing["source_titles"] = _merged_titles(existing.get("source_titles", []), theme.get("source_titles", []))
            if len(theme.get("snippet", "")) > len(existing.get("snippet", "")):
                existing["snippet"] = theme.get("snippet", existing.get("snippet", ""))
            if not existing.get("url") and theme.get("url"):
                existing["url"] = theme["url"]

    digest.source_counts = dict(sorted(aggregated_source_counts.items(), key=lambda item: (-item[1], item[0])))
    digest.errors_by_source = dict(sorted(aggregated_errors.items()))
    ranked_themes = _prepare_world_themes(list(merged_themes.values()))
    global_theme_items = _select_diversified_global_themes(ranked_themes, limit=global_limit)
    compact_theme_items = global_theme_items[:compact_limit]

    digest.themes = [_theme_model(item) for item in compact_theme_items]
    digest.global_themes = [_theme_model(item) for item in global_theme_items]
    digest.category_sections = _category_sections(ranked_themes)

    if digest.successful_queries == 0:
        digest.status = "failed"
        digest.notes.append("All last30days subqueries failed.")
    elif digest.query_errors or digest.errors_by_source:
        digest.status = "partial"
        digest.notes.append("Completed with partial source/query failures.")
    else:
        digest.status = "ok"

    if not digest.global_themes:
        digest.notes.append("No ranked themes were produced by last30days.")
    elif len(digest.themes) < compact_limit:
        digest.notes.append("Global top was narrowed by source/category diversity caps.")

    return digest


def _run_query(query: str, *, platform_sources: dict[str, Any] | None = None) -> dict[str, Any]:
    platform_sources = platform_sources or {}
    cmd = [
        os.environ.get("LAST30DAYS_PYTHON", sys.executable),
        LAST30DAYS_SCRIPT,
        query,
        "--emit=json",
        "--quick",
        "--lookback-days",
        str(LAST30DAYS_LOOKBACK_DAYS),
    ]
    github_repos = _build_github_repos(query, platform_sources)
    if github_repos:
        cmd.extend(["--github-repo", ",".join(github_repos)])
    cmd.extend(_build_platform_args(platform_sources))
    if os.environ.get("LAST30DAYS_USE_MOCK", "").strip() == "1":
        cmd.append("--mock")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=LAST30DAYS_TIMEOUT_SECONDS,
            env=os.environ.copy(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"query": query, "status": "failed", "error": f"timeout after {LAST30DAYS_TIMEOUT_SECONDS}s"}

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return {"query": query, "status": "failed", "error": detail[:800] or f"exit code {proc.returncode}"}

    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        detail = (proc.stdout or proc.stderr or "").strip()
        return {"query": query, "status": "failed", "error": f"invalid json: {exc}: {detail[:500]}"}

    return {
        "query": query,
        "status": "completed",
        "source_counts": _source_counts(report),
        "errors_by_source": dict(report.get("errors_by_source") or {}),
        "themes": _extract_themes(report, query=query),
        "provider_runtime": dict(report.get("provider_runtime") or {}),
        "warnings": list(report.get("warnings") or []),
    }


def _run_query_with_rescue(query: str, *, platform_sources: dict[str, Any] | None = None) -> dict[str, Any]:
    primary = _run_query(query, platform_sources=platform_sources)
    if primary["status"] != "completed" or primary.get("themes") or not RESCUE_QUERY_BUNDLE.get(query):
        return primary

    rescue_reports: list[dict[str, Any]] = []
    for rescue_query in RESCUE_QUERY_BUNDLE.get(query, []):
        rescue = _run_query(rescue_query, platform_sources=platform_sources)
        rescue_reports.append(rescue)

    merged = _merge_reports(query, [primary, *rescue_reports])
    merged["rescue_queries"] = [item["query"] for item in rescue_reports]
    if any(item["status"] == "completed" and item.get("themes") for item in rescue_reports):
        merged.setdefault("warnings", []).append("Used narrower rescue queries after an empty composite result.")
    return merged


def _build_platform_args(platform_sources: dict[str, Any]) -> list[str]:
    """Build extra CLI args for per-platform source hints (excluding github, handled separately)."""
    args: list[str] = []
    if reddit := platform_sources.get("reddit", {}):
        if feeds := reddit.get("feeds", []):
            args += ["--reddit-sub", ",".join(feeds)]
    if hn := platform_sources.get("hn", {}):
        if feeds := hn.get("feeds", []):
            args += ["--hn-feed", ",".join(feeds)]
    if youtube := platform_sources.get("youtube", {}):
        if terms := youtube.get("search_terms", []):
            args += ["--youtube-search", ",".join(terms)]
    if bluesky := platform_sources.get("bluesky", {}):
        if packs := bluesky.get("starter_packs", []):
            args += ["--bluesky-pack", ",".join(packs)]
    return args


def _build_github_repos(query: str, platform_sources: dict[str, Any]) -> list[str]:
    """Merge query-specific GITHUB_REPO_HINTS with platform_sources.github.repos, deduped."""
    repos = list(GITHUB_REPO_HINTS.get(query, []))
    if github := platform_sources.get("github", {}):
        repos += list(github.get("repos", []))
        if github.get("trending"):
            repos.append("trending")
    seen: set[str] = set()
    return [r for r in repos if not (r in seen or seen.add(r))]  # type: ignore[func-returns-value]


def _merge_reports(query: str, reports: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [report for report in reports if report.get("status") == "completed"]
    if not completed:
        first_failure = next((report for report in reports if report.get("error")), {})
        return {
            "query": query,
            "status": "failed",
            "error": first_failure.get("error", "last30days query failed"),
        }

    source_counts: dict[str, int] = defaultdict(int)
    errors_by_source: dict[str, str] = {}
    warnings: list[str] = []
    provider_runtime: dict[str, Any] = {}
    merged_themes: dict[str, dict[str, Any]] = {}

    for report in completed:
        for source, count in (report.get("source_counts") or {}).items():
            source_counts[source] += int(count)
        errors_by_source.update(report.get("errors_by_source") or {})
        warnings.extend(str(item) for item in (report.get("warnings") or []) if str(item))
        if not provider_runtime and report.get("provider_runtime"):
            provider_runtime = dict(report["provider_runtime"])
        for theme in report.get("themes") or []:
            current = dict(theme)
            key = _theme_key(current)
            existing = merged_themes.get(key)
            if not existing:
                merged_themes[key] = current
                continue
            existing["score"] = max(float(existing.get("score", 0.0)), float(current.get("score", 0.0)))
            existing["sources"] = sorted(set(existing.get("sources", [])) | set(current.get("sources", [])))
            existing["queries"] = sorted(set(existing.get("queries", [])) | set(current.get("queries", [])))
            existing["source_titles"] = _merged_titles(existing.get("source_titles", []), current.get("source_titles", []))
            if len(current.get("snippet", "")) > len(existing.get("snippet", "")):
                existing["snippet"] = current.get("snippet", existing.get("snippet", ""))
            if not existing.get("url") and current.get("url"):
                existing["url"] = current["url"]

    merged_report = {
        "query": query,
        "status": "completed",
        "source_counts": dict(sorted(source_counts.items(), key=lambda item: (-item[1], item[0]))),
        "errors_by_source": dict(sorted(errors_by_source.items())),
        "themes": sorted(
            merged_themes.values(),
            key=lambda theme: (-float(theme.get("score", 0.0)), theme.get("title", "")),
        ),
        "provider_runtime": provider_runtime,
        "warnings": _dedupe_strings(warnings),
    }
    return merged_report


def _extract_themes(report: dict[str, Any], *, query: str) -> list[dict[str, Any]]:
    ranked = list(report.get("ranked_candidates") or [])
    candidate_by_id = {str(item.get("candidate_id")): item for item in ranked if item.get("candidate_id")}
    themes: list[dict[str, Any]] = []

    for cluster in list(report.get("clusters") or [])[:8]:
        candidate = _candidate_for_cluster(cluster, candidate_by_id, ranked)
        if not candidate:
            continue
        sources = candidate.get("sources") or cluster.get("sources") or [candidate.get("source", "web")]
        source_titles = _source_titles(candidate)
        themes.append(
            {
                "theme_id": str(cluster.get("cluster_id") or candidate.get("candidate_id") or _slug(candidate.get("title", "theme"))),
                "title": str(candidate.get("title") or cluster.get("title") or "Untitled theme"),
                "snippet": _compact_text(
                    candidate.get("snippet")
                    or candidate.get("explanation")
                    or _first_source_item(candidate, "snippet")
                    or _first_source_item(candidate, "body")
                    or ""
                ),
                "url": str(candidate.get("url") or _first_source_item(candidate, "url") or ""),
                "sources": [_SOURCE_LABELS.get(str(source), str(source)) for source in sources],
                "queries": [query],
                "score": float(candidate.get("final_score") or candidate.get("rerank_score") or cluster.get("score") or 0.0),
                "source_titles": source_titles,
            }
        )

    if themes:
        return themes

    for candidate in ranked[:8]:
        themes.append(
            {
                "theme_id": str(candidate.get("candidate_id") or _slug(candidate.get("title", "theme"))),
                "title": str(candidate.get("title") or "Untitled theme"),
                "snippet": _compact_text(candidate.get("snippet") or candidate.get("explanation") or ""),
                "url": str(candidate.get("url") or ""),
                "sources": [_SOURCE_LABELS.get(str(source), str(source)) for source in (candidate.get("sources") or [candidate.get("source", "web")])],
                "queries": [query],
                "score": float(candidate.get("final_score") or candidate.get("rerank_score") or 0.0),
                "source_titles": _source_titles(candidate),
            }
        )
    return themes


def _candidate_for_cluster(cluster: dict[str, Any], candidate_by_id: dict[str, dict[str, Any]], ranked: list[dict[str, Any]]) -> dict[str, Any] | None:
    representative_ids = list(cluster.get("representative_ids") or [])
    candidate_ids = list(cluster.get("candidate_ids") or [])
    for candidate_id in representative_ids + candidate_ids:
        current = candidate_by_id.get(str(candidate_id))
        if current:
            return current
    cluster_id = str(cluster.get("cluster_id", "")).strip()
    for candidate in ranked:
        if str(candidate.get("cluster_id", "")).strip() == cluster_id:
            return candidate
    return None


def _source_counts(report: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for source, items in (report.get("items_by_source") or {}).items():
        count = len(items or [])
        if count:
            result[_SOURCE_LABELS.get(str(source), str(source))] = count
    return result


def _source_titles(candidate: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    for item in candidate.get("source_items") or []:
        title = str(item.get("title") or "").strip()
        if title:
            titles.append(title)
    return _merged_titles([], titles)


def _merged_titles(existing: list[str], incoming: list[str], *, limit: int = 3) -> list[str]:
    merged: list[str] = []
    for title in [*existing, *incoming]:
        clean = str(title).strip()
        if clean and clean not in merged:
            merged.append(clean)
        if len(merged) >= limit:
            break
    return merged


def _first_source_item(candidate: dict[str, Any], key: str) -> str:
    for item in candidate.get("source_items") or []:
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _theme_key(theme: dict[str, Any]) -> str:
    url = str(theme.get("url") or "").strip().lower()
    if url:
        return url
    return _slug(str(theme.get("title", "theme")).lower())


def _compact_text(value: str, *, limit: int = 280) -> str:
    text = " ".join((value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "theme"


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        clean = str(item).strip()
        if clean and clean not in seen:
            seen.append(clean)
    return seen


def _prepare_world_themes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for raw_theme in items:
        current = dict(raw_theme)
        current["sources"] = _dedupe_strings(list(current.get("sources", [])))
        current["queries"] = _dedupe_strings(list(current.get("queries", [])))
        current["source_titles"] = _merged_titles([], list(current.get("source_titles", [])), limit=5)
        current["category"] = _theme_category(current)
        current["primary_source"] = _primary_source(current)
        current["global_score"] = _world_score(current)
        ranked.append(current)

    ranked.sort(
        key=lambda theme: (
            -float(theme.get("global_score", 0.0)),
            -float(theme.get("score", 0.0)),
            theme.get("title", ""),
        )
    )

    for category in CATEGORY_ORDER:
        category_items = [theme for theme in ranked if theme.get("category") == category]
        for rank, theme in enumerate(category_items, start=1):
            theme["category_rank"] = rank
    return ranked


def _select_diversified_global_themes(items: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    by_source: dict[str, int] = defaultdict(int)
    by_category: dict[str, int] = defaultdict(int)

    for current in items:
        source = str(current.get("primary_source") or "unknown")
        category = str(current.get("category") or CATEGORY_WORLD)
        source_cap = _SOURCE_CAPS.get(source, _DEFAULT_SOURCE_CAP)
        if by_source[source] >= source_cap:
            continue
        if by_category[category] >= GLOBAL_CATEGORY_CAP:
            continue
        chosen = dict(current)
        chosen["global_rank"] = len(selected) + 1
        selected.append(chosen)
        by_source[source] += 1
        by_category[category] += 1
        if len(selected) >= limit:
            break
    return selected


def _category_sections(items: list[dict[str, Any]]) -> list[Last30DaysCategorySection]:
    sections: list[Last30DaysCategorySection] = []
    for category in CATEGORY_ORDER:
        category_items = [item for item in items if item.get("category") == category][:CATEGORY_SECTION_LIMIT]
        if not category_items:
            continue
        sections.append(
            Last30DaysCategorySection(
                category=category,
                themes=[_theme_model(item) for item in category_items],
            )
        )
    return sections


def _theme_model(item: dict[str, Any]) -> Last30DaysTheme:
    return Last30DaysTheme(
        theme_id=str(item.get("theme_id", _slug(item.get("title", "theme")))),
        title=str(item.get("title", "Untitled theme")),
        snippet=str(item.get("snippet", "")).strip(),
        url=str(item.get("url", "")).strip(),
        sources=list(item.get("sources", [])),
        queries=list(item.get("queries", [])),
        score=float(item.get("score", 0.0)),
        source_titles=list(item.get("source_titles", [])),
        category=str(item.get("category", "")),
        primary_source=str(item.get("primary_source", "")),
        global_score=float(item.get("global_score", 0.0)),
        global_rank=int(item.get("global_rank", 0) or 0),
        category_rank=int(item.get("category_rank", 0) or 0),
    )


def _theme_category(theme: dict[str, Any]) -> str:
    category_scores: dict[str, float] = defaultdict(float)
    for query in theme.get("queries") or []:
        hinted = QUERY_CATEGORY_MAP.get(str(query).strip())
        if hinted:
            category_scores[hinted] += 5.0

    haystack = " ".join(
        [
            str(theme.get("title") or ""),
            str(theme.get("snippet") or ""),
            " ".join(str(item) for item in theme.get("source_titles") or []),
        ]
    ).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in haystack:
                category_scores[category] += 1.0

    if "github" in (theme.get("sources") or []):
        category_scores[CATEGORY_OPEN_SOURCE] += 2.0

    if not category_scores:
        return CATEGORY_WORLD
    return sorted(
        category_scores.items(),
        key=lambda item: (-item[1], CATEGORY_ORDER.index(item[0])),
    )[0][0]


def _primary_source(theme: dict[str, Any]) -> str:
    sources = [str(source) for source in (theme.get("sources") or []) if str(source)]
    if not sources:
        return "unknown"
    return sorted(sources, key=lambda source: (PRIMARY_SOURCE_PRIORITY.get(source, 99), source))[0]


def _world_score(theme: dict[str, Any]) -> float:
    base_score = float(theme.get("score", 0.0))
    source_bonus = min(len(theme.get("sources") or []), 3) * 6.0
    query_bonus = min(len(theme.get("queries") or []), 3) * 3.0
    significance = CATEGORY_SIGNIFICANCE.get(str(theme.get("category") or CATEGORY_WORLD), 5.0)
    penalty = _context_penalty(theme)
    if "github" in (theme.get("sources") or []) and theme.get("category") != CATEGORY_OPEN_SOURCE:
        penalty += 8.0
    primary = str(theme.get("primary_source") or "")
    quality_bonus = 5.0 if primary in QUALITY_SOURCES else 0.0
    sources = list(theme.get("sources") or [])
    multi_quality_bonus = 3.0 if sum(1 for s in sources if s in QUALITY_SOURCES) >= 2 else 0.0
    return base_score + source_bonus + query_bonus + significance + quality_bonus + multi_quality_bonus - penalty


def _context_penalty(theme: dict[str, Any]) -> float:
    penalty = 0.0
    title = str(theme.get("title") or "").strip()
    lower_title = title.lower()
    url = str(theme.get("url") or "").strip().lower()
    sources = list(theme.get("sources") or [])
    source_titles = list(theme.get("source_titles") or [])
    snippet = str(theme.get("snippet") or "").strip()

    if not url:
        penalty += 10.0
    if title.startswith("@") or title.startswith(">") or lower_title.startswith("rt "):
        penalty += 15.0
    if "x.com/" in url and not source_titles:
        penalty += 12.0
    if sources == ["x"] and not source_titles:
        penalty += 12.0
    if set(sources) <= {"x", "reddit"} and not (set(sources) & QUALITY_SOURCES - {"reddit"}):
        # Only X/Reddit, no web/HN/YouTube
        if not any(s in QUALITY_SOURCES for s in sources if s != "reddit"):
            penalty += 10.0
    if len(snippet) < 40:
        penalty += 6.0
    return penalty


def _default_suggestions() -> list[str]:
    return [
        "Big Tech launches",
        "Markets and regulation",
        "Consumer platform shifts",
        "Creator economy",
        "Open source builders",
        "Internet culture",
    ]
