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

from models import Last30DaysDigest, Last30DaysTheme


DEFAULT_QUERY_BUNDLE = [
    "OpenAI Codex Claude Code Gemini CLI Cursor Windsurf",
    "OpenClaw MCP servers agent tooling open source AI tools",
    "AI coding agents context engineering prompt engineering",
    "Veo 3 Seedance 2.0 Nano Banana Pro paper.design creator workflows",
]

RESCUE_QUERY_BUNDLE = {
    "OpenAI Codex Claude Code Gemini CLI Cursor Windsurf": [
        "OpenAI Codex",
        "Claude Code",
        "Gemini CLI",
        "Cursor",
        "Windsurf",
    ],
    "OpenClaw MCP servers agent tooling open source AI tools": [
        "OpenClaw",
        "MCP servers",
        "agent tooling",
        "open source AI tools",
    ],
    "AI coding agents context engineering prompt engineering": [
        "AI coding agents",
        "context engineering",
        "prompt engineering coding agents",
    ],
    "Veo 3 Seedance 2.0 Nano Banana Pro paper.design creator workflows": [
        "Veo 3",
        "Seedance 2.0",
        "Nano Banana Pro",
        "paper.design prompts",
    ],
}

GITHUB_REPO_HINTS = {
    "OpenAI Codex Claude Code Gemini CLI Cursor Windsurf": [
        "openai/codex",
        "google-gemini/gemini-cli",
    ],
    "OpenClaw MCP servers agent tooling open source AI tools": [
        "openclaw/openclaw",
        "modelcontextprotocol/servers",
        "openziti/mcp-gateway",
        "isteamhq/mcp-servers",
    ],
    "OpenAI Codex": [
        "openai/codex",
    ],
    "Gemini CLI": [
        "google-gemini/gemini-cli",
    ],
    "OpenClaw": [
        "openclaw/openclaw",
    ],
    "MCP servers": [
        "modelcontextprotocol/servers",
        "openziti/mcp-gateway",
        "isteamhq/mcp-servers",
    ],
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

    digest = Last30DaysDigest(
        preset_id=preset_id or str(current.get("preset_id", "broad-discovery-v1")),
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
        result = _run_query_with_rescue(query)
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
    digest.themes = [
        Last30DaysTheme(
            theme_id=str(item.get("theme_id", _slug(item.get("title", "theme")))),
            title=str(item.get("title", "Untitled theme")),
            snippet=str(item.get("snippet", "")).strip(),
            url=str(item.get("url", "")).strip(),
            sources=list(item.get("sources", [])),
            queries=list(item.get("queries", [])),
            score=float(item.get("score", 0.0)),
            source_titles=list(item.get("source_titles", [])),
        )
        for item in sorted(
            merged_themes.values(),
            key=lambda theme: (-float(theme.get("score", 0.0)), theme.get("title", "")),
        )[: int(current.get("max_items", 7) or 7)]
    ]

    if digest.successful_queries == 0:
        digest.status = "failed"
        digest.notes.append("All last30days subqueries failed.")
    elif digest.query_errors or digest.errors_by_source:
        digest.status = "partial"
        digest.notes.append("Completed with partial source/query failures.")
    else:
        digest.status = "ok"

    if not digest.themes:
        digest.notes.append("No ranked themes were produced by last30days.")

    return digest


def _run_query(query: str) -> dict[str, Any]:
    cmd = [
        os.environ.get("LAST30DAYS_PYTHON", sys.executable),
        LAST30DAYS_SCRIPT,
        query,
        "--emit=json",
        "--quick",
        "--lookback-days",
        str(LAST30DAYS_LOOKBACK_DAYS),
    ]
    github_repos = list(GITHUB_REPO_HINTS.get(query, []))
    if github_repos:
        cmd.extend(["--github-repo", ",".join(github_repos)])
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


def _run_query_with_rescue(query: str) -> dict[str, Any]:
    primary = _run_query(query)
    if primary["status"] != "completed" or primary.get("themes") or not RESCUE_QUERY_BUNDLE.get(query):
        return primary

    rescue_reports: list[dict[str, Any]] = []
    for rescue_query in RESCUE_QUERY_BUNDLE.get(query, []):
        rescue = _run_query(rescue_query)
        rescue_reports.append(rescue)

    merged = _merge_reports(query, [primary, *rescue_reports])
    merged["rescue_queries"] = [item["query"] for item in rescue_reports]
    if any(item["status"] == "completed" and item.get("themes") for item in rescue_reports):
        merged.setdefault("warnings", []).append("Used narrower rescue queries after an empty composite result.")
    return merged


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


def _default_suggestions() -> list[str]:
    return [
        "OpenAI Codex",
        "OpenClaw",
        "MCP servers",
        "AI coding agents",
        "Veo 3",
        "Nano Banana Pro",
    ]
