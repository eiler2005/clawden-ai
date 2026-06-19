import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cron_bridge


class FakeRedis:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.deleted = []

    def get(self, key: str) -> str:
        return self.run_id

    def delete(self, key: str) -> None:
        self.deleted.append(key)


class CronBridgeStatusTests(unittest.TestCase):
    def test_recover_interrupted_status_marks_stale_run_and_releases_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_state_dir = cron_bridge.STATE_DIR
            original_status_path = cron_bridge.STATUS_PATH
            original_redis_url = cron_bridge.REDIS_URL
            original_make_redis = cron_bridge._make_redis
            fake_redis = FakeRedis("run-1")
            try:
                cron_bridge.STATE_DIR = Path(tmp)
                cron_bridge.STATUS_PATH = Path(tmp) / "cron-bridge-status.json"
                cron_bridge.REDIS_URL = "redis://test"
                cron_bridge._make_redis = lambda: fake_redis
                cron_bridge._write_status(
                    {
                        "ok": True,
                        "running": True,
                        "run_id": "run-1",
                        "digest_type": "morning",
                        "started_at": "2026-06-19T05:00:02+00:00",
                        "finished_at": None,
                        "exit_code": None,
                        "tail": [],
                    }
                )

                cron_bridge._recover_interrupted_status()

                status = json.loads(cron_bridge.STATUS_PATH.read_text(encoding="utf-8"))
                self.assertFalse(status["ok"])
                self.assertFalse(status["running"])
                self.assertTrue(status["interrupted"])
                self.assertEqual(status["exit_code"], 130)
                self.assertEqual(status["error"], "bridge_restarted_while_pipeline_running")
                self.assertIn("bridge restarted", status["tail"][-1])
                self.assertEqual(fake_redis.deleted, [cron_bridge.DIGEST_LOCK_KEY])
            finally:
                cron_bridge.STATE_DIR = original_state_dir
                cron_bridge.STATUS_PATH = original_status_path
                cron_bridge.REDIS_URL = original_redis_url
                cron_bridge._make_redis = original_make_redis


if __name__ == "__main__":
    unittest.main()
