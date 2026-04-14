from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("EMAIL_DIGEST_SUPERGROUP_ID", "1")
os.environ.setdefault("EMAIL_DIGEST_TOPIC_ID", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.modules.setdefault(
    "aiohttp",
    types.SimpleNamespace(ClientSession=object, ClientTimeout=lambda total=None: total),
)
docker_errors = types.SimpleNamespace(DockerException=Exception, NotFound=Exception)
sys.modules.setdefault(
    "docker",
    types.SimpleNamespace(from_env=lambda: None, errors=docker_errors),
)
sys.modules.setdefault("docker.errors", docker_errors)

import cron_bridge


def sample_config() -> dict:
    return {
        "topic_name": "inbox-email",
        "resolve_forwarded_sender": False,
        "labels": {
            "polled": "benka/polled",
            "low_signal": "benka/low-signal",
            "digested": "benka/digested",
        },
        "low_signal_hints": ["newsletter", "unsubscribe", "sale", "discount", "promo", "digest"],
    }


def make_thread(thread_id: str, *messages: dict) -> dict:
    return {
        "thread_id": thread_id,
        "subject": messages[0].get("subject", "(no subject)"),
        "messages": list(messages),
    }


class PollPrefilterTests(unittest.TestCase):
    def test_flatten_window_messages_keeps_original_sender_when_forward_lookup_disabled(self) -> None:
        config = sample_config()
        thread_snapshots = [
            {
                "thread_id": "thread-forwarded",
                "subject": "FW: Искусственный интеллект и большие данные",
                "thread_preview": "",
                "received_timestamp": "2026-04-14T09:53:08+00:00",
                "timestamp": "2026-04-14T09:53:08+00:00",
                "messages": [
                    {
                        "message_id": "msg-forwarded-1",
                        "timestamp": "2026-04-14T09:53:08+00:00",
                        "labels": [],
                        "from_raw": "Denis Ermilov <denis.ermilov@cinimex.ru>",
                        "from_name": "Denis Ermilov",
                        "from_email": "denis.ermilov@cinimex.ru",
                        "sender_domain": "cinimex.ru",
                        "subject": "FW: Искусственный интеллект и большие данные",
                        "preview": "",
                        "text_excerpt": (
                            "От: Elena Zabrodina\n"
                            "Отправлено: 14 апреля 2026 г., 12:53:08 (UTC+03:00) Москва, Санкт-Петербург\n"
                            "Кому: Ермилов Денис Игоревич\n"
                            "Тема: Искусственный интеллект и большие данные - секция в рамках CNews Forum 18 июня"
                        ),
                        "has_attachments": False,
                        "attachment_count": 0,
                    }
                ],
            }
        ]

        messages = cron_bridge._flatten_window_messages(thread_snapshots=thread_snapshots, config=config)

        self.assertEqual(messages[0]["sender_display"], "Denis Ermilov")

    def test_flatten_window_messages_uses_forwarded_sender_for_work_email(self) -> None:
        config = sample_config()
        config["topic_name"] = "work-email"
        config["resolve_forwarded_sender"] = True
        thread_snapshots = [
            {
                "thread_id": "thread-forwarded",
                "subject": "FW: Искусственный интеллект и большие данные",
                "thread_preview": "",
                "received_timestamp": "2026-04-14T09:53:08+00:00",
                "timestamp": "2026-04-14T09:53:08+00:00",
                "messages": [
                    {
                        "message_id": "msg-forwarded-1",
                        "timestamp": "2026-04-14T09:53:08+00:00",
                        "labels": [],
                        "from_raw": "Denis Ermilov <denis.ermilov@cinimex.ru>",
                        "from_name": "Denis Ermilov",
                        "from_email": "denis.ermilov@cinimex.ru",
                        "sender_domain": "cinimex.ru",
                        "subject": "FW: Искусственный интеллект и большие данные",
                        "preview": "",
                        "text_excerpt": (
                            "От: Elena Zabrodina\n"
                            "Отправлено: 14 апреля 2026 г., 12:53:08 (UTC+03:00) Москва, Санкт-Петербург\n"
                            "Кому: Ермилов Денис Игоревич\n"
                            "Тема: Искусственный интеллект и большие данные - секция в рамках CNews Forum 18 июня"
                        ),
                        "has_attachments": False,
                        "attachment_count": 0,
                    }
                ],
            }
        ]

        messages = cron_bridge._flatten_window_messages(thread_snapshots=thread_snapshots, config=config)

        self.assertEqual(messages[0]["sender_display"], "Elena Zabrodina")
        self.assertEqual(messages[0]["from_name"], "Elena Zabrodina")
        self.assertEqual(messages[0]["from_email"], "")

    def test_scheduled_digest_window_supports_slot_minutes(self) -> None:
        config = {
            "timezone": "Europe/Moscow",
            "schedule_slots": ["08:30", "10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00"],
        }
        now = cron_bridge.datetime(2026, 4, 13, 13, 7, tzinfo=cron_bridge.timezone.utc)

        start_dt, end_dt = cron_bridge._scheduled_digest_window(now, config=config)

        self.assertEqual(start_dt, cron_bridge.datetime(2026, 4, 13, 11, 30, tzinfo=cron_bridge.timezone.utc))
        self.assertEqual(end_dt, cron_bridge.datetime(2026, 4, 13, 13, 0, tzinfo=cron_bridge.timezone.utc))

    def test_prepare_poll_result_skips_llm_for_obvious_low_signal_thread(self) -> None:
        config = sample_config()
        thread_snapshots = [
            make_thread(
                "thread-low",
                {
                    "message_id": "msg-low-1",
                    "labels": [],
                    "subject": "Weekly newsletter sale",
                    "preview": "unsubscribe discount promo",
                    "text_excerpt": "unsubscribe discount promo",
                    "has_attachments": False,
                    "attachment_count": 0,
                },
            )
        ]

        with patch.object(cron_bridge, "_collect_thread_snapshots", return_value=(1, thread_snapshots)), patch.object(
            cron_bridge,
            "run_agent_json",
            side_effect=AssertionError("LLM should not be called for obvious low-signal window"),
        ):
            result, tail = cron_bridge._prepare_poll_result(
                config=config,
                run_id="run-low",
                inbox_ref="my-inbox@agentmail.to",
                since_dt=cron_bridge.datetime(2026, 4, 13, 8, 0, tzinfo=cron_bridge.timezone.utc),
                until_dt=cron_bridge.datetime(2026, 4, 13, 8, 5, tzinfo=cron_bridge.timezone.utc),
                mode="poll",
            )

        self.assertEqual(result.messages_scanned, 1)
        self.assertEqual(result.threads_considered, 1)
        self.assertEqual(result.low_signal_count, 1)
        self.assertEqual(result.label_actions["benka/low-signal"], ["msg-low-1"])
        self.assertTrue(any("llm_skipped=true" in line for line in tail))

    def test_prepare_poll_result_passes_only_candidate_threads_to_llm(self) -> None:
        config = sample_config()
        low_signal_thread = make_thread(
            "thread-low",
            {
                "message_id": "msg-low-1",
                "labels": [],
                "subject": "Digest sale",
                "preview": "unsubscribe promo",
                "text_excerpt": "newsletter promo unsubscribe",
                "has_attachments": False,
                "attachment_count": 0,
            },
        )
        candidate_thread = make_thread(
            "thread-action",
            {
                "message_id": "msg-action-1",
                "labels": [],
                "subject": "Project update",
                "preview": "please reply before tomorrow",
                "text_excerpt": "please reply before tomorrow",
                "has_attachments": False,
                "attachment_count": 0,
            },
        )
        captured_prompt: dict[str, str] = {}

        def fake_run_agent_json(prompt: str):
            captured_prompt["prompt"] = prompt
            return types.SimpleNamespace(
                payload={
                    "ok": True,
                    "messages_scanned": 1,
                    "threads_considered": 1,
                    "threads_selected": 1,
                    "low_signal_count": 0,
                    "batch_lead": [],
                    "publish_events": [],
                    "label_actions": {},
                    "model_meta": {"model_id": "openclaw", "tier": "primary"},
                },
                output_tail=["llm-called"],
                agent_id="main",
            )

        with patch.object(cron_bridge, "_collect_thread_snapshots", return_value=(2, [low_signal_thread, candidate_thread])), patch.object(
            cron_bridge,
            "run_agent_json",
            side_effect=fake_run_agent_json,
        ):
            result, tail = cron_bridge._prepare_poll_result(
                config=config,
                run_id="run-mixed",
                inbox_ref="my-inbox@agentmail.to",
                since_dt=cron_bridge.datetime(2026, 4, 13, 8, 0, tzinfo=cron_bridge.timezone.utc),
                until_dt=cron_bridge.datetime(2026, 4, 13, 8, 5, tzinfo=cron_bridge.timezone.utc),
                mode="poll",
            )

        self.assertIn("thread-action", captured_prompt["prompt"])
        self.assertNotIn("thread-low", captured_prompt["prompt"])
        self.assertEqual(result.low_signal_count, 1)
        self.assertEqual(result.label_actions["benka/low-signal"], ["msg-low-1"])
        self.assertTrue(any("candidate_threads=1" in line for line in tail))
        self.assertTrue(any("llm_skipped=false" in line for line in tail))


if __name__ == "__main__":
    unittest.main()
