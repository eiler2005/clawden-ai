from __future__ import annotations

import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from docx import Document
from markdownify import markdownify
from pypdf import PdfReader


QUEUE_START = "<!-- wiki-import-queue:start -->"
QUEUE_END = "<!-- wiki-import-queue:end -->"
SYSTEM_FILES = {
    "SCHEMA.md",
    "INDEX.md",
    "OVERVIEW.md",
    "IMPORT-QUEUE.md",
    "LOG.md",
    "TOPICS.md",
    "CANONICALS.yaml",
}
PAGE_FOLDERS = {
    "concept": "concepts",
    "entity": "entities",
    "decision": "decisions",
    "session": "sessions",
    "research": "research",
}
THEME_ORDER = [
    "runtime",
    "memory",
    "wiki",
    "retrieval",
    "signals",
    "routing",
    "sync",
    "security",
    "operations",
]
THEME_LABELS = {
    "runtime": "Runtime",
    "memory": "Memory",
    "wiki": "Wiki",
    "retrieval": "Retrieval",
    "signals": "Signals",
    "routing": "Routing",
    "sync": "Sync",
    "security": "Security",
    "operations": "Operations",
}
THEME_KEYWORDS = {
    "runtime": ["openclaw", "runtime", "gateway", "agent", "service", "docker compose"],
    "memory": ["memory", "recall", "cold start", "context", "daily note", "long-term"],
    "wiki": ["wiki", "obsidian", "knowledge base", "markdown", "curated import", "llm-wiki"],
    "retrieval": ["lightrag", "retrieval", "rag", "knowledge graph", "graph", "hybrid query", "vector"],
    "signals": ["signal", "telegram", "digest", "last30days", "radar", "theme"],
    "routing": ["routing", "router", "omniroute", "model routing", "provider"],
    "sync": ["syncthing", "sync", "vault", "bidirectional", "replication"],
    "security": ["security", "auth", "token", "allowlist", "boundary", "access"],
    "operations": ["deploy", "operations", "setup", "health", "cron", "runbook", "maintenance"],
}
CANONICAL_CONCEPTS = {
    "knowledge graph": {
        "slug": "knowledge-graph",
        "name": "Knowledge Graph",
        "aliases": ["knowledge graph", "graph retrieval"],
        "tags": ["graph", "retrieval"],
        "themes": ["retrieval", "memory"],
    },
    "three tier memory": {
        "slug": "three-tier-memory",
        "name": "Three-Tier Memory",
        "aliases": ["three tier memory", "three-tier memory"],
        "tags": ["memory"],
        "themes": ["memory", "wiki"],
    },
    "signal routing": {
        "slug": "signal-routing",
        "name": "Signal Routing",
        "aliases": ["signal routing"],
        "tags": ["signals", "routing"],
        "themes": ["signals", "routing"],
    },
    "curated import": {
        "slug": "curated-import",
        "name": "Curated Import",
        "aliases": ["curated import", "wiki import"],
        "tags": ["wiki", "import"],
        "themes": ["wiki", "operations"],
    },
    "hybrid retrieval": {
        "slug": "hybrid-retrieval",
        "name": "Hybrid Retrieval",
        "aliases": ["hybrid retrieval"],
        "tags": ["retrieval"],
        "themes": ["retrieval", "memory"],
    },
}
STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "and",
    "because",
    "been",
    "being",
    "between",
    "from",
    "into",
    "just",
    "more",
    "most",
    "over",
    "such",
    "than",
    "that",
    "their",
    "them",
    "they",
    "this",
    "those",
    "through",
    "using",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
}
TEXT_EXTENSIONS = {".md", ".txt", ".text", ".json", ".yaml", ".yml", ".html", ".htm"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".rtf"}
DOCUMENT_ARTIFACT_PATTERNS = {
    "readme",
    "setup",
    "operations",
    "architecture",
    "security",
    "design",
    "overview",
    "guide",
    "notes",
    "manual",
    "repository",
    "article",
    "memory architecture",
    "setup and operations",
    "architecture and security",
    "rollout design",
}
GENERIC_ENTITY_SLUGS = {
    "bridge",
    "browser",
    "please",
    "public",
    "operations",
    "overview",
    "overview-for",
    "security",
    "memory-architecture",
    "repository",
    "readme",
    "article",
    "setup",
    "there",
    "this",
    "github-com",
    "telegra-ph",
}
GENERIC_HOST_LABELS = {"example.com", "github.com", "telegra.ph", "www.github.com", "www.telegra.ph"}
DEFAULT_CANONICALS = [
    {
        "slug": "openclaw",
        "type": "entity",
        "subtype": "service",
        "name": "OpenClaw",
        "aliases": ["OpenClaw runtime", "OpenClaw gateway", "openclaw"],
        "tags": ["openclaw", "runtime", "agents"],
        "themes": ["runtime", "operations", "wiki"],
        "preferred_folder": "entities",
    },
    {
        "slug": "lightrag",
        "type": "entity",
        "subtype": "service",
        "name": "LightRAG",
        "aliases": ["LightRAG", "light rag", "graph retrieval"],
        "tags": ["lightrag", "retrieval", "graph"],
        "themes": ["retrieval", "memory", "operations"],
        "preferred_folder": "entities",
    },
    {
        "slug": "obsidian",
        "type": "entity",
        "subtype": "tool",
        "name": "Obsidian",
        "aliases": ["Obsidian Vault", "obsidian vault", "obsidian"],
        "tags": ["obsidian", "wiki"],
        "themes": ["wiki", "memory", "sync"],
        "preferred_folder": "entities",
    },
    {
        "slug": "syncthing",
        "type": "entity",
        "subtype": "service",
        "name": "Syncthing",
        "aliases": ["syncthing", "bidirectional sync"],
        "tags": ["syncthing", "sync"],
        "themes": ["sync", "operations"],
        "preferred_folder": "entities",
    },
    {
        "slug": "signals-bridge",
        "type": "entity",
        "subtype": "service",
        "name": "Signals Bridge",
        "aliases": ["signals bridge", "signals-bridge", "signal bridge"],
        "tags": ["signals", "bridge"],
        "themes": ["signals", "operations", "routing"],
        "preferred_folder": "entities",
    },
    {
        "slug": "last30days",
        "type": "entity",
        "subtype": "service",
        "name": "Last30Days",
        "aliases": ["last30days", "last 30 days", "world radar"],
        "tags": ["signals", "digest", "last30days"],
        "themes": ["signals", "operations"],
        "preferred_folder": "entities",
    },
    {
        "slug": "omniroute",
        "type": "entity",
        "subtype": "service",
        "name": "OmniRoute",
        "aliases": ["omniroute", "model routing"],
        "tags": ["routing", "omniroute"],
        "themes": ["routing", "operations", "runtime"],
        "preferred_folder": "entities",
    },
    {
        "slug": "benka",
        "type": "entity",
        "subtype": "person",
        "name": "Benka",
        "aliases": ["Бенька", "Benka"],
        "tags": ["agent", "benka"],
        "themes": ["runtime", "wiki"],
        "preferred_folder": "entities",
    },
    {
        "slug": "llm-wiki",
        "type": "concept",
        "subtype": "pattern",
        "name": "LLM-Wiki",
        "aliases": ["LLM Wiki", "llm wiki", "LLM-Wiki"],
        "tags": ["wiki", "llm", "knowledge-base"],
        "themes": ["wiki", "memory"],
        "preferred_folder": "concepts",
    },
]


@dataclass
class ImportRequest:
    source_type: str
    source: str
    target_kind: str = "auto"
    title: str = ""
    import_goal: str = ""


@dataclass
class NormalizedSource:
    fingerprint: str
    source_type: str
    source: str
    target_kind: str
    title: str
    raw_path: str
    mime_type: str
    markdown: str
    summary: str
    host: str = ""
    import_goal: str = ""


@dataclass
class PageSpec:
    slug: str
    name: str
    page_type: str
    subtype: str = ""
    aliases: list[str] | None = None
    tags: list[str] | None = None
    themes: list[str] | None = None
    related: list[str] | None = None
    confidence: str = "INFERRED"


