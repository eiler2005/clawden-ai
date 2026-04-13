"""
Persist last30days digests to state storage and Obsidian.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from models import Last30DaysDigest


STATE_ROOT = Path("/app/state/last30days")
OBSIDIAN_ROOT = Path("/app/obsidian")


def persist_last30days_digest(digest: Last30DaysDigest, *, config: dict) -> dict[str, str]:
    current = dict(config.get("last30days", {}) or {})
    obsidian_cfg = dict(current.get("obsidian", {}) or {})
    root_name = str(obsidian_cfg.get("root", "Last30Days"))
    tz = ZoneInfo(str(current.get("timezone") or config.get("timezone") or "Europe/Moscow"))
    generated_at = datetime.fromisoformat(digest.generated_at)
    local_dt = generated_at.astimezone(tz)
    date_slug = local_dt.strftime("%Y-%m-%d")
    slot_slug = _slot_slug(current, local_dt)

    state_dir = STATE_ROOT / date_slug
    state_dir.mkdir(parents=True, exist_ok=True)
    derived_json_path = state_dir / f"{slot_slug}-{digest.mode}.json"
    derived_json_path.write_text(
        json.dumps(digest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    obsidian_base = OBSIDIAN_ROOT / root_name
    derived_obsidian_dir = obsidian_base / "Derived" / date_slug
    derived_obsidian_dir.mkdir(parents=True, exist_ok=True)
    derived_obsidian_path = derived_obsidian_dir / f"{slot_slug}-{digest.mode}.json"
    derived_obsidian_path.write_text(
        json.dumps(digest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    expanded_dir = obsidian_base / "Expanded"
    expanded_dir.mkdir(parents=True, exist_ok=True)
    expanded_path = expanded_dir / f"{date_slug}-{digest.topic_name}.md"
    expanded_path.write_text(_render_expanded_markdown(digest, local_dt), encoding="utf-8")

    return {
        "state_json": str(derived_json_path),
        "obsidian_derived_json": str(derived_obsidian_path),
        "obsidian_expanded_md": str(expanded_path),
    }


def _slot_slug(config: dict, generated_local: datetime) -> str:
    expr = str(config.get("schedule_expr", "")).strip()
    parts = expr.split()
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{int(parts[1]):02d}{int(parts[0]):02d}"
    return generated_local.strftime("%H%M")


def _render_expanded_markdown(digest: Last30DaysDigest, generated_local: datetime) -> str:
    source_summary = ", ".join(f"{source}: {count}" for source, count in digest.source_counts.items()) or "none"
    frontmatter = [
        "---",
        f"title: {digest.topic_name} {generated_local.strftime('%Y-%m-%d')}",
        "type: last30days-expanded-note",
        f"preset_id: {digest.preset_id}",
        f"mode: {digest.mode}",
        f"generated_at: {digest.generated_at}",
        f"status: {digest.status}",
        f"successful_queries: {digest.successful_queries}",
        f"total_queries: {digest.total_queries}",
        f"global_theme_count: {len(digest.global_themes)}",
        f"category_count: {len(digest.category_sections)}",
        f"source_summary: {source_summary}",
        "---",
        "",
    ]

    lines = [f"# {digest.topic_name} — {generated_local.strftime('%Y-%m-%d')}", ""]
    lines.append("## Executive Summary")
    if digest.global_themes:
        lines.append(
            f"Captured {len(digest.global_themes)} global themes across {len(digest.category_sections)} active categories from {digest.successful_queries}/{digest.total_queries} world-radar runs."
        )
    else:
        lines.append("No ranked themes were captured in this run.")
    if digest.notes:
        lines.append(" ".join(digest.notes))
    lines.append("")

    lines.append("## Global Top Themes")
    if digest.global_themes:
        for idx, theme in enumerate(digest.global_themes, start=1):
            lines.append(f"{idx}. **{theme.title}**")
            if theme.snippet:
                lines.append(theme.snippet)
            meta = []
            if theme.category:
                meta.append("category: " + theme.category)
            if theme.sources:
                meta.append("sources: " + ", ".join(theme.sources))
            if theme.queries:
                meta.append("queries: " + " | ".join(theme.queries))
            if theme.global_rank:
                meta.append(f"global_rank: {theme.global_rank}")
            if meta:
                lines.append("; ".join(meta))
            if theme.url:
                lines.append(theme.url)
            if theme.source_titles:
                lines.append("notable refs: " + " | ".join(theme.source_titles))
            lines.append("")
    else:
        lines.append("1. No themes yet.")
        lines.append("")

    lines.append("## Category Sections")
    if digest.category_sections:
        for section in digest.category_sections:
            lines.append(f"### {section.category}")
            for theme in section.themes[:10]:
                rank_prefix = f"{theme.category_rank}. " if theme.category_rank else "- "
                lines.append(f"{rank_prefix}**{theme.title}**")
                if theme.snippet:
                    lines.append(theme.snippet)
                meta = []
                if theme.primary_source:
                    meta.append("primary_source: " + theme.primary_source)
                if theme.sources:
                    meta.append("sources: " + ", ".join(theme.sources))
                if theme.url:
                    meta.append(theme.url)
                if meta:
                    lines.append(" | ".join(meta))
                lines.append("")
    else:
        lines.append("- none")
        lines.append("")

    lines.append("## Source Coverage")
    if digest.source_counts:
        for source, count in digest.source_counts.items():
            lines.append(f"- {source}: {count}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Missing Sources And Errors")
    if digest.errors_by_source or digest.query_errors:
        for source, error in digest.errors_by_source.items():
            lines.append(f"- source `{source}`: {error}")
        for query, error in digest.query_errors.items():
            lines.append(f"- query `{query}`: {error}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Suggested Future Watchlist Candidates")
    if digest.suggestions:
        for item in digest.suggestions:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")

    return "\n".join(frontmatter + lines).strip() + "\n"
