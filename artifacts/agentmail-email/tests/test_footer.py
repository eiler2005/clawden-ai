from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("EMAIL_DIGEST_SUPERGROUP_ID", "1")
os.environ.setdefault("EMAIL_DIGEST_TOPIC_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault(
    "aiohttp",
    types.SimpleNamespace(ClientSession=object, ClientTimeout=lambda total: total),
)

from models import ModelMeta, PollPrepResult
from poster import render_poll_batch


class FooterRenderingTests(unittest.TestCase):
    def test_direct_agent_footer_is_human_readable(self) -> None:
        result = PollPrepResult(
            messages_scanned=3,
            threads_considered=2,
            threads_selected=1,
            low_signal_count=0,
            batch_lead=[],
            publish_events=[],
            label_actions={},
            model_meta=ModelMeta(
                model_id="agentmail-direct",
                tier="primary",
                model_label="OpenClaw Agent",
                complexity="standard",
                memory_mode="memory",
            ),
        )

        html = render_poll_batch(
            result,
            window_start=datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 13, 8, 5, tzinfo=timezone.utc),
        )

        self.assertIn("primary (OpenClaw Agent) · standard · memory", html)

    def test_rich_footer_renders_optional_details(self) -> None:
        line = render_poll_batch(
            PollPrepResult(
                messages_scanned=1,
                threads_considered=1,
                threads_selected=1,
                low_signal_count=0,
                batch_lead=[],
                publish_events=[],
                label_actions={},
                model_meta=ModelMeta(
                    model_id="claude-sonnet-4-5",
                    tier="smart",
                    model_label="Claude Sonnet 4.5",
                    provider_fallback=True,
                    score_pct=13,
                    complexity="standard",
                    memory_mode="memory",
                ),
            ),
            window_start=datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 13, 8, 5, tzinfo=timezone.utc),
        )

        self.assertIn("smart (Claude Sonnet 4.5) · fallback · 13% · standard · memory", line)


if __name__ == "__main__":
    unittest.main()
