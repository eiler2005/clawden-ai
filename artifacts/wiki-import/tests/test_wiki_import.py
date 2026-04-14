from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REPO_ROOT = ROOT.parents[1]

from importer import ImportRequest, WikiImporter


def scaffold(root: Path) -> None:
    wiki = root / "wiki"
    raw = root / "raw"
    for path in [
        wiki / "concepts",
        wiki / "entities",
        wiki / "decisions",
        wiki / "sessions",
        wiki / "research",
        raw / "articles",
        raw / "documents",
        raw / "signals",
    ]:
        path.mkdir(parents=True, exist_ok=True)
    (wiki / "SCHEMA.md").write_text("# schema\n", encoding="utf-8")
    (wiki / "LOG.md").write_text("# log\n", encoding="utf-8")
    (wiki / "INDEX.md").write_text("# index\n", encoding="utf-8")
    (wiki / "OVERVIEW.md").write_text("# overview\n", encoding="utf-8")
    (wiki / "IMPORT-QUEUE.md").write_text(
        "# queue\n\n<!-- wiki-import-queue:start -->\n```json\n[]\n```\n<!-- wiki-import-queue:end -->\n",
        encoding="utf-8",
    )


class WikiImportTests(unittest.TestCase):
    def test_text_import_creates_raw_and_wiki_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            result = importer.import_source(
                ImportRequest(
                    source_type="text",
                    source="# LightRAG Decision\n\nWe decided to use LightRAG because graph traversal matters for wiki recall.",
                    title="LightRAG Decision",
                )
            )

            self.assertTrue(result["ok"])
            self.assertTrue((root / result["raw_path"]).exists())
            self.assertTrue(any(path.startswith("wiki/research/") for path in result["page_paths"]))
            queue_text = (root / "wiki" / "IMPORT-QUEUE.md").read_text(encoding="utf-8")
            self.assertIn('"status": "done"', queue_text)
            self.assertIn("## Import Queue", (root / "wiki" / "OVERVIEW.md").read_text(encoding="utf-8"))

    @patch("importer.requests.get")
    def test_url_import_normalizes_into_article(self, mock_get) -> None:
        html = "<html><head><title>Graphify Overview</title></head><body><article><h1>Graphify Overview</h1><p>Graphify builds knowledge graphs from source material.</p></article></body></html>"
        mock_get.return_value = Mock(status_code=200, headers={"Content-Type": "text/html"}, text=html)
        mock_get.return_value.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            result = importer.import_source(
                ImportRequest(
                    source_type="url",
                    source="https://example.com/graphify-overview",
                )
            )

            self.assertTrue(result["ok"])
            raw_path = root / result["raw_path"]
            self.assertTrue(raw_path.exists())
            self.assertIn("type: raw-article", raw_path.read_text(encoding="utf-8"))

    def test_server_path_import_reads_from_host_opt_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            host_opt = root / "host-opt"
            host_source = host_opt / "docs" / "input.txt"
            host_source.parent.mkdir(parents=True, exist_ok=True)
            host_source.write_text("Server path content about Obsidian and LightRAG.", encoding="utf-8")
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, host_opt_root=host_opt, state_root=root / "state")
            result = importer.import_source(
                ImportRequest(
                    source_type="server_path",
                    source="/opt/docs/input.txt",
                    target_kind="document",
                )
            )

            self.assertTrue(result["ok"])
            self.assertTrue((root / result["raw_path"]).exists())
            self.assertIn("documents", result["raw_path"])

    def test_lint_reports_empty_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            (root / "wiki" / "concepts" / "sample.md").write_text(
                "---\ntype: concept\nname: Sample\nconfidence: CONFIRMED\nhub: false\ntags: [sample]\nrelated: []\nupdated: 2024-01-01\n---\n\n# Sample\n\n## Definition\n\n## Connections\n_pending_\n",
                encoding="utf-8",
            )
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            result = importer.lint()
            self.assertTrue(result["ok"])
            self.assertIn("Empty Sections", result["report"])
            self.assertGreaterEqual(result["empty_section_count"], 1)

    def test_dedup_updates_existing_queue_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            request = ImportRequest(source_type="text", source="Repeated body", title="Repeated Body")
            first = importer.import_source(request)
            second = importer.import_source(request)
            queue_text = (root / "wiki" / "IMPORT-QUEUE.md").read_text(encoding="utf-8")
            payload = json.loads(queue_text.split("```json\n", 1)[1].split("\n```", 1)[0])
            self.assertEqual(len(payload), 1)
            self.assertEqual(first["fingerprint"], second["fingerprint"])

    def test_reimport_reuses_existing_research_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            request = ImportRequest(
                source_type="text",
                source="# OpenClaw\n\nOpenClaw powers the runtime.",
                title="OpenClaw",
            )
            first = importer.import_source(request)
            second = importer.import_source(request)
            research_paths_1 = [path for path in first["page_paths"] if path.startswith("wiki/research/")]
            research_paths_2 = [path for path in second["page_paths"] if path.startswith("wiki/research/")]
            self.assertEqual(research_paths_1, research_paths_2)
            self.assertEqual(len(list((root / "wiki" / "research").glob("*.md"))), 1)

    def test_tracked_lightrag_ingest_uses_curated_paths_only(self) -> None:
        script = (REPO_ROOT / "scripts" / "lightrag-ingest.sh").read_text(encoding="utf-8")
        self.assertIn('upload_dir "/opt/openclaw/workspace"', script)
        self.assertIn('upload_dir "/opt/obsidian-vault/wiki"', script)
        self.assertIn('upload_dir "/opt/obsidian-vault/raw/signals"', script)
        self.assertNotIn('upload_dir "/opt/obsidian-vault/raw"', script)
        self.assertNotIn('upload_dir "/opt/obsidian-vault"', script)

    def test_alias_resolution_maps_openclaw_runtime_to_canonical_entity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            result = importer.import_source(
                ImportRequest(
                    source_type="text",
                    source="# Runtime Notes\n\nThe OpenClaw runtime coordinates memory lookup and gateway routing.",
                    title="OpenClaw runtime",
                )
            )

            self.assertTrue(result["ok"])
            self.assertTrue((root / "wiki" / "entities" / "openclaw.md").exists())
            self.assertFalse((root / "wiki" / "entities" / "openclaw-runtime.md").exists())
            canonical = (root / "wiki" / "entities" / "openclaw.md").read_text(encoding="utf-8")
            self.assertIn("aliases:", canonical)
            self.assertIn("OpenClaw runtime", canonical)

    def test_source_title_artifact_does_not_become_primary_entity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            result = importer.import_source(
                ImportRequest(
                    source_type="text",
                    source="# LightRAG Setup and Operations\n\nLightRAG powers hybrid retrieval for the wiki and is part of operations.",
                    title="LightRAG Setup and Operations",
                )
            )

            self.assertTrue(result["ok"])
            self.assertTrue((root / "wiki" / "entities" / "lightrag.md").exists())
            self.assertFalse((root / "wiki" / "entities" / "lightrag-setup.md").exists())
            research_pages = sorted((root / "wiki" / "research").glob("*.md"))
            self.assertGreaterEqual(len(research_pages), 1)

    def test_topics_map_and_themes_are_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")
            importer.import_source(
                ImportRequest(
                    source_type="text",
                    source="# Signals Bridge\n\nSignals Bridge publishes Telegram alerts and writes raw signal digests.",
                    title="Signals Bridge",
                    import_goal="Document the signal ingestion and routing flow.",
                )
            )

            topics = (root / "wiki" / "TOPICS.md").read_text(encoding="utf-8")
            self.assertIn("## Signals", topics)
            self.assertIn("[[signals-bridge]]", topics)
            entity = (root / "wiki" / "entities" / "signals-bridge.md").read_text(encoding="utf-8")
            self.assertIn("themes:", entity)
            self.assertIn("- signals", entity)

    def test_lint_repair_merges_duplicates_and_rewrites_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scaffold(root)
            (root / "wiki" / "entities" / "openclaw-openclaw.md").write_text(
                "---\ntype: entity\nsubtype: service\nname: OpenClaw OpenClaw\naliases: []\nstatus: active\nconfidence: INFERRED\nhub: false\ntags: [openclaw]\nrelated: []\nupdated: 2026-04-14\n---\n\n# OpenClaw OpenClaw\n\n## What it is\nDuplicate entity page.\n\n## Connections\n- linked from [[openclaw]]\n",
                encoding="utf-8",
            )
            (root / "wiki" / "concepts" / "openclaw.md").write_text(
                "---\ntype: concept\nname: OpenClaw\naliases: []\nconfidence: INFERRED\nhub: false\ntags: [openclaw]\nrelated: []\nupdated: 2026-04-14\n---\n\n# OpenClaw\n\n## Definition\nConcept collision page.\n",
                encoding="utf-8",
            )
            (root / "wiki" / "research" / "openclaw.md").write_text(
                "---\ntype: research\nname: OpenClaw\nconfidence: INFERRED\ntags: [openclaw]\nrelated: []\nupdated: 2026-04-14\n---\n\n# OpenClaw\n\n## Findings\nResearch collision page.\n",
                encoding="utf-8",
            )
            (root / "wiki" / "entities" / "consumer.md").write_text(
                "---\ntype: entity\nsubtype: service\nname: Consumer\naliases: []\nstatus: active\nconfidence: INFERRED\nhub: false\ntags: [consumer]\nrelated: []\nupdated: 2026-04-14\n---\n\n# Consumer\n\n## What it is\nUses [[openclaw]] and [[openclaw-openclaw]].\n",
                encoding="utf-8",
            )
            importer = WikiImporter(obsidian_root=root, state_root=root / "state")

            result = importer.lint(repair=True)

            self.assertTrue(result["ok"])
            self.assertEqual(result["duplicate_basename_count"], 0)
            self.assertTrue((root / "wiki" / "entities" / "openclaw.md").exists())
            self.assertFalse((root / "wiki" / "entities" / "openclaw-openclaw.md").exists())
            self.assertTrue((root / "wiki" / "concepts" / "openclaw-concept.md").exists())
            self.assertTrue((root / "wiki" / "research" / "openclaw-research.md").exists())
            consumer = (root / "wiki" / "entities" / "consumer.md").read_text(encoding="utf-8")
            self.assertIn("[[openclaw]]", consumer)
            self.assertNotIn("[[openclaw-openclaw]]", consumer)


if __name__ == "__main__":
    unittest.main()
