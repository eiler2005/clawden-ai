import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import Post
from scorer import score_posts


BASE_TIME = datetime(2026, 6, 23, 9, 0, tzinfo=timezone.utc)


def _config(top_n: int) -> dict:
    return {
        "min_score": 1,
        "top_posts_for_llm": top_n,
        "pin_boost": 0,
        "channel_position_boost": {
            "top_1_4": 0,
            "top_5_8": 0,
            "top_9_12": 0,
            "other": 0,
        },
        "folder_tiers": {
            "A": {"folders": ["news", "work"], "priority": 5},
            "C": {"priority": 1},
        },
    }


def _post(idx: int, folder: str, channel_id: int) -> Post:
    return Post(
        channel_id=channel_id,
        channel_name=f"{folder}-{channel_id}",
        folder_name=folder,
        folder_priority=5,
        msg_id=idx,
        text=f"AI market signal {idx}",
        date=BASE_TIME + timedelta(minutes=idx),
        channel_position=20,
    )


class ScorerContentMixTests(unittest.TestCase):
    def test_news_is_capped_when_other_folders_have_enough_candidates(self) -> None:
        posts = [
            *[_post(idx, "news", 1000 + idx) for idx in range(70)],
            *[_post(idx + 100, "work", 2000 + idx) for idx in range(70)],
        ]

        selected = score_posts(posts, _config(top_n=42))
        news_count = sum(1 for post in selected if post.folder_name == "news")

        self.assertEqual(len(selected), 42)
        self.assertLessEqual(news_count, int(42 * 0.35))

    def test_news_expands_when_other_folders_are_scarce(self) -> None:
        posts = [
            *[_post(idx, "news", 1000 + idx) for idx in range(25)],
            *[_post(idx + 100, "work", 2000 + idx) for idx in range(4)],
        ]

        selected = score_posts(posts, _config(top_n=12))
        news_count = sum(1 for post in selected if post.folder_name == "news")

        self.assertEqual(len(selected), 12)
        self.assertEqual(news_count, 8)
        self.assertGreater(news_count, int(12 * 0.35))


if __name__ == "__main__":
    unittest.main()
