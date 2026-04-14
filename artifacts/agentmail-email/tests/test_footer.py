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
from poster import render_mailbox_digest, render_poll_batch


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
                model_label="без LLM",
                complexity="template",
                memory_mode="mailbox-window",
            ),
        )

        html = render_poll_batch(
            result,
            window_start=datetime(2026, 4, 13, 8, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 13, 8, 5, tzinfo=timezone.utc),
        )

        self.assertIn("маршрут: прямой рендер · модель: без LLM · сложность: шаблонный обзор · контекст: окно почты", html)

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

        self.assertIn("маршрут: OmniRoute smart · модель: Claude Sonnet 4.5 · резервная модель · контекст: 13% · сложность: обычная · память: включена", line)

    def test_mailbox_digest_renders_compact_message_lines_and_sender_first_highlights(self) -> None:
        html = render_mailbox_digest(
            digest_type="interval",
            window_start=datetime(2026, 4, 14, 10, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 14, 11, 30, tzinfo=timezone.utc),
            messages=[
                {
                    "message_id": "m1",
                    "thread_id": "t1",
                    "timestamp": "2026-04-14T11:26:00+03:00",
                    "subject": "FW: Компания «Синимекс» и Росгосстрах получили премию Finnext за совместный проект",
                    "sender_display": "portal@cinimex.ru",
                    "preview": "От: portal@cinimex.ru\nОтправлено: 14 апреля 2026 г.\nКомпания «Синимекс» и Росгосстрах получили премию Finnext за совместный проект",
                    "has_attachments": True,
                    "attachment_count": 1,
                    "is_low_signal": False,
                },
                {
                    "message_id": "m2",
                    "thread_id": "t2",
                    "timestamp": "2026-04-14T11:17:00+03:00",
                    "subject": "FW: Онлайн-встреча с Генеральным директором Синимекс",
                    "sender_display": "Козко Сергей Петрович",
                    "preview": "От: Козко Сергей Петрович\nОтправлено: 14 апреля 2026 г.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
            ],
            important_messages=[
                {
                    "message_id": "m1",
                    "thread_id": "t1",
                    "timestamp": "2026-04-14T11:26:00+03:00",
                    "subject": "FW: Компания «Синимекс» и Росгосстрах получили премию Finnext за совместный проект",
                    "sender_display": "portal@cinimex.ru",
                    "preview": "От: portal@cinimex.ru\nОтправлено: 14 апреля 2026 г.\nКомпания «Синимекс» и Росгосстрах получили премию Finnext за совместный проект",
                    "has_attachments": True,
                    "attachment_count": 1,
                    "is_low_signal": False,
                }
            ],
            model_meta=ModelMeta(
                model_id="agentmail-direct",
                tier="primary",
                model_label="без LLM",
                complexity="template",
                memory_mode="mailbox-window",
            ),
        )

        self.assertNotIn("<b>От кого</b>", html)
        self.assertIn("• 11:26 — <b>portal@cinimex.ru</b> — Компания «Синимекс» и Росгосстрах получили премию Finnext за совместный проект. Вложения: 1.", html)
        self.assertIn("• 11:26 — <b>portal@cinimex.ru</b> — Компания «Синимекс» и Росгосстрах получили премию Finnext за совместный проект.", html)
        self.assertNotIn("Отправлено:", html)

    def test_mailbox_digest_renders_distilled_important_summaries_with_sender_email(self) -> None:
        html = render_mailbox_digest(
            digest_type="interval",
            window_start=datetime(2026, 4, 14, 14, 30, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 14, 16, 0, tzinfo=timezone.utc),
            messages=[
                {
                    "message_id": "m1",
                    "thread_id": "t1",
                    "timestamp": "2026-04-14T18:31:00+03:00",
                    "subject": "Отпуск Селищев 16-17 апреля",
                    "sender_display": "Дмитрий Селищев",
                    "from_email": "d.selishev@cinimex.ru",
                    "preview": "Коллеги, с 16 апреля на два дня в отпуске, по срочным вопросам на телефоне, изредка смотрю VK Teams.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
                {
                    "message_id": "m2",
                    "thread_id": "t2",
                    "timestamp": "2026-04-14T17:58:00+03:00",
                    "subject": "Updated invitation: Cinimex | Еженедельная встреча @ Weekly from 2pm to 3pm on Tuesday",
                    "sender_display": "Google Calendar от имени Sergei Mazin",
                    "from_email": "sergei.mazin@cinimex.ru",
                    "preview": "Updated invitation: Cinimex | Еженедельная встреча @ Weekly from 2pm to 3pm on Tuesday",
                    "has_attachments": True,
                    "attachment_count": 2,
                    "is_low_signal": False,
                },
            ],
            important_messages=[
                {
                    "message_id": "m1",
                    "thread_id": "t1",
                    "timestamp": "2026-04-14T18:31:00+03:00",
                    "subject": "Отпуск Селищев 16-17 апреля",
                    "sender_display": "Дмитрий Селищев",
                    "from_email": "d.selishev@cinimex.ru",
                    "preview": "Коллеги, с 16 апреля на два дня в отпуске, по срочным вопросам на телефоне, изредка смотрю VK Teams.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
                {
                    "message_id": "m2",
                    "thread_id": "t2",
                    "timestamp": "2026-04-14T17:58:00+03:00",
                    "subject": "Updated invitation: Cinimex | Еженедельная встреча @ Weekly from 2pm to 3pm on Tuesday",
                    "sender_display": "Google Calendar от имени Sergei Mazin",
                    "from_email": "sergei.mazin@cinimex.ru",
                    "preview": "Updated invitation: Cinimex | Еженедельная встреча @ Weekly from 2pm to 3pm on Tuesday",
                    "has_attachments": True,
                    "attachment_count": 2,
                    "is_low_signal": False,
                },
            ],
            model_meta=ModelMeta(
                model_id="agentmail-direct",
                tier="primary",
                model_label="без LLM",
                complexity="template",
                memory_mode="mailbox-window",
            ),
        )

        self.assertIn(
            "• 18:31 — <b>Дмитрий Селищев (d.selishev@cinimex.ru)</b> — Будет в отпуске 16–17 апреля; по срочным вопросам лучше звонить; в VK Teams будет появляться нерегулярно.",
            html,
        )
        self.assertIn(
            "• 17:58 — <b>Google Calendar от имени Sergei Mazin (sergei.mazin@cinimex.ru)</b> — Обновлён или переотправлен инвайт на встречу «Cinimex | Еженедельная встреча».",
            html,
        )


if __name__ == "__main__":
    unittest.main()
