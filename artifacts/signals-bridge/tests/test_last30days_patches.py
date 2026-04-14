from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / "last30days_patches"
sys.path.insert(0, str(PATCH_DIR))

from patch_last30days_skill import patch_skill
import reddit_hybrid


PIPELINE_TEMPLATE = """from . import (
    planner,
    reddit,
    reddit_public,
    rerank,
)

def handler():
    if source == "reddit":
        # Use raw_topic so expand_reddit_queries() generates diverse variants
        # from the original user topic, not the planner's narrowed search_query.
        reddit_query = raw_topic or subquery.search_query
        # Public Reddit first (free, gets comments); SC as backup
        try:
            public_results = reddit_public.search_reddit_public(
                reddit_query, from_date, to_date, depth=depth,
                subreddits=subreddits,
            )
            if public_results:
                return public_results, {}
        except Exception as exc:
            sys.stderr.write(
                f"[Reddit] Public search failed ({type(exc).__name__}: {exc})"
            )
            if not config.get("SCRAPECREATORS_API_KEY"):
                sys.stderr.write("\\n")
                return [], {}
            sys.stderr.write(", using ScrapeCreators backup\\n")
        # Fallback to ScrapeCreators if public returned empty or raised
        if config.get("SCRAPECREATORS_API_KEY"):
            try:
                result = reddit.search_and_enrich(
                    reddit_query,
                    from_date,
                    to_date,
                    depth=depth,
                    token=config.get("SCRAPECREATORS_API_KEY"),
                    subreddits=subreddits,
                )
                return reddit.parse_reddit_response(result), {}
            except Exception as exc:
                sys.stderr.write(
                    f"[Reddit] ScrapeCreators backup also failed "
                    f"({type(exc).__name__}: {exc})\\n"
                )
        return [], {}
"""


class PatchSkillTests(unittest.TestCase):
    def test_patch_skill_injects_hybrid_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lib_dir = root / "scripts" / "lib"
            lib_dir.mkdir(parents=True)
            (lib_dir / "pipeline.py").write_text(PIPELINE_TEMPLATE, encoding="utf-8")

            patch_skill(root)

            pipeline = (lib_dir / "pipeline.py").read_text(encoding="utf-8")
            self.assertIn("reddit_hybrid", pipeline)
            self.assertIn("search_reddit_hybrid", pipeline)
            self.assertTrue((lib_dir / "reddit_hybrid.py").exists())


class RedditHybridTests(unittest.TestCase):
    def test_search_uses_json_when_available(self) -> None:
        with patch.object(reddit_hybrid, "_search_json", return_value=[{"url": "https://www.reddit.com/r/test/comments/1", "date": "2026-04-10", "engagement": {"score": 10, "num_comments": 2}, "metadata": {"retrieval_transport": "json"}}]), patch.object(reddit_hybrid, "_search_rss", return_value=[]), patch.object(reddit_hybrid, "_enrich_posts", side_effect=lambda posts, depth="default": posts):
            results = reddit_hybrid.search_reddit_hybrid("topic", "2026-04-01", "2026-04-30")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["retrieval_transport"], "json")

    def test_search_falls_back_to_rss(self) -> None:
        rss_post = {
            "url": "https://www.reddit.com/r/test/comments/1",
            "date": "2026-04-10",
            "engagement": {"score": 0, "num_comments": 0},
            "metadata": {"retrieval_transport": "rss"},
        }
        with patch.object(reddit_hybrid, "_search_json", return_value=[]), patch.object(reddit_hybrid, "_search_rss", return_value=[rss_post]), patch.object(reddit_hybrid, "_enrich_posts", side_effect=lambda posts, depth="default": posts):
            results = reddit_hybrid.search_reddit_hybrid("topic", "2026-04-01", "2026-04-30")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["retrieval_transport"], "rss")

    def test_comments_rss_enrichment_preserves_best_effort(self) -> None:
        feed = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>t3_abc</id>
    <title>Thread title</title>
    <link href="https://www.reddit.com/r/test/comments/abc/thread/" />
    <content type="html">&lt;p&gt;Thread body&lt;/p&gt;</content>
    <updated>2026-04-10T12:00:00+00:00</updated>
  </entry>
  <entry>
    <id>t1_c1</id>
    <title>/u/alice on Thread title</title>
    <link href="https://www.reddit.com/r/test/comments/abc/thread/c1/" />
    <author><name>/u/alice</name></author>
    <content type="html">&lt;p&gt;This is a useful comment with enough substance to keep.&lt;/p&gt;</content>
    <updated>2026-04-10T12:10:00+00:00</updated>
  </entry>
</feed>"""
        item = {
            "url": "https://www.reddit.com/r/test/comments/abc/thread/",
            "metadata": {"retrieval_transport": "rss"},
        }
        with patch.object(reddit_hybrid, "_curl_fetch", return_value=(200, "application/atom+xml", feed)):
            enriched = reddit_hybrid._enrich_post(item)
        self.assertIn("top_comments", enriched)
        self.assertEqual(enriched["metadata"]["comment_transport"], "rss")
        self.assertEqual(enriched["top_comments"][0]["author"], "/u/alice")
