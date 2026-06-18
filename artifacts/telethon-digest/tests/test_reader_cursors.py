import asyncio
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("TELEGRAM_API_ID", "1")
os.environ.setdefault("TELEGRAM_API_HASH", "test-api-hash")

import reader


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
                    {"id": 123, "name": "Test Channel", "broadcast": True},
                ],
            }
        ],
        "read_batch_size": 1,
        "read_batch_delay_sec": 0,
        "lookahead_hours": 4,
    }


class FakeClient:
    def __init__(self) -> None:
        self.regular_min_ids: list[int] = []

    async def get_messages(self, channel_id, **kwargs):
        if "min_id" in kwargs:
            self.regular_min_ids.append(kwargs["min_id"])
        return []


class ReaderCursorTests(unittest.TestCase):
    def test_scheduled_backread_ignores_saved_cursor(self) -> None:
        original_get_cursor = reader.state_store.get_cursor
        client = FakeClient()
        try:
            reader.state_store.get_cursor = lambda channel_id: 777

            asyncio.run(reader.read_all_channels(client, _config(), use_cursors=False))
        finally:
            reader.state_store.get_cursor = original_get_cursor

        self.assertEqual(client.regular_min_ids, [0])

    def test_default_read_uses_saved_cursor(self) -> None:
        original_get_cursor = reader.state_store.get_cursor
        client = FakeClient()
        try:
            reader.state_store.get_cursor = lambda channel_id: 777

            asyncio.run(reader.read_all_channels(client, _config()))
        finally:
            reader.state_store.get_cursor = original_get_cursor

        self.assertEqual(client.regular_min_ids, [777])


if __name__ == "__main__":
    unittest.main()
