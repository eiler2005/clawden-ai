import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import digest_worker


class ScheduledWindowTests(unittest.TestCase):
    def test_scheduled_period_label_uses_nominal_slot_window(self) -> None:
        previous_hour = os.environ.get("DIGEST_SLOT_HOUR")
        previous_minute = os.environ.get("DIGEST_SLOT_MINUTE")
        os.environ["DIGEST_SLOT_HOUR"] = "11"
        os.environ["DIGEST_SLOT_MINUTE"] = "0"
        try:
            label = digest_worker._scheduled_period_label(
                {"timezone": "Europe/Moscow", "schedule_hours": [8, 11, 14, 17, 21]},
                now=datetime(2026, 4, 22, 8, 5, tzinfo=timezone.utc),
            )
        finally:
            if previous_hour is None:
                os.environ.pop("DIGEST_SLOT_HOUR", None)
            else:
                os.environ["DIGEST_SLOT_HOUR"] = previous_hour
            if previous_minute is None:
                os.environ.pop("DIGEST_SLOT_MINUTE", None)
            else:
                os.environ["DIGEST_SLOT_MINUTE"] = previous_minute

        self.assertEqual(label, "08:00–11:00")

    def test_schedule_slots_support_explicit_minutes(self) -> None:
        slots = digest_worker._schedule_slots(
            {"schedule_slots": ["08:30", "10:00", "11:30", "13:00"]}
        )
        self.assertEqual(slots, [(8, 30), (10, 0), (11, 30), (13, 0)])


if __name__ == "__main__":
    unittest.main()
