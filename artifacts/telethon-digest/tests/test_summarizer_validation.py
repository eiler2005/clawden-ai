import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import summarizer
from models import DigestStats, ModelMeta, Post


class SummarizerValidationTests(unittest.TestCase):
    def test_markdown_fenced_json_is_not_treated_as_retry_marker(self) -> None:
        raw = '```json\n{"title": "Digest", "lead": ["ok"]}\n```'

        self.assertFalse(summarizer._has_retry_markers(raw))

    def test_clarification_response_is_retry_marker(self) -> None:
        self.assertTrue(
            summarizer._has_retry_markers("Мне нужна дополнительная информация.")
        )

    def test_missing_llm_post_url_is_repaired_from_matching_channel(self) -> None:
        posts = [
            Post(
                channel_id=1,
                channel_name="AI Channel",
                folder_name="AI",
                folder_priority=1,
                msg_id=10,
                text="Model routing update",
                date=datetime(2026, 5, 29, tzinfo=timezone.utc),
                url="https://t.me/c/100/10",
                channel_url="https://t.me/example",
                score=9.0,
            )
        ]
        payload = {
            "title": "Digest",
            "period_label": "08:00-11:00",
            "lead": ["AI Channel дал полезный апдейт."],
            "new_glance": [],
            "must_read": [
                {
                    "channel": "AI Channel",
                    "channel_url": "https://t.me/example",
                    "post_url": "",
                    "extra_post_urls": [],
                    "summary": "Стоит открыть апдейт по маршрутизации моделей.",
                    "kind": "signal",
                    "pinned": False,
                    "also_mentioned": [],
                }
            ],
            "sections": [],
            "low_signal": [],
            "model_meta": {},
            "themes": ["AI - апдейт по маршрутизации моделей"],
            "quiet_folders": [],
        }

        document = summarizer._validate_document_payload(
            payload,
            digest_type="interval",
            period_label="08:00-11:00",
            stats=DigestStats(channels_in_scope=1, new_posts_seen=1, posts_selected=1),
            model_meta=ModelMeta(model_id="gpt-5.5", tier="medium"),
            config={},
            posts=posts,
        )

        self.assertEqual(document.must_read[0].post_url, "https://t.me/c/100/10")


if __name__ == "__main__":
    unittest.main()
