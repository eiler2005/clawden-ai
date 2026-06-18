import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TELEGRAM_API_ID", "1")
os.environ.setdefault("TELEGRAM_API_HASH", "test-api-hash")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("DIGEST_SUPERGROUP_ID", "1")
os.environ.setdefault("DIGEST_TOPIC_ID", "1")

import digest_worker
from models import Post


class FakeClient:
    async def connect(self) -> None:
        return None

    async def is_user_authorized(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = datetime(2026, 6, 18, 8, 5, tzinfo=timezone.utc)
        return current if tz is None else current.astimezone(tz)


def _config() -> dict:
    return {
        "read_only": True,
        "require_explicit_allowlist": True,
        "read_broadcast_channels_only": True,
        "allowed_folder_names": ["news"],
        "folders": [
            {
                "name": "news",
                "priority": 5,
                "channels": [
                    {"id": 1, "name": "A", "broadcast": True},
                    {"id": 2, "name": "B", "broadcast": True},
                    {"id": 3, "name": "C", "broadcast": True},
                ],
            }
        ],
        "timezone": "Europe/Moscow",
        "schedule_hours": [8, 11, 14, 17, 21],
        "digest_types": {"11": "interval"},
        "lookahead_hours": 4,
    }


class DigestWorkerStatsTests(unittest.TestCase):
    def test_scheduled_stats_count_only_channels_active_in_period(self) -> None:
        captured: dict = {}
        posts = [
            Post(1, "A", "news", 5, 10, "inside A", datetime(2026, 6, 18, 7, 30, tzinfo=timezone.utc)),
            Post(2, "B", "news", 5, 20, "inside B", datetime(2026, 6, 18, 5, 30, tzinfo=timezone.utc)),
            Post(3, "C", "news", 5, 30, "outside C", datetime(2026, 6, 18, 8, 30, tzinfo=timezone.utc)),
        ]

        original_env = {
            "DIGEST_SLOT_HOUR": os.environ.get("DIGEST_SLOT_HOUR"),
            "DIGEST_SLOT_MINUTE": os.environ.get("DIGEST_SLOT_MINUTE"),
            "DIGEST_TYPE_OVERRIDE": os.environ.get("DIGEST_TYPE_OVERRIDE"),
        }
        originals = {
            "datetime": digest_worker.datetime,
            "build_client": digest_worker.build_client,
            "read_all_channels": digest_worker.read_all_channels,
            "score_posts": digest_worker.score_posts,
            "deduplicate_posts": digest_worker.deduplicate_posts,
            "attach_links": digest_worker.attach_links,
            "summarize": digest_worker.summarize,
            "post_digest": digest_worker.post_digest,
            "persist_digest": digest_worker.persist_digest,
            "update_cursors": digest_worker.update_cursors,
            "set_last_run": digest_worker.state_store.set_last_run,
        }

        async def fake_read_all_channels(client, config, *, use_cursors=True):
            captured["use_cursors"] = use_cursors
            return posts

        async def fake_deduplicate_posts(selected_posts, config):
            return list(selected_posts)

        async def fake_summarize(selected_posts, *, stats, **kwargs):
            captured["stats"] = stats
            captured["selected_posts"] = list(selected_posts)
            return object()

        async def fake_post_digest(document):
            return True

        async def fake_persist_digest(*args, **kwargs):
            return None

        try:
            os.environ["DIGEST_SLOT_HOUR"] = "11"
            os.environ["DIGEST_SLOT_MINUTE"] = "0"
            os.environ.pop("DIGEST_TYPE_OVERRIDE", None)
            digest_worker.datetime = FixedDateTime
            digest_worker.build_client = lambda: FakeClient()
            digest_worker.read_all_channels = fake_read_all_channels
            digest_worker.score_posts = lambda selected_posts, config: list(selected_posts)
            digest_worker.deduplicate_posts = fake_deduplicate_posts
            digest_worker.attach_links = lambda selected_posts: None
            digest_worker.summarize = fake_summarize
            digest_worker.post_digest = fake_post_digest
            digest_worker.persist_digest = fake_persist_digest
            digest_worker.update_cursors = lambda selected_posts: captured.setdefault(
                "cursor_channels",
                [post.channel_id for post in selected_posts],
            )
            digest_worker.state_store.set_last_run = lambda *args, **kwargs: None

            asyncio.run(digest_worker.run_digest(_config()))
        finally:
            for key, value in originals.items():
                if key == "set_last_run":
                    digest_worker.state_store.set_last_run = value
                else:
                    setattr(digest_worker, key, value)
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        stats = captured["stats"]
        self.assertFalse(captured["use_cursors"])
        self.assertEqual(stats.active_channels_seen, 2)
        self.assertEqual(stats.new_posts_seen, 2)
        self.assertEqual(stats.channels_in_scope, 3)
        self.assertEqual(captured["cursor_channels"], [1, 2])


if __name__ == "__main__":
    unittest.main()
