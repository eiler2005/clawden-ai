import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("DIGEST_SUPERGROUP_ID", "1")
os.environ.setdefault("DIGEST_TOPIC_ID", "1")

import poster
from models import DigestDocument, DigestItem, DigestSection, DigestStats, ModelMeta


class PosterLinkTests(unittest.TestCase):
    def test_lead_gets_source_link_from_matching_section_item(self) -> None:
        document = DigestDocument(
            digest_type="interval",
            title="Дайджест",
            period_label="08:00–11:00",
            lead=[
                "AI-инфраструктура снова сдвинулась к практическому продакшену: Foundry и агенты выходят в рабочий контур."
            ],
            new_glance=[],
            must_read=[],
            sections=[
                DigestSection(
                    folder="news",
                    tier="A",
                    folder_link=None,
                    items=[
                        DigestItem(
                            channel="AI Channel",
                            channel_url=None,
                            post_url="https://t.me/c/100/10",
                            summary="Foundry и агентные инструменты переходят в практический production-контур.",
                            kind="signal",
                        )
                    ],
                )
            ],
            low_signal=[],
            stats=DigestStats(channels_in_scope=1, new_posts_seen=1, posts_selected=1),
            model_meta=ModelMeta(model_id="gpt-5.5", tier="medium"),
        )

        html = poster.render_digest_html(document)

        lead_block = html.split("🗂 <b>Папки</b>", 1)[0]
        self.assertIn('<a href="https://t.me/c/100/10">→</a>', lead_block)


if __name__ == "__main__":
    unittest.main()