class WikiImporter:
    def __init__(self, *, obsidian_root: Path, host_opt_root: Path | None = None, state_root: Path | None = None) -> None:
        self.obsidian_root = Path(obsidian_root)
        self.host_opt_root = Path(host_opt_root) if host_opt_root else Path("/host-opt")
        self.state_root = Path(state_root or "/app/state")
        self.wiki_root = self.obsidian_root / "wiki"
        self.raw_root = self.obsidian_root / "raw"

    def import_source(self, request: ImportRequest) -> dict[str, Any]:
        self._ensure_layout()
        normalized = self._normalize_source(request)
        queue = self._load_queue()
        entry = self._upsert_queue_entry(
            queue,
            normalized.fingerprint,
            {
                "status": "processing",
                "source_type": normalized.source_type,
                "target_kind": normalized.target_kind,
                "title": normalized.title,
                "source": normalized.source,
                "raw_path": normalized.raw_path,
                "updated": _utc_now(),
                "error": "",
            },
        )
        self._save_queue(queue)

        result: dict[str, Any] = {}
        try:
            page_paths = self._materialize_wiki(normalized)
            self._refresh_indexes_and_topics()
            self._append_log(
                operation="ingest",
                source=normalized.source,
                description=normalized.title,
                created=[path for path in page_paths if path.exists()],
                updated=[self.wiki_root / "INDEX.md", self.wiki_root / "OVERVIEW.md", self.wiki_root / "TOPICS.md"],
                insight=f"Imported {normalized.target_kind} source into canonical wiki pages and topic maps.",
            )
            entry["status"] = "done"
            entry["research_path"] = str(
                next((path.relative_to(self.obsidian_root) for path in page_paths if path.parent.name == "research"), "")
            )
            entry["updated"] = _utc_now()
            entry["error"] = ""
            self._save_queue(queue)
            result = {
                "ok": True,
                "fingerprint": normalized.fingerprint,
                "raw_path": normalized.raw_path,
                "page_paths": [str(path.relative_to(self.obsidian_root)) for path in page_paths],
                "queue_status": entry["status"],
            }
        except Exception as exc:
            entry["status"] = "failed"
            entry["updated"] = _utc_now()
            entry["error"] = f"{exc.__class__.__name__}: {exc}"
            self._save_queue(queue)
            raise
        self._write_status({"ok": True, "last_import": result, "updated": _utc_now()})
        return result

    def lint(self, *, repair: bool = False) -> dict[str, Any]:
        self._ensure_layout()
        repair_actions: list[str] = []
        if repair:
            repair_actions = self._repair_existing_wiki()
        pages = self._scan_pages()
        canonicals = self._load_canonicals()
        incoming = self._incoming_link_counts(pages)
        now = datetime.now(timezone.utc).date()

        stale: list[str] = []
        empty_sections: list[str] = []
        missing_links: list[str] = []
        hub_candidates: list[str] = []
        findings: list[str] = []
        duplicate_basenames = self._duplicate_basename_findings(pages)
        duplicate_token_slugs = self._duplicate_token_slug_findings(pages)
        source_title_entities = self._source_title_entity_findings(pages)
        alias_collisions = self._alias_collision_findings(pages)
        missing_themes = self._missing_theme_findings(pages)
        broken_canonicals = self._broken_canonical_findings(canonicals)
        topics_drift = self._topics_drift(pages)

        for page in pages:
            updated = str(page["meta"].get("updated", "")).strip()
            if updated:
                try:
                    age = (now - datetime.strptime(updated, "%Y-%m-%d").date()).days
                    if age > 90:
                        stale.append(f"{page['rel_path']} ({age} days)")
                except ValueError:
                    findings.append(f"- Invalid updated date: `{page['rel_path']}`")
            else:
                findings.append(f"- Missing updated date: `{page['rel_path']}`")

            for header in _empty_markdown_sections(page["body"]):
                empty_sections.append(f"{page['rel_path']} -> {header}")

            missing_links.extend(self._missing_link_findings(page, pages))
            if incoming.get(page["slug"], 0) >= 5 and not bool(page["meta"].get("hub")):
                hub_candidates.append(f"{page['rel_path']} ({incoming[page['slug']]} links)")

        report_lines = ["# Wiki Lint Report", ""]
        report_lines.append(f"- scanned_pages: {len(pages)}")
        report_lines.append(f"- repair: {str(repair).lower()}")
        if repair_actions:
            report_lines.append(f"- repair_actions: {len(repair_actions)}")
        report_lines.append("")
        report_lines.append("## Duplicate Basenames")
        report_lines.extend([f"- {item}" for item in duplicate_basenames] or ["- none"])
        report_lines.append("")
        report_lines.append("## Duplicate-Token Slugs")
        report_lines.extend([f"- {item}" for item in duplicate_token_slugs] or ["- none"])
        report_lines.append("")
        report_lines.append("## Source-Title-as-Entity")
        report_lines.extend([f"- {item}" for item in source_title_entities] or ["- none"])
        report_lines.append("")
        report_lines.append("## Alias Collisions")
        report_lines.extend([f"- {item}" for item in alias_collisions] or ["- none"])
        report_lines.append("")
        report_lines.append("## Missing Themes")
        report_lines.extend([f"- {item}" for item in missing_themes] or ["- none"])
        report_lines.append("")
        report_lines.append("## Broken Canonical References")
        report_lines.extend([f"- {item}" for item in broken_canonicals] or ["- none"])
        report_lines.append("")
        report_lines.append("## TOPICS Drift")
        report_lines.extend([f"- {item}" for item in topics_drift] or ["- none"])
        report_lines.append("")
        report_lines.append("## Stale Pages")
        report_lines.extend([f"- {item}" for item in stale] or ["- none"])
        report_lines.append("")
        report_lines.append("## Empty Sections")
        report_lines.extend([f"- {item}" for item in empty_sections] or ["- none"])
        report_lines.append("")
        report_lines.append("## Missing Links")
        report_lines.extend([f"- {item}" for item in missing_links[:20]] or ["- none"])
        report_lines.append("")
        report_lines.append("## Hub Candidates")
        report_lines.extend([f"- {item}" for item in hub_candidates] or ["- none"])
        report_lines.append("")
        report_lines.append("## Contradictions")
        report_lines.append("- heuristic contradiction detection not implemented in v1.2")
        if repair_actions:
            report_lines.append("")
            report_lines.append("## Repair Actions")
            report_lines.extend([f"- {item}" for item in repair_actions])
        report = "\n".join(report_lines).strip() + "\n"
        payload = {
            "ok": True,
            "report": report,
            "stale_count": len(stale),
            "empty_section_count": len(empty_sections),
            "missing_link_count": len(missing_links),
            "hub_candidate_count": len(hub_candidates),
            "duplicate_basename_count": len(duplicate_basenames),
            "duplicate_token_slug_count": len(duplicate_token_slugs),
            "source_title_entity_count": len(source_title_entities),
            "alias_collision_count": len(alias_collisions),
            "missing_theme_count": len(missing_themes),
            "broken_canonical_count": len(broken_canonicals),
            "topics_drift_count": len(topics_drift),
            "repair_actions": repair_actions,
        }
        self._write_status({"ok": True, "last_lint": payload, "updated": _utc_now()})
        return payload

    def status(self) -> dict[str, Any]:
        queue = self._load_queue()
        counts: dict[str, int] = {}
        for item in queue:
            counts[item.get("status", "unknown")] = counts.get(item.get("status", "unknown"), 0) + 1
        status_path = self.state_root / "wiki-import-status.json"
        payload = {
            "ok": True,
            "queue_counts": counts,
            "queue_size": len(queue),
            "wiki_root": str(self.wiki_root),
            "raw_root": str(self.raw_root),
            "canonical_file": str(self.wiki_root / "CANONICALS.yaml"),
            "topics_file": str(self.wiki_root / "TOPICS.md"),
        }
        if status_path.exists():
            try:
                payload["last_status"] = json.loads(status_path.read_text(encoding="utf-8"))
            except Exception:
                payload["last_status"] = {"ok": False, "error": "status_file_unreadable"}
        return payload

    def _normalize_source(self, request: ImportRequest) -> NormalizedSource:
        source_type = request.source_type.strip().lower()
        if source_type not in {"url", "text", "server_path"}:
            raise ValueError(f"unsupported source_type: {request.source_type}")
        if source_type == "url":
            return self._normalize_url(request)
        if source_type == "text":
            return self._normalize_text(request)
        return self._normalize_server_path(request)

    def _normalize_url(self, request: ImportRequest) -> NormalizedSource:
        response = requests.get(
            request.source,
            timeout=30,
            headers={"User-Agent": "wiki-import/1.0 (+https://openclaw.local)"},
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        host = urlparse(request.source).netloc.lower()
        title = request.title.strip()
        if content_type == "application/pdf" or request.source.lower().endswith(".pdf"):
            markdown = _pdf_to_markdown(response.content)
            target_kind = _resolve_target_kind(request.target_kind, "document")
            title = title or _title_from_url(request.source) or "Imported PDF"
            mime_type = "application/pdf"
        elif request.source.lower().endswith(".docx"):
            markdown = _docx_to_markdown(response.content)
            target_kind = _resolve_target_kind(request.target_kind, "document")
            title = title or _title_from_url(request.source) or "Imported DOCX"
            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            html = response.text
            markdown = _html_to_markdown(html)
            title = title or _extract_html_title(html) or _title_from_url(request.source) or "Imported URL"
            target_kind = _resolve_target_kind(request.target_kind, "article")
            mime_type = content_type or "text/html"
        fingerprint = _fingerprint(request.source.encode("utf-8") + b"\n" + markdown.encode("utf-8"))
        raw_path = self._raw_path(target_kind, title, fingerprint)
        if not (self.obsidian_root / raw_path).exists():
            rendered = _render_raw_markdown(
                title=title,
                source_type="url",
                source=request.source,
                target_kind=target_kind,
                fingerprint=fingerprint,
                mime_type=mime_type,
                body_markdown=markdown,
            )
            (self.obsidian_root / raw_path).parent.mkdir(parents=True, exist_ok=True)
            (self.obsidian_root / raw_path).write_text(rendered, encoding="utf-8")
        return NormalizedSource(
            fingerprint=fingerprint,
            source_type="url",
            source=request.source,
            target_kind=target_kind,
            title=title,
            raw_path=str(raw_path),
            mime_type=mime_type,
            markdown=markdown,
            summary=_summary_from_markdown(markdown),
            host=host,
            import_goal=request.import_goal.strip(),
        )

    def _normalize_text(self, request: ImportRequest) -> NormalizedSource:
        title = request.title.strip() or _title_from_text(request.source)
        markdown = request.source.strip()
        target_kind = _resolve_target_kind(request.target_kind, "article")
        fingerprint = _fingerprint(markdown.encode("utf-8"))
        raw_path = self._raw_path(target_kind, title, fingerprint)
        if not (self.obsidian_root / raw_path).exists():
            rendered = _render_raw_markdown(
                title=title,
                source_type="text",
                source="manual",
                target_kind=target_kind,
                fingerprint=fingerprint,
                mime_type="text/markdown",
                body_markdown=markdown,
            )
            (self.obsidian_root / raw_path).parent.mkdir(parents=True, exist_ok=True)
            (self.obsidian_root / raw_path).write_text(rendered, encoding="utf-8")
        return NormalizedSource(
            fingerprint=fingerprint,
            source_type="text",
            source="manual",
            target_kind=target_kind,
            title=title,
            raw_path=str(raw_path),
            mime_type="text/markdown",
            markdown=markdown,
            summary=_summary_from_markdown(markdown),
            import_goal=request.import_goal.strip(),
        )

    def _normalize_server_path(self, request: ImportRequest) -> NormalizedSource:
        host_path = Path(request.source)
        readable_path = self._resolve_host_path(host_path)
        if not readable_path.exists():
            raise FileNotFoundError(f"server path is not accessible: {request.source}")

        suffix = readable_path.suffix.lower()
        title = request.title.strip() or readable_path.stem.replace("_", " ").replace("-", " ")
        mime_type = "text/plain"
        if suffix == ".pdf":
            markdown = _pdf_to_markdown(readable_path.read_bytes())
            target_kind = _resolve_target_kind(request.target_kind, "document")
            mime_type = "application/pdf"
        elif suffix == ".docx":
            markdown = _docx_to_markdown(readable_path.read_bytes())
            target_kind = _resolve_target_kind(request.target_kind, "document")
            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif suffix in {".html", ".htm"}:
            markdown = _html_to_markdown(readable_path.read_text(encoding="utf-8", errors="ignore"))
            target_kind = _resolve_target_kind(request.target_kind, "article")
            mime_type = "text/html"
        elif suffix in TEXT_EXTENSIONS:
            markdown = readable_path.read_text(encoding="utf-8", errors="ignore")
            target_kind = _resolve_target_kind(request.target_kind, "document" if suffix == ".json" else "article")
            mime_type = "text/plain"
        else:
            raise ValueError(f"unsupported server_path suffix: {suffix}")

        fingerprint = _fingerprint(str(host_path).encode("utf-8") + b"\n" + markdown.encode("utf-8"))
        raw_path = self._raw_path(target_kind, title, fingerprint)
        if not (self.obsidian_root / raw_path).exists():
            rendered = _render_raw_markdown(
                title=title,
                source_type="server_path",
                source=request.source,
                target_kind=target_kind,
                fingerprint=fingerprint,
                mime_type=mime_type,
                body_markdown=markdown,
            )
            (self.obsidian_root / raw_path).parent.mkdir(parents=True, exist_ok=True)
            (self.obsidian_root / raw_path).write_text(rendered, encoding="utf-8")
        return NormalizedSource(
            fingerprint=fingerprint,
            source_type="server_path",
            source=request.source,
            target_kind=target_kind,
            title=title,
            raw_path=str(raw_path),
            mime_type=mime_type,
            markdown=markdown,
            summary=_summary_from_markdown(markdown),
            import_goal=request.import_goal.strip(),
        )

    def _materialize_wiki(self, normalized: NormalizedSource) -> list[Path]:
        pages = self._scan_pages()
        canonicals = self._load_canonicals()
        entity_specs = self._select_entity_specs(normalized, pages, canonicals)
        occupied = {page["slug"] for page in pages}
        occupied.update(spec.slug for spec in entity_specs)
        existing_research = self._match_existing_research(normalized.title, pages)
        research_slug = existing_research.slug if existing_research else self._unique_page_slug(slugify(normalized.title) or "imported-source", occupied, "research")
        occupied.add(research_slug)
        concept_specs = self._select_concept_specs(normalized, pages, canonicals, entity_specs, occupied)
        decision_spec = self._select_decision_spec(normalized, pages, entity_specs, concept_specs, occupied)

        page_paths: list[Path] = []
        entity_paths = [self._write_entity_page(spec, normalized, research_slug) for spec in entity_specs]
        page_paths.extend(entity_paths)
        concept_paths = [self._write_concept_page(spec, normalized, research_slug, entity_paths) for spec in concept_specs]
        page_paths.extend(concept_paths)
        research_path = self._write_research_page(normalized, research_slug, entity_specs, concept_specs)
        page_paths.append(research_path)

        if decision_spec is not None:
            page_paths.append(self._write_decision_page(decision_spec, normalized, entity_specs, concept_specs))

        self._update_hub_flags()
        return page_paths

    def _select_entity_specs(
        self,
        normalized: NormalizedSource,
        pages: list[dict[str, Any]],
        canonicals: list[dict[str, Any]],
    ) -> list[PageSpec]:
        context = f"{normalized.title}\n{normalized.import_goal}\n{normalized.summary}\n{normalized.markdown[:4000]}"
        entity_specs: list[PageSpec] = []
        seen: set[str] = set()

        for canonical in canonicals:
            if canonical.get("type") != "entity":
                continue
            if self._canonical_matches_context(context, canonical):
                spec = self._page_spec_from_canonical(canonical, "entity")
                if spec.slug not in seen:
                    seen.add(spec.slug)
                    entity_specs.append(spec)

        if normalized.host and normalized.host not in GENERIC_HOST_LABELS:
            host_label = normalized.host.replace("www.", "").split(":")[0]
            host_match = self._match_existing_or_canonical_entity(host_label, pages, canonicals)
            if host_match and host_match.slug not in seen:
                seen.add(host_match.slug)
                entity_specs.append(host_match)

        for candidate in _dedupe_preserve(_extract_entities(normalized.title, normalized.markdown)):
            spec = self._match_existing_or_canonical_entity(candidate, pages, canonicals)
            if spec is None or spec.slug in seen:
                continue
            seen.add(spec.slug)
            entity_specs.append(spec)

        if not entity_specs and not _is_document_title_artifact(normalized.title):
            fallback = self._match_existing_or_canonical_entity(normalized.title, pages, canonicals)
            if fallback is not None:
                entity_specs.append(fallback)

        return entity_specs[:3]

    def _select_concept_specs(
        self,
        normalized: NormalizedSource,
        pages: list[dict[str, Any]],
        canonicals: list[dict[str, Any]],
        entity_specs: list[PageSpec],
        occupied: set[str],
    ) -> list[PageSpec]:
        concepts: list[PageSpec] = []
        seen: set[str] = set()
        context = f"{normalized.title}\n{normalized.import_goal}\n{normalized.summary}\n{normalized.markdown[:5000]}"
        entity_aliases = {
            _normalize_lookup(alias)
            for spec in entity_specs
            for alias in [spec.name, spec.slug, *(spec.aliases or [])]
        }

        for canonical in canonicals:
            if canonical.get("type") != "concept":
                continue
            if self._canonical_matches_context(context, canonical):
                existing = self._match_existing_concept(str(canonical.get("name", "")), pages)
                spec = existing or self._page_spec_from_canonical(canonical, "concept")
                if spec.slug in seen:
                    continue
                if spec.slug in occupied and not existing:
                    spec.slug = self._unique_page_slug(spec.slug, occupied, "concept")
                seen.add(spec.slug)
                concepts.append(spec)
                occupied.add(spec.slug)

        for phrase_key, concept in CANONICAL_CONCEPTS.items():
            if _contains_phrase(_normalize_lookup(context), phrase_key):
                existing = self._match_existing_concept(concept["name"], pages)
                slug = existing.slug if existing else concept["slug"]
                if slug in seen:
                    continue
                if slug in occupied and not existing:
                    slug = self._unique_page_slug(slug, occupied, "concept")
                seen.add(slug)
                occupied.add(slug)
                concepts.append(
                    PageSpec(
                        slug=slug,
                        name=existing.name if existing else concept["name"],
                        page_type="concept",
                        aliases=list(existing.aliases if existing else concept["aliases"]),
                        tags=list(existing.tags if existing and existing.tags else concept["tags"]),
                        themes=list(existing.themes if existing and existing.themes else concept["themes"]),
                    )
                )

        for keyword in _dedupe_preserve(_extract_keywords(normalized.title, normalized.markdown)):
            human = _humanize_name(keyword)
            lookup = _normalize_lookup(human)
            if not lookup or lookup in entity_aliases or _is_document_title_artifact(human):
                continue
            base_slug = slugify(human)
            if not base_slug:
                continue
            existing = self._match_existing_concept(human, pages)
            slug = existing.slug if existing else base_slug
            if slug in seen:
                continue
            if slug in occupied and not existing:
                slug = self._unique_page_slug(base_slug, occupied, "concept")
            seen.add(slug)
            occupied.add(slug)
            concepts.append(
                PageSpec(
                    slug=slug,
                    name=existing.name if existing else human,
                    page_type="concept",
                    aliases=list(existing.aliases if existing else []),
                    tags=list(existing.tags if existing and existing.tags else _tag_list(human)),
                    themes=list(
                        existing.themes
                        if existing and existing.themes
                        else self._infer_themes(context, extra_themes=[theme for spec in entity_specs for theme in (spec.themes or [])])
                    ),
                )
            )
            if len(concepts) >= 3:
                break

        return concepts[:3]

    def _match_existing_concept(self, candidate: str, pages: list[dict[str, Any]]) -> PageSpec | None:
        lookup = _normalize_lookup(candidate)
        if not lookup:
            return None
        for page in pages:
            if page["meta"].get("type") != "concept":
                continue
            values = [page["slug"], str(page["meta"].get("name", "")), *(page["meta"].get("aliases", []) or [])]
            if any(_normalize_lookup(str(value)) == lookup or slugify(str(value)) == slugify(candidate) for value in values if str(value).strip()):
                return PageSpec(
                    slug=page["slug"],
                    name=str(page["meta"].get("name", page["slug"])),
                    page_type="concept",
                    aliases=[str(item) for item in page["meta"].get("aliases", []) or []],
                    tags=[str(item) for item in page["meta"].get("tags", []) or []],
                    themes=self._normalize_themes(page["meta"].get("themes", [])),
                )
        return None

    def _match_existing_research(self, candidate: str, pages: list[dict[str, Any]]) -> PageSpec | None:
        lookup = _normalize_lookup(candidate)
        if not lookup:
            return None
        for page in pages:
            if page["meta"].get("type") != "research":
                continue
            values = [page["slug"], str(page["meta"].get("name", ""))]
            if any(_normalize_lookup(str(value)) == lookup or slugify(str(value)) == slugify(candidate) for value in values if str(value).strip()):
                return PageSpec(slug=page["slug"], name=str(page["meta"].get("name", page["slug"])), page_type="research")
        return None

    def _match_existing_decision(self, candidate: str, pages: list[dict[str, Any]]) -> PageSpec | None:
        lookup = _normalize_lookup(candidate)
        if not lookup:
            return None
        for page in pages:
            if page["meta"].get("type") != "decision":
                continue
            values = [page["slug"], str(page["meta"].get("name", ""))]
            if any(_normalize_lookup(str(value)) == lookup or slugify(str(value)) == slugify(candidate) for value in values if str(value).strip()):
                return PageSpec(slug=page["slug"], name=str(page["meta"].get("name", page["slug"])), page_type="decision")
        return None

    def _select_decision_spec(
        self,
        normalized: NormalizedSource,
        pages: list[dict[str, Any]],
        entity_specs: list[PageSpec],
        concept_specs: list[PageSpec],
        occupied: set[str],
    ) -> PageSpec | None:
        if not _should_create_decision(normalized):
            return None
        lower_title = normalized.title.strip()
        existing = self._match_existing_decision(f"Decision: {lower_title}", pages)
        slug = existing.slug if existing else slugify(f"decide-{lower_title}") or "decide-import"
        if slug in occupied and not existing:
            slug = self._unique_page_slug(slug, occupied, "decision")
        themes = self._infer_themes(
            f"{normalized.title}\n{normalized.import_goal}\n{normalized.markdown[:3000]}",
            extra_themes=[theme for spec in entity_specs + concept_specs for theme in (spec.themes or [])],
        )
        return PageSpec(
            slug=slug,
            name=existing.name if existing else f"Decision: {normalized.title}",
            page_type="decision",
            tags=["decisions", *(theme for theme in themes if theme not in {"operations"})][:4],
            themes=themes,
            related=[],
        )

    def _write_entity_page(self, spec: PageSpec, normalized: NormalizedSource, research_slug: str) -> Path:
        path = self.wiki_root / "entities" / f"{spec.slug}.md"
        content = self._render_page_content(
            path=path,
            meta={
                "type": "entity",
                "subtype": spec.subtype or "project",
                "name": spec.name,
                "aliases": sorted(set(spec.aliases or [])),
                "status": "active",
                "confidence": spec.confidence,
                "hub": False,
                "tags": spec.tags or _tag_list(spec.name),
                "themes": spec.themes or ["wiki"],
                "related": [f"research/{research_slug}.md"],
                "updated": _today(),
            },
            title=spec.name,
            sections=[
                ("What it is", f"{spec.name} is a canonical entity in the LLM-Wiki and is updated as new curated sources arrive."),
                ("How we use it", normalized.summary or f"See [[{research_slug}]] for the current synthesis drawn from `{normalized.raw_path}`."),
                (
                    "Key properties",
                    "\n".join(
                        [
                            f"- subtype: {spec.subtype or 'project'}",
                            f"- themes: {', '.join(spec.themes or ['wiki'])}",
                            f"- raw_source: `{normalized.raw_path}`",
                        ]
                    ),
                ),
                (
                    "Connections",
                    "\n".join(
                        [
                            f"- **Synthesis page:** [[{research_slug}]]",
                            f"- **Themes:** {', '.join(spec.themes or ['wiki'])}",
                        ]
                    ),
                ),
                ("Sources", f"- [{normalized.title}]({_raw_link(normalized.raw_path)})"),
            ],
        )
        path.write_text(content, encoding="utf-8")
        return path

    def _write_concept_page(
        self,
        spec: PageSpec,
        normalized: NormalizedSource,
        research_slug: str,
        entity_paths: list[Path],
    ) -> Path:
        path = self.wiki_root / "concepts" / f"{spec.slug}.md"
        entity_links = [f"[[{item.stem}]]" for item in entity_paths]
        content = self._render_page_content(
            path=path,
            meta={
                "type": "concept",
                "name": spec.name,
                "aliases": sorted(set(spec.aliases or [])),
                "confidence": spec.confidence,
                "hub": False,
                "tags": spec.tags or _tag_list(spec.name),
                "themes": spec.themes or ["wiki"],
                "related": [f"research/{research_slug}.md"] + [f"entities/{item.name}" for item in entity_paths],
                "updated": _today(),
            },
            title=spec.name,
            sections=[
                ("Definition", f"{spec.name} is a recurring concept in the curated wiki."),
                ("How it works", normalized.summary or f"See [[{research_slug}]] for the supporting synthesis."),
                ("When to use", f"Use this concept when navigating the source [[{research_slug}]] and related canonical pages."),
                ("Our usage", f"This page is maintained by the wiki-import bridge from `{normalized.source_type}` inputs."),
                (
                    "Connections",
                    "\n".join(
                        [
                            f"- **Related entities:** {', '.join(entity_links) if entity_links else 'none'}",
                            f"- **Synthesis page:** [[{research_slug}]]",
                            f"- **Themes:** {', '.join(spec.themes or ['wiki'])}",
                        ]
                    ),
                ),
                ("Sources", f"- [{normalized.title}]({_raw_link(normalized.raw_path)})"),
            ],
        )
        path.write_text(content, encoding="utf-8")
        return path

    def _write_research_page(
        self,
        normalized: NormalizedSource,
        research_slug: str,
        entity_specs: list[PageSpec],
        concept_specs: list[PageSpec],
    ) -> Path:
        path = self.wiki_root / "research" / f"{research_slug}.md"
        entity_links = [f"[[{item.slug}]]" for item in entity_specs]
        concept_links = [f"[[{item.slug}]]" for item in concept_specs]
        themes = self._infer_themes(
            f"{normalized.title}\n{normalized.import_goal}\n{normalized.markdown[:5000]}",
            extra_themes=[theme for spec in entity_specs + concept_specs for theme in (spec.themes or [])],
        )
        content = self._render_page_content(
            path=path,
            meta={
                "type": "research",
                "name": normalized.title,
                "confidence": "INFERRED",
                "tags": _tag_list(normalized.title),
                "themes": themes,
                "related": [f"entities/{item.slug}.md" for item in entity_specs] + [f"concepts/{item.slug}.md" for item in concept_specs],
                "updated": _today(),
            },
            title=normalized.title,
            sections=[
                ("Question", normalized.import_goal or f"What should the wiki preserve from `{normalized.raw_path}`?"),
                ("Sources", f"- [{normalized.title}]({_raw_link(normalized.raw_path)}) — normalized {normalized.source_type} source"),
                ("Findings", _top_findings(normalized.markdown)),
                ("Synthesis", normalized.summary or "Source imported and linked into the wiki."),
                (
                    "Connections",
                    "\n".join(
                        [
                            f"- **Entities:** {', '.join(entity_links) if entity_links else 'none'}",
                            f"- **Concepts:** {', '.join(concept_links) if concept_links else 'none'}",
                            f"- **Themes:** {', '.join(themes)}",
                        ]
                    ),
                ),
            ],
        )
        path.write_text(content, encoding="utf-8")
        return path

    def _write_decision_page(
        self,
        spec: PageSpec,
        normalized: NormalizedSource,
        entity_specs: list[PageSpec],
        concept_specs: list[PageSpec],
    ) -> Path:
        path = self.wiki_root / "decisions" / f"{spec.slug}.md"
        related = [f"entities/{item.slug}.md" for item in entity_specs] + [f"concepts/{item.slug}.md" for item in concept_specs]
        content = self._render_page_content(
            path=path,
            meta={
                "type": "decision",
                "name": spec.name,
                "date": _today(),
                "status": "closed",
                "confidence": "INFERRED",
                "tags": spec.tags or ["decisions"],
                "themes": spec.themes or ["operations"],
                "related": related,
                "updated": _today(),
            },
            title=spec.name,
            sections=[
                ("Context", normalized.summary or f"The source `{normalized.raw_path}` contains explicit decision-like language worth preserving."),
                ("Options considered", "1. Keep only the raw source\n2. Curate the source into canonical wiki pages"),
                ("Decision", "Curate the source into canonical wiki pages and preserve the raw source as immutable evidence."),
                ("Consequences", "- Pro: durable, searchable synthesis\n- Con: importer remains heuristic and should be reviewed"),
                ("Status", "Closed unless a more explicit ADR supersedes this page."),
            ],
        )
        path.write_text(content, encoding="utf-8")
        return path

    def _refresh_indexes_and_topics(self) -> None:
        pages = self._scan_pages()
        self._write_index(pages)
        self._write_overview(pages)
        self._write_topics(pages)

    def _write_index(self, pages: list[dict[str, Any]]) -> None:
        by_type: dict[str, list[dict[str, Any]]] = {key: [] for key in PAGE_FOLDERS}
        for page in self._unique_pages_by_slug(pages):
            by_type.setdefault(page["meta"].get("type", "research"), []).append(page)

        lines = [
            "# LLM-Wiki Index",
            f"_Last updated: {_today()} by bot_",
            "_Maintained by bot. Do not edit manually._",
            "",
            "System pages:",
            "- [Overview](OVERVIEW.md)",
            "- [Topics](TOPICS.md)",
            "- [Canonicals](CANONICALS.yaml)",
            "- [Schema](SCHEMA.md)",
            "- [Import Queue](IMPORT-QUEUE.md)",
            "- [Operation Log](LOG.md)",
            "",
            "---",
            "",
            "## Concepts",
            "| Page | Summary | Tags | Confidence | Updated |",
            "|------|---------|------|------------|---------|",
        ]
        lines.extend(_index_rows(by_type.get("concept", []), fields=["confidence", "updated"]) or ["| _(empty — populate via ingest)_ | | | | |"])
        lines.extend(
            [
                "",
                "## Entities",
                "| Page | Summary | Tags | Status |",
                "|------|---------|------|--------|",
            ]
        )
        lines.extend(_index_rows(by_type.get("entity", []), fields=["status"]) or ["| _(empty — populate via ingest)_ | | | |"])
        lines.extend(
            [
                "",
                "## Decisions",
                "| Page | Summary | Date | Status |",
                "|------|---------|------|--------|",
            ]
        )
        lines.extend(_index_rows(by_type.get("decision", []), fields=["date", "status"]) or ["| _(empty — populate via ingest)_ | | | |"])
        lines.extend(
            [
                "",
                "## Research",
                "| Page | Summary | Tags | Updated |",
                "|------|---------|------|---------|",
            ]
        )
        lines.extend(_index_rows(by_type.get("research", []), fields=["updated"]) or ["| _(empty — populate via ingest)_ | | | |"])
        lines.extend(["", "## Hub Pages (God Nodes)", "Pages with 5+ incoming wiki links:"])
        incoming = self._incoming_link_counts(pages)
        hub_lines = []
        for page in sorted(self._unique_pages_by_slug(pages), key=lambda item: (-incoming.get(item["slug"], 0), item["rel_path"])):
            count = incoming.get(page["slug"], 0)
            if count >= 5:
                hub_lines.append(f"- [{page['meta'].get('name', page['slug'])}]({page['rel_path']}) — {count} links")
        lines.extend(hub_lines or ["- _(none yet)_"])
        (self.wiki_root / "INDEX.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    def _write_overview(self, pages: list[dict[str, Any]]) -> None:
        unique_pages = self._unique_pages_by_slug(pages)
        incoming = self._incoming_link_counts(unique_pages)
        hubs = sorted(unique_pages, key=lambda item: (-incoming.get(item["slug"], 0), item["rel_path"]))[:5]
        recent = sorted(unique_pages, key=lambda item: (str(item["meta"].get("updated", "")), item["rel_path"]), reverse=True)[:5]
        decisions = [page for page in unique_pages if page["meta"].get("type") == "decision"][:5]
        queue = self._load_queue()
        queue_counts: dict[str, int] = {}
        theme_counts: dict[str, int] = defaultdict(int)
        for item in queue:
            queue_counts[item.get("status", "unknown")] = queue_counts.get(item.get("status", "unknown"), 0) + 1
        for page in unique_pages:
            for theme in page["meta"].get("themes", []) or []:
                theme_counts[str(theme)] += 1

        active_themes = sorted(
            ((theme, count) for theme, count in theme_counts.items()),
            key=lambda item: (-item[1], THEME_ORDER.index(item[0]) if item[0] in THEME_ORDER else 999),
        )[:4]

        lines = [
            "# LLM-Wiki Overview",
            "_Bot-maintained cold-start summary. Keep compact._",
            "",
            "---",
            "",
            "## Active Focus",
            f"- Curated wiki pages: {len(unique_pages)}",
            f"- Queue entries: {len(queue)}",
            "- Prefer `OVERVIEW.md` for boot, `TOPICS.md` for thematic navigation, and `INDEX.md` for full registry.",
            "",
            "## Active Themes",
        ]
        lines.extend([f"- {THEME_LABELS.get(theme, theme.title())} — {count} pages" for theme, count in active_themes] or ["- _(populate after first imports)_"])
        lines.extend(["", "## Hub Pages"])
        lines.extend(
            [f"- [[{page['slug']}]] — {incoming.get(page['slug'], 0)} incoming links" for page in hubs if incoming.get(page["slug"], 0) > 0]
            or ["- _(populate after first imports and lint pass)_"]
        )
        lines.extend(["", "## Active Decisions"])
        lines.extend([f"- [[{page['slug']}]] — {page['summary']}" for page in decisions] or ["- _(populate after first imports)_"])
        lines.extend(["", "## Recent Updates"])
        lines.extend([f"- [[{page['slug']}]] — {page['meta'].get('updated', 'unknown')}" for page in recent] or ["- _(populate after first imports)_"])
        lines.extend(["", "## Import Queue"])
        if queue_counts:
            for status, count in sorted(queue_counts.items()):
                lines.append(f"- {status}: {count}")
        else:
            lines.append("- no queued imports")
        (self.wiki_root / "OVERVIEW.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    def _write_topics(self, pages: list[dict[str, Any]]) -> None:
        unique_pages = self._unique_pages_by_slug(pages)
        incoming = self._incoming_link_counts(unique_pages)
        lines = [
            "# LLM-Wiki Topics",
            "_Bot-maintained thematic navigation. Typed folders stay primary; themes are secondary navigation._",
            "",
            "---",
        ]
        for theme in THEME_ORDER:
            themed = [page for page in unique_pages if theme in (page["meta"].get("themes", []) or [])]
            lines.extend(["", f"## {THEME_LABELS[theme]}"])
            if not themed:
                lines.append("- _(no pages yet)_")
                continue
            entities = sorted(
                [page for page in themed if page["meta"].get("type") == "entity"],
                key=lambda item: (-incoming.get(item["slug"], 0), item["rel_path"]),
            )[:3]
            concepts = sorted(
                [page for page in themed if page["meta"].get("type") == "concept"],
                key=lambda item: (-incoming.get(item["slug"], 0), item["rel_path"]),
            )[:3]
            decisions = sorted(
                [page for page in themed if page["meta"].get("type") == "decision"],
                key=lambda item: (item["meta"].get("updated", ""), item["rel_path"]),
                reverse=True,
            )[:3]
            research = sorted(
                [page for page in themed if page["meta"].get("type") == "research"],
                key=lambda item: (item["meta"].get("updated", ""), item["rel_path"]),
                reverse=True,
            )[:3]
            lines.append("### Anchor Entities")
            lines.extend([f"- [[{page['slug']}]]" for page in entities] or ["- none"])
            lines.append("")
            lines.append("### Core Concepts")
            lines.extend([f"- [[{page['slug']}]]" for page in concepts] or ["- none"])
            lines.append("")
            lines.append("### Active Decisions")
            lines.extend([f"- [[{page['slug']}]]" for page in decisions] or ["- none"])
            lines.append("")
            lines.append("### Research and Synthesis")
            lines.extend([f"- [[{page['slug']}]]" for page in research] or ["- none"])
        (self.wiki_root / "TOPICS.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")

    def _repair_existing_wiki(self) -> list[str]:
        actions: list[str] = []
        pages = self._scan_pages()
        canonicals = self._load_canonicals()

        for canonical in canonicals:
            if canonical.get("type") not in {"entity", "concept"}:
                continue
            folder = "entities" if canonical.get("type") == "entity" else "concepts"
            matching = [
                page
                for page in pages
                if page["meta"].get("type") == canonical.get("type") and self._page_matches_canonical(page, canonical)
            ]
            if not matching:
                continue
            target_path = self.wiki_root / folder / f"{canonical['slug']}.md"
            target_page = next((page for page in matching if page["path"] == target_path), matching[0])
            merged_meta = dict(target_page["meta"])
            merged_meta.update(
                {
                    "type": canonical.get("type"),
                    "name": canonical.get("name", merged_meta.get("name", canonical["slug"])),
                    "aliases": _dedupe_preserve(
                        [
                            *canonical.get("aliases", []),
                            *merged_meta.get("aliases", []),
                            *[page["meta"].get("name", "") for page in matching],
                            *[page["slug"] for page in matching if page["slug"] != canonical["slug"]],
                        ]
                    ),
                    "tags": _dedupe_preserve([*canonical.get("tags", []), *merged_meta.get("tags", [])]),
                    "themes": self._normalize_themes([*canonical.get("themes", []), *merged_meta.get("themes", [])]),
                    "updated": _today(),
                }
            )
            if canonical.get("type") == "entity":
                merged_meta["subtype"] = canonical.get("subtype", merged_meta.get("subtype", "project"))
                merged_meta["status"] = "active"
            content = self._render_page_content(
                path=target_path,
                meta=merged_meta,
                title=str(merged_meta.get("name", canonical["slug"])),
                sections=self._body_to_sections(target_page["body"]),
            )
            target_path.write_text(content, encoding="utf-8")
            rewrite_map = {page["slug"]: canonical["slug"] for page in matching if page["slug"] != canonical["slug"]}
            if rewrite_map:
                self._rewrite_wikilinks(rewrite_map)
            for page in matching:
                if page["path"] != target_path and page["path"].exists():
                    page["path"].unlink()
            if rewrite_map or target_page["path"] != target_path:
                actions.append(f"merged {len(matching)} pages into {folder}/{canonical['slug']}.md")

        pages = self._scan_pages()
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for page in pages:
            groups[page["slug"]].append(page)
        for slug, group in sorted(groups.items()):
            if len(group) <= 1:
                continue
            ordered = sorted(group, key=lambda page: _page_priority(str(page["meta"].get("type", ""))))
            keeper = ordered[0]
            for page in ordered[1:]:
                new_slug = self._unique_page_slug(slug, {item["slug"] for item in self._scan_pages()}, str(page["meta"].get("type", "research")))
                new_path = page["path"].with_name(f"{new_slug}.md")
                page["path"].rename(new_path)
                actions.append(f"renamed {page['rel_path']} -> {new_path.relative_to(self.wiki_root)}")

        pages = self._scan_pages()
        for page in pages:
            if page["meta"].get("type") != "decision":
                continue
            if page["path"].stem.startswith("imported-") or str(page["meta"].get("name", "")).startswith("Imported signals from "):
                page["path"].unlink()
                actions.append(f"removed low-signal decision {page['rel_path']}")

        pages = self._scan_pages()
        for page_type in ("research", "decision"):
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for page in pages:
                if page["meta"].get("type") != page_type:
                    continue
                key = _normalize_lookup(str(page["meta"].get("name", page["slug"])))
                if key:
                    grouped[key].append(page)
            rewrite_map: dict[str, str] = {}
            for _, group in grouped.items():
                if len(group) <= 1:
                    continue
                ordered = sorted(group, key=lambda item: (len(item["slug"]), item["rel_path"]))
                keeper = ordered[0]
                for page in ordered[1:]:
                    rewrite_map[page["slug"]] = keeper["slug"]
                    if page["path"].exists():
                        page["path"].unlink()
                    actions.append(f"merged duplicate {page_type} {page['rel_path']} -> {keeper['rel_path']}")
            if rewrite_map:
                self._rewrite_wikilinks(rewrite_map)
            pages = self._scan_pages()

        pages = self._scan_pages()
        research_by_name = {
            _normalize_lookup(str(page["meta"].get("name", page["slug"]))): page["slug"]
            for page in pages
            if page["meta"].get("type") == "research"
        }
        for page in pages:
            if page["meta"].get("type") != "entity":
                continue
            if page["slug"] in GENERIC_ENTITY_SLUGS:
                page["path"].unlink()
                actions.append(f"removed generic entity {page['rel_path']}")
                continue
            if _is_document_title_artifact(str(page["meta"].get("name", page["slug"]))):
                key = _normalize_lookup(str(page["meta"].get("name", page["slug"])))
                if key in research_by_name:
                    self._rewrite_wikilinks({page["slug"]: research_by_name[key]})
                    page["path"].unlink()
                    actions.append(f"converted source-title entity {page['rel_path']} -> research/{research_by_name[key]}.md")

        pages = self._scan_pages()
        canonicals = self._load_canonicals()
        for page in pages:
            meta = dict(page["meta"])
            if meta.get("type") == "session":
                continue
            changed = False
            themes = self._infer_themes(
                f"{meta.get('name', page['slug'])}\n{page['body']}",
                extra_themes=list(meta.get("themes", []) or []),
            )
            if self._normalize_themes(meta.get("themes", [])) != themes:
                meta["themes"] = themes
                changed = True
            if meta.get("type") in {"entity", "concept"}:
                aliases = _dedupe_preserve([*(meta.get("aliases", []) or []), meta.get("name", ""), page["slug"]])
                if aliases != (meta.get("aliases", []) or []):
                    meta["aliases"] = aliases
                    changed = True
            for canonical in canonicals:
                if canonical.get("slug") == page["slug"] and canonical.get("type") == meta.get("type"):
                    merged_aliases = _dedupe_preserve([*canonical.get("aliases", []), *(meta.get("aliases", []) or [])])
                    if merged_aliases != (meta.get("aliases", []) or []):
                        meta["aliases"] = merged_aliases
                        changed = True
                    canonical_themes = self._normalize_themes([*canonical.get("themes", []), *(meta.get("themes", []) or [])])
                    if canonical_themes != (meta.get("themes", []) or []):
                        meta["themes"] = canonical_themes
                        changed = True
                    merged_tags = _dedupe_preserve([*canonical.get("tags", []), *(meta.get("tags", []) or [])])
                    if merged_tags != (meta.get("tags", []) or []):
                        meta["tags"] = merged_tags
                        changed = True
                    if canonical.get("type") == "entity" and canonical.get("name") and meta.get("name") != canonical.get("name"):
                        meta["name"] = canonical["name"]
                        changed = True
            if changed:
                page["path"].write_text(_dump_frontmatter(meta) + "\n" + page["body"].lstrip("\n"), encoding="utf-8")
                actions.append(f"normalized metadata for {page['rel_path']}")

        self._update_hub_flags()
        self._refresh_indexes_and_topics()
        if actions:
            self._append_log(
                operation="migration",
                source="repair=true",
                description="canonical identity and thematic navigation repair",
                created=[],
                updated=[self.wiki_root / "INDEX.md", self.wiki_root / "OVERVIEW.md", self.wiki_root / "TOPICS.md"],
                insight="Repaired duplicate slugs, canonicalized entity pages, and rebuilt thematic navigation.",
            )
        return actions

    def _duplicate_basename_findings(self, pages: list[dict[str, Any]]) -> list[str]:
        groups: dict[str, list[str]] = defaultdict(list)
        for page in pages:
            groups[page["slug"]].append(page["rel_path"])
        return [f"{slug}: {', '.join(sorted(paths))}" for slug, paths in sorted(groups.items()) if len(paths) > 1]

    def _duplicate_token_slug_findings(self, pages: list[dict[str, Any]]) -> list[str]:
        findings: list[str] = []
        for page in pages:
            tokens = [token for token in page["slug"].split("-") if token]
            if len(tokens) >= 2 and len(tokens) != len(dict.fromkeys(tokens)):
                findings.append(page["rel_path"])
        return sorted(findings)

    def _source_title_entity_findings(self, pages: list[dict[str, Any]]) -> list[str]:
        findings: list[str] = []
        for page in pages:
            if page["meta"].get("type") != "entity":
                continue
            label = str(page["meta"].get("name", page["slug"]))
            if _is_document_title_artifact(label) and page["slug"] not in {item["slug"] for item in self._load_canonicals()}:
                findings.append(page["rel_path"])
        return sorted(findings)

    def _alias_collision_findings(self, pages: list[dict[str, Any]]) -> list[str]:
        owners: dict[str, set[str]] = defaultdict(set)
        for page in pages:
            for value in [page["slug"], str(page["meta"].get("name", "")), *(page["meta"].get("aliases", []) or [])]:
                lookup = _normalize_lookup(str(value))
                if lookup:
                    owners[lookup].add(page["rel_path"])
        findings = []
        for alias, paths in sorted(owners.items()):
            if len(paths) > 1:
                findings.append(f"{alias}: {', '.join(sorted(paths))}")
        return findings

    def _missing_theme_findings(self, pages: list[dict[str, Any]]) -> list[str]:
        findings = []
        for page in pages:
            if page["meta"].get("type") == "session":
                continue
            themes = self._normalize_themes(page["meta"].get("themes", []))
            if not themes:
                findings.append(page["rel_path"])
        return sorted(findings)

    def _broken_canonical_findings(self, canonicals: list[dict[str, Any]]) -> list[str]:
        findings = []
        for canonical in canonicals:
            folder = canonical.get("preferred_folder") or PAGE_FOLDERS.get(str(canonical.get("type", "")), "entities")
            suffix = ".md" if folder != "" else ""
            path = self.wiki_root / folder / f"{canonical['slug']}{suffix}"
            if canonical.get("type") == "concept" and folder == "concepts":
                path = self.wiki_root / "concepts" / f"{canonical['slug']}.md"
            elif canonical.get("type") == "entity":
                path = self.wiki_root / "entities" / f"{canonical['slug']}.md"
            if not path.exists():
                findings.append(f"{canonical['slug']} -> missing {path.relative_to(self.wiki_root)}")
        return findings

    def _topics_drift(self, pages: list[dict[str, Any]]) -> list[str]:
        path = self.wiki_root / "TOPICS.md"
        if not path.exists():
            return ["TOPICS.md is missing"]
        rendered = self._render_topics_text(pages)
        current = path.read_text(encoding="utf-8")
        return ["TOPICS.md differs from rendered theme view"] if current != rendered else []

    def _load_queue(self) -> list[dict[str, Any]]:
        path = self.wiki_root / "IMPORT-QUEUE.md"
        if not path.exists():
            return []
        text = path.read_text(encoding="utf-8")
        start = text.find(QUEUE_START)
        end = text.find(QUEUE_END)
        if start == -1 or end == -1:
            return []
        chunk = text[start + len(QUEUE_START):end]
        match = re.search(r"```json\s*(.*?)\s*```", chunk, re.S)
        if not match:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _save_queue(self, queue: list[dict[str, Any]]) -> None:
        path = self.wiki_root / "IMPORT-QUEUE.md"
        text = path.read_text(encoding="utf-8") if path.exists() else "# LLM-Wiki Import Queue\n"
        rendered = f"{QUEUE_START}\n```json\n{json.dumps(queue, ensure_ascii=False, indent=2)}\n```\n{QUEUE_END}"
        if QUEUE_START in text and QUEUE_END in text:
            text = re.sub(f"{re.escape(QUEUE_START)}.*?{re.escape(QUEUE_END)}", rendered, text, flags=re.S)
        else:
            text = text.rstrip() + "\n\n" + rendered + "\n"
        path.write_text(text, encoding="utf-8")

    def _upsert_queue_entry(self, queue: list[dict[str, Any]], fingerprint: str, patch: dict[str, Any]) -> dict[str, Any]:
        for item in queue:
            if item.get("fingerprint") == fingerprint:
                item.update(patch)
                item["fingerprint"] = fingerprint
                return item
        patch = dict(patch)
        patch["fingerprint"] = fingerprint
        queue.append(patch)
        return patch

    def _raw_path(self, target_kind: str, title: str, fingerprint: str) -> Path:
        folder = "articles" if target_kind == "article" else "documents"
        slug = slugify(title) or "imported-source"
        return Path("raw") / folder / f"{_today()}-{slug}-{fingerprint[:10]}.md"

    def _resolve_host_path(self, host_path: Path) -> Path:
        if str(host_path).startswith("/opt/"):
            return self.host_opt_root / host_path.relative_to("/opt")
        if host_path.is_absolute():
            return host_path
        return self.obsidian_root / host_path

    def _render_page_content(self, *, path: Path, meta: dict[str, Any], title: str, sections: list[tuple[str, str]]) -> str:
        existing_meta, existing_body = _split_frontmatter(path.read_text(encoding="utf-8")) if path.exists() else ({}, "")
        merged_meta = self._merge_meta(existing_meta, meta)
        merged_sections = self._merge_sections(existing_body, sections)
        return self._render_page(meta=merged_meta, title=title, sections=merged_sections)

    def _render_page(self, *, meta: dict[str, Any], title: str, sections: list[tuple[str, str]]) -> str:
        lines = [_dump_frontmatter(meta), "", f"# {title}", ""]
        for heading, content in sections:
            lines.append(f"## {heading}")
            lines.append(content.strip() or "_pending_")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _merge_meta(self, existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        meta = dict(existing)
        for key, value in incoming.items():
            if key in {"aliases", "tags", "themes", "related"}:
                meta[key] = _dedupe_preserve([*(meta.get(key, []) or []), *(value or [])])
            elif key == "hub":
                meta[key] = bool(value)
            else:
                meta[key] = value
        if meta.get("type") in {"entity", "concept"}:
            meta["aliases"] = _dedupe_preserve([*(meta.get("aliases", []) or []), str(meta.get("name", "")), ""])
            meta["aliases"] = [item for item in meta["aliases"] if item]
        if meta.get("type") != "session":
            meta["themes"] = self._normalize_themes(meta.get("themes", []))
        return meta

    def _merge_sections(self, existing_body: str, incoming_sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
        existing_sections = {heading: content for heading, content in self._body_to_sections(existing_body)}
        merged: list[tuple[str, str]] = []
        for heading, incoming in incoming_sections:
            old = existing_sections.pop(heading, "")
            merged.append((heading, _merge_section_text(old, incoming, heading)))
        for heading, content in existing_sections.items():
            merged.append((heading, content))
        return merged

    def _body_to_sections(self, body: str) -> list[tuple[str, str]]:
        if not body.strip():
            return []
        lines = body.splitlines()
        sections: list[tuple[str, str]] = []
        current_heading: str | None = None
        current_lines: list[str] = []
        for line in lines:
            if line.startswith("## "):
                if current_heading is not None:
                    sections.append((current_heading, "\n".join(current_lines).strip()))
                current_heading = line[3:].strip()
                current_lines = []
                continue
            if current_heading is not None:
                current_lines.append(line)
        if current_heading is not None:
            sections.append((current_heading, "\n".join(current_lines).strip()))
        return sections

    def _ensure_layout(self) -> None:
        for path in [
            self.wiki_root / "concepts",
            self.wiki_root / "entities",
            self.wiki_root / "decisions",
            self.wiki_root / "sessions",
            self.wiki_root / "research",
            self.wiki_root / "templates",
            self.raw_root / "articles",
            self.raw_root / "documents",
            self.raw_root / "signals",
            self.state_root,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        self._ensure_system_file(
            self.wiki_root / "IMPORT-QUEUE.md",
            "# LLM-Wiki Import Queue\n\n<!-- wiki-import-queue:start -->\n```json\n[]\n```\n<!-- wiki-import-queue:end -->\n",
        )
        self._ensure_system_file(self.wiki_root / "INDEX.md", _default_index_text())
        self._ensure_system_file(self.wiki_root / "OVERVIEW.md", _default_overview_text())
        self._ensure_system_file(self.wiki_root / "TOPICS.md", _default_topics_text())
        self._ensure_system_file(self.wiki_root / "LOG.md", "# LLM-Wiki Operation Log\n")
        self._ensure_system_file(self.wiki_root / "SCHEMA.md", "# LLM-Wiki Schema\n")
        self._ensure_system_file(self.wiki_root / "CANONICALS.yaml", _default_canonicals_yaml())

    def _ensure_system_file(self, path: Path, content: str) -> None:
        if not path.exists():
            path.write_text(content, encoding="utf-8")

    def _write_status(self, payload: dict[str, Any]) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        (self.state_root / "wiki-import-status.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _scan_pages(self) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        for path in sorted(self.wiki_root.rglob("*.md")):
            if path.name in SYSTEM_FILES or "templates" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            meta, body = _split_frontmatter(text)
            pages.append(
                {
                    "path": path,
                    "rel_path": str(path.relative_to(self.wiki_root)),
                    "slug": path.stem,
                    "meta": meta,
                    "body": body,
                    "summary": _summary_from_markdown(body),
                }
            )
        return pages

    def _unique_pages_by_slug(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in sorted(pages, key=lambda item: (item["slug"], _page_priority(str(item["meta"].get("type", ""))), item["rel_path"])):
            if page["slug"] in seen:
                continue
            seen.add(page["slug"])
            result.append(page)
        return result

    def _update_hub_flags(self) -> None:
        pages = self._scan_pages()
        incoming = self._incoming_link_counts(pages)
        for page in pages:
            meta = dict(page["meta"])
            current = bool(meta.get("hub", False))
            desired = incoming.get(page["slug"], 0) >= 5
            if current != desired:
                meta["hub"] = desired
                page["path"].write_text(_dump_frontmatter(meta) + "\n" + page["body"].lstrip("\n"), encoding="utf-8")

    def _incoming_link_counts(self, pages: list[dict[str, Any]]) -> dict[str, int]:
        known = {page["slug"] for page in pages}
        counts: dict[str, int] = {}
        for page in pages:
            for slug in set(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", page["body"])):
                if slug in known:
                    counts[slug] = counts.get(slug, 0) + 1
        return counts

    def _missing_link_findings(self, page: dict[str, Any], pages: list[dict[str, Any]]) -> list[str]:
        findings: list[str] = []
        linked = set(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", page["body"]))
        lower_body = page["body"].lower()
        for other in pages:
            if other["slug"] == page["slug"]:
                continue
            title = str(other["meta"].get("name", other["slug"])).strip()
            if len(title) < 4:
                continue
            if title.lower() in lower_body and other["slug"] not in linked:
                findings.append(f"{page['rel_path']} mentions `{title}` without `[[{other['slug']}]]`")
        return findings

    def _rewrite_wikilinks(self, mapping: dict[str, str]) -> None:
        if not mapping:
            return
        for path in sorted(self.wiki_root.rglob("*.md")):
            if path.name == "CANONICALS.yaml":
                continue
            text = path.read_text(encoding="utf-8")
            original = text
            for old, new in mapping.items():
                text = re.sub(rf"\[\[{re.escape(old)}(\|[^\]]+)?\]\]", lambda match: f"[[{new}{match.group(1) or ''}]]", text)
            if text != original:
                path.write_text(text, encoding="utf-8")

    def _load_canonicals(self) -> list[dict[str, Any]]:
        path = self.wiki_root / "CANONICALS.yaml"
        if not path.exists():
            path.write_text(_default_canonicals_yaml(), encoding="utf-8")
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items = payload.get("canonicals") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return list(DEFAULT_CANONICALS)
        return [item for item in items if isinstance(item, dict) and item.get("slug")]

    def _page_spec_from_canonical(self, canonical: dict[str, Any], expected_type: str) -> PageSpec:
        return PageSpec(
            slug=str(canonical["slug"]),
            name=str(canonical.get("name") or _humanize_name(str(canonical["slug"]))),
            page_type=expected_type,
            subtype=str(canonical.get("subtype", "")),
            aliases=[item for item in canonical.get("aliases", []) if str(item).strip()],
            tags=[str(item) for item in canonical.get("tags", []) if str(item).strip()],
            themes=self._normalize_themes(canonical.get("themes", [])),
            related=[],
        )

    def _match_existing_or_canonical_entity(
        self,
        candidate: str,
        pages: list[dict[str, Any]],
        canonicals: list[dict[str, Any]],
    ) -> PageSpec | None:
        lookup = _normalize_lookup(candidate)
        if not lookup or _is_document_title_artifact(candidate):
            return None
        for canonical in canonicals:
            if canonical.get("type") == "entity" and self._canonical_matches_label(candidate, canonical):
                return self._page_spec_from_canonical(canonical, "entity")
        for page in pages:
            if page["meta"].get("type") != "entity":
                continue
            values = [page["slug"], str(page["meta"].get("name", "")), *(page["meta"].get("aliases", []) or [])]
            if any(_normalize_lookup(value) == lookup for value in values if str(value).strip()):
                return PageSpec(
                    slug=page["slug"],
                    name=str(page["meta"].get("name", page["slug"])),
                    page_type="entity",
                    subtype=str(page["meta"].get("subtype", "project")),
                    aliases=[str(item) for item in page["meta"].get("aliases", []) or []],
                    tags=[str(item) for item in page["meta"].get("tags", []) or []],
                    themes=self._normalize_themes(page["meta"].get("themes", [])),
                )
        slug = slugify(candidate)
        if not slug or slug in GENERIC_ENTITY_SLUGS:
            return None
        unique_slug = self._unique_page_slug(slug, {page["slug"] for page in pages}, "entity")
        return PageSpec(
            slug=unique_slug,
            name=_humanize_name(candidate),
            page_type="entity",
            subtype="project",
            aliases=[candidate],
            tags=_tag_list(candidate),
            themes=self._infer_themes(candidate),
        )

    def _canonical_matches_context(self, context: str, canonical: dict[str, Any]) -> bool:
        normalized_context = _normalize_lookup(context)
        for value in [canonical.get("slug", ""), canonical.get("name", ""), *(canonical.get("aliases", []) or [])]:
            candidate = _normalize_lookup(str(value))
            if candidate and _contains_phrase(normalized_context, candidate):
                return True
        return False

    def _canonical_matches_label(self, label: str, canonical: dict[str, Any]) -> bool:
        raw = label.strip()
        normalized = _normalize_lookup(raw)
        if not normalized:
            return False
        if raw.lower() == str(canonical.get("slug", "")).lower():
            return True
        if slugify(raw) == slugify(str(canonical.get("slug", ""))):
            return True
        for value in [canonical.get("name", ""), *(canonical.get("aliases", []) or [])]:
            text = str(value).strip()
            if text and raw.lower() == text.lower():
                return True
            if normalized and normalized == _normalize_lookup(text):
                return True
            if slugify(raw) and slugify(raw) == slugify(text):
                return True
        return False

    def _page_matches_canonical(self, page: dict[str, Any], canonical: dict[str, Any]) -> bool:
        values = [page["slug"], str(page["meta"].get("name", "")), *(page["meta"].get("aliases", []) or [])]
        return any(self._canonical_matches_label(str(value), canonical) for value in values if str(value).strip())

    def _unique_page_slug(self, base_slug: str, occupied: set[str], page_type: str) -> str:
        candidate = base_slug or "imported-source"
        if candidate not in occupied:
            return candidate
        suffix = {"entity": "entity", "concept": "concept", "research": "research", "decision": "decision"}.get(page_type, "page")
        candidate = f"{base_slug}-{suffix}"
        if candidate not in occupied:
            return candidate
        counter = 2
        while f"{candidate}-{counter}" in occupied:
            counter += 1
        return f"{candidate}-{counter}"

    def _infer_themes(self, text: str, *, extra_themes: list[str] | None = None) -> list[str]:
        scores: dict[str, int] = defaultdict(int)
        lookup = _normalize_lookup(text)
        for theme, keywords in THEME_KEYWORDS.items():
            for keyword in keywords:
                if _contains_phrase(lookup, _normalize_lookup(keyword)):
                    scores[theme] += 2 if " " in keyword else 1
        for theme in extra_themes or []:
            if theme in THEME_ORDER:
                scores[theme] += 2
        if not scores:
            scores["wiki"] = 1
        ordered = sorted(
            scores.items(),
            key=lambda item: (-item[1], THEME_ORDER.index(item[0]) if item[0] in THEME_ORDER else 999),
        )
        return [theme for theme, _ in ordered[:3]]

    def _normalize_themes(self, values: list[Any] | Any) -> list[str]:
        if isinstance(values, str):
            values = [values]
        result: list[str] = []
        for item in values or []:
            theme = str(item).strip().lower().replace(" ", "-")
            if theme in THEME_ORDER and theme not in result:
                result.append(theme)
        return result[:3]

    def _render_topics_text(self, pages: list[dict[str, Any]]) -> str:
        unique_pages = self._unique_pages_by_slug(pages)
        incoming = self._incoming_link_counts(unique_pages)
        lines = [
            "# LLM-Wiki Topics",
            "_Bot-maintained thematic navigation. Typed folders stay primary; themes are secondary navigation._",
            "",
            "---",
        ]
        for theme in THEME_ORDER:
            themed = [page for page in unique_pages if theme in (page["meta"].get("themes", []) or [])]
            lines.extend(["", f"## {THEME_LABELS[theme]}"])
            if not themed:
                lines.append("- _(no pages yet)_")
                continue
            entities = sorted(
                [page for page in themed if page["meta"].get("type") == "entity"],
                key=lambda item: (-incoming.get(item["slug"], 0), item["rel_path"]),
            )[:3]
            concepts = sorted(
                [page for page in themed if page["meta"].get("type") == "concept"],
                key=lambda item: (-incoming.get(item["slug"], 0), item["rel_path"]),
            )[:3]
            decisions = sorted(
                [page for page in themed if page["meta"].get("type") == "decision"],
                key=lambda item: (item["meta"].get("updated", ""), item["rel_path"]),
                reverse=True,
            )[:3]
            research = sorted(
                [page for page in themed if page["meta"].get("type") == "research"],
                key=lambda item: (item["meta"].get("updated", ""), item["rel_path"]),
                reverse=True,
            )[:3]
            lines.append("### Anchor Entities")
            lines.extend([f"- [[{page['slug']}]]" for page in entities] or ["- none"])
            lines.append("")
            lines.append("### Core Concepts")
            lines.extend([f"- [[{page['slug']}]]" for page in concepts] or ["- none"])
            lines.append("")
            lines.append("### Active Decisions")
            lines.extend([f"- [[{page['slug']}]]" for page in decisions] or ["- none"])
            lines.append("")
            lines.append("### Research and Synthesis")
            lines.extend([f"- [[{page['slug']}]]" for page in research] or ["- none"])
        return "\n".join(lines).strip() + "\n"

    def _append_log(self, *, operation: str, source: str, description: str, created: list[Path], updated: list[Path], insight: str) -> None:
        path = self.wiki_root / "LOG.md"
        block = [
            f"## [{_today()}] {operation} | {description}",
            f"Source: {source}",
            _log_line("Pages created", [str(item.relative_to(self.wiki_root)) for item in created if item.exists()]),
            _log_line("Pages updated", [str(item.relative_to(self.wiki_root)) for item in updated if item.exists()]),
            f"Key insight: {insight}",
            "",
        ]
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n".join(block))


def slugify(value: str) -> str:
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    tokens = [token for token in lowered.strip("-").split("-") if token]
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token not in seen:
            deduped.append(token)
            seen.add(token)
    return "-".join(deduped)[:80]


def _title_from_url(url: str) -> str:
    slug = Path(urlparse(url).path).stem.replace("-", " ").replace("_", " ").strip()
    return slug.title() if slug else urlparse(url).netloc


def _extract_html_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.text.strip():
        return soup.title.text.strip()
    first_h1 = soup.find("h1")
    return first_h1.get_text(" ", strip=True) if first_h1 else ""


def _html_to_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return markdownify(str(main), heading_style="ATX").strip()


def _pdf_to_markdown(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    text = "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)
    return text.strip()


def _docx_to_markdown(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    return "\n\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    _, rest = text.split("---\n", 1)
    yaml_text, body = rest.split("\n---\n", 1)
    return yaml.safe_load(yaml_text) or {}, body


def _dump_frontmatter(meta: dict[str, Any]) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip() + "\n---"


def _fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _render_raw_markdown(
    *,
    title: str,
    source_type: str,
    source: str,
    target_kind: str,
    fingerprint: str,
    mime_type: str,
    body_markdown: str,
) -> str:
    meta = {
        "type": f"raw-{target_kind}",
        "source_type": source_type,
        "source": source,
        "title": title,
        "fingerprint": fingerprint,
        "mime_type": mime_type,
        "saved_at": _utc_now(),
    }
    return _dump_frontmatter(meta) + f"\n\n# {title}\n\n{body_markdown.strip()}\n"


def _summary_from_markdown(markdown_text: str, *, limit: int = 180) -> str:
    text = re.sub(r"^\s*#.*$", "", markdown_text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() + ("..." if len(text) > limit else "")


def _extract_keywords(title: str, markdown_text: str) -> list[str]:
    text = f"{title}\n{markdown_text}"
    counts: dict[str, int] = {}
    for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", text):
        clean = word.lower().strip("-")
        if clean in STOPWORDS or clean in DOCUMENT_ARTIFACT_PATTERNS:
            continue
        counts[clean] = counts.get(clean, 0) + 1
    return [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:8]]


def _extract_entities(title: str, markdown_text: str) -> list[str]:
    candidates = re.findall(r"\b(?:[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,2})\b", f"{title}\n{markdown_text[:2500]}")
    cleaned = []
    for candidate in candidates:
        stripped = candidate.strip()
        if len(stripped) < 4 or _is_document_title_artifact(stripped):
            continue
        cleaned.append(stripped)
    return cleaned[:12]


def _dedupe_preserve(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _normalize_lookup(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _humanize_name(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if value.islower():
        return value.replace("-", " ").title()
    return re.sub(r"\s+", " ", value)


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:80]
    return "Imported Text"


def _top_findings(markdown_text: str) -> str:
    lines = [line.strip() for line in markdown_text.splitlines() if line.strip()][:5]
    if not lines:
        return "### Finding One\nNo structured findings extracted yet."
    findings = []
    for idx, line in enumerate(lines[:3], start=1):
        findings.append(f"### Finding {idx}\n{line}")
    return "\n\n".join(findings)


def _should_create_decision(normalized: NormalizedSource) -> bool:
    goal = normalized.import_goal.lower()
    if any(marker in goal for marker in ["decision", "why ", "choose", "choice", "rationale", "adr"]):
        return True
    lower = normalized.markdown.lower()
    strong_markers = ["## decision", "## options considered", "## consequences", "we decided", "decision:", "rejected because"]
    return sum(1 for marker in strong_markers if marker in lower) >= 2


def _resolve_target_kind(requested: str, default: str) -> str:
    requested = (requested or "auto").strip().lower()
    if requested in {"article", "document"}:
        return requested
    return default


def _tag_list(value: str) -> list[str]:
    return [tag for tag in slugify(value).split("-") if tag][:4]


def _raw_link(raw_path: str) -> str:
    return f"../../{raw_path}"


def _log_line(label: str, items: list[str]) -> str:
    return f"{label}: " + (", ".join(sorted(set(items))) if items else "none")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _index_rows(pages: list[dict[str, Any]], *, fields: list[str]) -> list[str]:
    rows: list[str] = []
    for page in sorted(pages, key=lambda item: item["rel_path"]):
        name = page["meta"].get("name", page["slug"])
        summary = page["summary"].replace("|", "\\|")
        tags = ", ".join(page["meta"].get("tags", []))
        cells = [f"[{name}]({page['rel_path']})", summary, tags]
        for field in fields:
            cells.append(str(page["meta"].get(field, "")))
        rows.append("| " + " | ".join(cells) + " |")
    return rows


def _empty_markdown_sections(body: str) -> list[str]:
    headers = list(re.finditer(r"^##\s+(.+)$", body, flags=re.M))
    empty: list[str] = []
    for index, match in enumerate(headers):
        start = match.end()
        end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
        chunk = body[start:end].strip()
        if not chunk or chunk == "_pending_":
            empty.append(match.group(1).strip())
    return empty


def _page_priority(page_type: str) -> int:
    return {"entity": 0, "concept": 1, "research": 2, "decision": 3, "session": 4}.get(page_type, 9)


def _normalize_lookup(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _contains_phrase(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    if haystack == needle:
        return True
    return f" {needle} " in f" {haystack} "


def _is_document_title_artifact(value: str) -> bool:
    lookup = _normalize_lookup(value)
    if not lookup:
        return False
    if lookup in DOCUMENT_ARTIFACT_PATTERNS:
        return True
    words = lookup.split()
    artifact_words = {"readme", "setup", "operations", "architecture", "security", "design", "repository", "article", "guide", "manual"}
    if len(words) >= 2 and any(word in artifact_words for word in words):
        return True
    return any(f" {token} " in f" {lookup} " for token in DOCUMENT_ARTIFACT_PATTERNS if " " in token)


def _merge_section_text(existing: str, incoming: str, heading: str) -> str:
    existing = existing.strip()
    incoming = incoming.strip()
    if not existing or existing == "_pending_":
        return incoming
    if not incoming or incoming == "_pending_" or incoming in existing:
        return existing
    if heading in {"Sources", "Connections", "Key properties"}:
        merged = _dedupe_preserve([*existing.splitlines(), *incoming.splitlines()])
        return "\n".join(line for line in merged if line.strip())
    if existing in incoming:
        return incoming
    return existing.rstrip() + "\n\n" + incoming


def _default_canonicals_yaml() -> str:
    return yaml.safe_dump({"canonicals": DEFAULT_CANONICALS}, sort_keys=False, allow_unicode=True)


def _default_overview_text() -> str:
    return (
        "# LLM-Wiki Overview\n"
        "_Bot-maintained cold-start summary. Keep compact._\n\n"
        "---\n\n"
        "## Active Focus\n"
        "- LLM-Wiki rollout is active.\n"
        "- Prefer canonical wiki pages over raw sources for retrieval.\n"
        "- Read `TOPICS.md` for thematic navigation and `SCHEMA.md` before any wiki write operation.\n\n"
        "## Active Themes\n"
        "- _(populate after first imports)_\n\n"
        "## Hub Pages\n"
        "- _(populate after first imports and lint pass)_\n\n"
        "## Active Decisions\n"
        "- _(populate after first imports)_\n\n"
        "## Recent Updates\n"
        "- _(populate after first imports)_\n\n"
        "## Import Queue\n"
        "- See `IMPORT-QUEUE.md` for pending curated imports.\n"
    )


def _default_index_text() -> str:
    return (
        "# LLM-Wiki Index\n"
        "_Last updated: — (bootstrap pending)_\n"
        "_Maintained by bot. Do not edit manually._\n\n"
        "System pages:\n"
        "- [Overview](OVERVIEW.md)\n"
        "- [Topics](TOPICS.md)\n"
        "- [Canonicals](CANONICALS.yaml)\n"
        "- [Schema](SCHEMA.md)\n"
        "- [Import Queue](IMPORT-QUEUE.md)\n"
        "- [Operation Log](LOG.md)\n\n"
        "---\n\n"
        "## Concepts\n"
        "| Page | Summary | Tags | Confidence | Updated |\n"
        "|------|---------|------|------------|---------|\n"
        "| _(empty — populate via ingest)_ | | | | |\n\n"
        "## Entities\n"
        "| Page | Summary | Tags | Status |\n"
        "|------|---------|------|--------|\n"
        "| _(empty — populate via ingest)_ | | | |\n\n"
        "## Decisions\n"
        "| Page | Summary | Date | Status |\n"
        "|------|---------|------|--------|\n"
        "| _(empty — populate via ingest)_ | | | |\n\n"
        "## Research\n"
        "| Page | Summary | Tags | Updated |\n"
        "|------|---------|------|---------|\n"
        "| _(empty — populate via ingest)_ | | | |\n\n"
        "## Hub Pages (God Nodes)\n"
        "_Pages with 5+ incoming wiki links. Populated after first lint run._\n"
    )


def _default_topics_text() -> str:
    lines = [
        "# LLM-Wiki Topics",
        "_Bot-maintained thematic navigation. Typed folders stay primary; themes are secondary navigation._",
        "",
        "---",
    ]
    for theme in THEME_ORDER:
        lines.extend(
            [
                "",
                f"## {THEME_LABELS[theme]}",
                "- _(no pages yet)_",
            ]
        )
    return "\n".join(lines).strip() + "\n"
