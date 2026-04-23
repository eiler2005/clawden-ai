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
        self.assertIn("• Сюжетов: <b>2</b>", html)
        self.assertIn("<b>Сюжеты</b>", html)
        self.assertIn("<b>Что важного</b>", html)
        self.assertNotIn("<b>Нужно реагировать</b>", html)
        self.assertNotIn("<b>Для информации</b>", html)
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

    def test_mailbox_digest_normalizes_calendar_sender_spacing_and_compacts_calendar_lines(self) -> None:
        html = render_mailbox_digest(
            digest_type="interval",
            window_start=datetime(2026, 4, 15, 7, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 15, 8, 30, tzinfo=timezone.utc),
            messages=[
                {
                    "message_id": "m3",
                    "thread_id": "t3",
                    "timestamp": "2026-04-15T10:24:00+03:00",
                    "subject": "Updated invitation: Синимекс | Ариэль Инокс @ Wed Apr 15, 2026 5pm - 5:45pm (GMT+5) (denis.ermilov@cinimex.ru)",
                    "sender_display": "Google CalendarОт имениDenis Ermilov",
                    "from_email": "denis.ermilov@cinimex.ru",
                    "preview": "Updated invitation: Синимекс | Ариэль Инокс @ Wed Apr 15, 2026 5pm - 5:45pm (GMT+5) (denis.ermilov@cinimex.ru). Когда: 15 апреля 2026 г. 15:00-15:45.",
                    "has_attachments": True,
                    "attachment_count": 2,
                    "is_low_signal": False,
                }
            ],
            important_messages=[
                {
                    "message_id": "m3",
                    "thread_id": "t3",
                    "timestamp": "2026-04-15T10:24:00+03:00",
                    "subject": "Updated invitation: Синимекс | Ариэль Инокс @ Wed Apr 15, 2026 5pm - 5:45pm (GMT+5) (denis.ermilov@cinimex.ru)",
                    "sender_display": "Google CalendarОт имениDenis Ermilov",
                    "from_email": "denis.ermilov@cinimex.ru",
                    "preview": "Updated invitation: Синимекс | Ариэль Инокс @ Wed Apr 15, 2026 5pm - 5:45pm (GMT+5) (denis.ermilov@cinimex.ru). Когда: 15 апреля 2026 г. 15:00-15:45.",
                    "has_attachments": True,
                    "attachment_count": 2,
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

        self.assertIn(
            "• 10:24 — <b>Google Calendar от имени Denis Ermilov</b> — Обновлён инвайт на встречу «Синимекс | Ариэль Инокс». Вложения: 2.",
            html,
        )
        self.assertIn(
            "• 10:24 — <b>Google Calendar от имени Denis Ermilov (denis.ermilov@cinimex.ru)</b> — Обновлён или переотправлен инвайт на встречу «Синимекс | Ариэль Инокс».",
            html,
        )

    def test_mailbox_digest_turns_resource_requests_into_clear_plot(self) -> None:
        html = render_mailbox_digest(
            digest_type="interval",
            window_start=datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 17, 11, 30, tzinfo=timezone.utc),
            messages=[
                {
                    "message_id": "m4",
                    "thread_id": "t4",
                    "timestamp": "2026-04-17T14:15:00+03:00",
                    "subject": "ресурсы для ПР-2952",
                    "sender_display": "Литус Татьяна Юрьевна",
                    "preview": "Копия: Полевиков Сергей Геннадьевич; sotnikov; vf@vtb. Коллеги, добрый день. Денис, нам срочно требуется аналитик на ПР-2952. Во вложении детали.",
                    "has_attachments": True,
                    "attachment_count": 1,
                    "is_low_signal": False,
                }
            ],
            important_messages=[
                {
                    "message_id": "m4",
                    "thread_id": "t4",
                    "timestamp": "2026-04-17T14:15:00+03:00",
                    "subject": "ресурсы для ПР-2952",
                    "sender_display": "Литус Татьяна Юрьевна",
                    "preview": "Копия: Полевиков Сергей Геннадьевич; sotnikov; vf@vtb. Коллеги, добрый день. Денис, нам срочно требуется аналитик на ПР-2952. Во вложении детали.",
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

        self.assertIn(
            "• 14:15 — <b>Литус Татьяна Юрьевна</b> — Запрос на усиление команды по ПР-2952: требуется аналитик. Вложения: 1.",
            html,
        )
        self.assertIn(
            "• 14:15 — <b>Литус Татьяна Юрьевна</b> — Запрос на усиление команды по ПР-2952: требуется аналитик.",
            html,
        )
        self.assertNotIn("Копия:", html)

    def test_work_email_digest_adds_next_step_to_actionable_stories(self) -> None:
        html = render_mailbox_digest(
            digest_type="interval",
            window_start=datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 17, 11, 30, tzinfo=timezone.utc),
            messages=[
                {
                    "message_id": "m8",
                    "thread_id": "t8",
                    "timestamp": "2026-04-17T14:15:00+03:00",
                    "subject": "ресурсы для ПР-2952",
                    "sender_display": "Литус Татьяна Юрьевна",
                    "preview": "Коллеги, добрый день. Денис, нам срочно требуется аналитик на ПР-2952. Во вложении детали.",
                    "has_attachments": True,
                    "attachment_count": 1,
                    "is_low_signal": False,
                },
                {
                    "message_id": "m9",
                    "thread_id": "t9",
                    "timestamp": "2026-04-17T14:05:00+03:00",
                    "subject": "BI есть, ясности нет: что сломано между отчетом и решением",
                    "sender_display": "Points Lab",
                    "preview": "BI собрали, но неясно, где разрыв между отчетом и решением. Нужен разбор по проблеме.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
            ],
            important_messages=[],
            topic_name="work-email",
            model_meta=ModelMeta(
                model_id="agentmail-direct",
                tier="primary",
                model_label="без LLM",
                complexity="template",
                memory_mode="mailbox-window",
            ),
        )

        self.assertIn("<b>Нужно реагировать</b>", html)
        self.assertIn("<b>Для информации</b>", html)
        self.assertNotIn("<b>Что важного</b>", html)
        self.assertIn(
            "• 14:15 — <b>Литус Татьяна Юрьевна</b> — Запрос на усиление команды по ПР-2952: требуется аналитик; нужно быстро ответить, кого можно выделить или как закрыть запрос. Вложения: 1.",
            html,
        )
        self.assertIn(
            "• 14:15 — <b>Литус Татьяна Юрьевна</b> — Запрос на усиление команды по ПР-2952: требуется аналитик; нужно быстро ответить, кого можно выделить или как закрыть запрос.",
            html,
        )
        self.assertIn(
            "• 14:05 — <b>Points Lab</b> — BI есть, ясности нет: что сломано между отчетом и решением; нужно уточнить, что именно сломано и где разрыв.",
            html,
        )
        self.assertIn(
            "• Отдельных информационных писем без реакции в этом окне не вижу.",
            html,
        )

    def test_work_email_digest_renders_informational_stories_in_separate_section(self) -> None:
        html = render_mailbox_digest(
            digest_type="interval",
            window_start=datetime(2026, 4, 18, 7, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 18, 8, 30, tzinfo=timezone.utc),
            messages=[
                {
                    "message_id": "m10",
                    "thread_id": "t10",
                    "timestamp": "2026-04-18T11:15:00+03:00",
                    "subject": "ресурсы для ПР-3010",
                    "sender_display": "Пышкин Алексей Александрович",
                    "preview": "Коллеги, нужен разработчик на ПР-3010 до конца недели.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
                {
                    "message_id": "m11",
                    "thread_id": "t11",
                    "timestamp": "2026-04-18T10:52:00+03:00",
                    "subject": "Отпуск Селищев 21-22 апреля",
                    "sender_display": "Дмитрий Селищев",
                    "from_email": "d.selishev@cinimex.ru",
                    "preview": "Коллеги, с 21 апреля на два дня в отпуске, по срочным вопросам на телефоне.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
            ],
            important_messages=[],
            topic_name="work-email",
            model_meta=ModelMeta(
                model_id="agentmail-direct",
                tier="primary",
                model_label="без LLM",
                complexity="template",
                memory_mode="mailbox-window",
            ),
        )

        self.assertIn("<b>Нужно реагировать</b>", html)
        self.assertIn("<b>Для информации</b>", html)
        self.assertIn(
            "• 11:15 — <b>Пышкин Алексей Александрович</b> — Запрос на усиление команды по ПР-3010: требуется разработчик; нужно ответить, кого можно выделить или как закрыть запрос.",
            html,
        )
        self.assertIn(
            "• 10:52 — <b>Дмитрий Селищев (d.selishev@cinimex.ru)</b> — Будет в отпуске 21–22 апреля; по срочным вопросам лучше звонить; нужно учесть отсутствие в планировании и срочных коммуникациях.",
            html,
        )
        react_section = html.split("<b>Нужно реагировать</b>", 1)[1].split("<b>Для информации</b>", 1)[0]
        info_section = html.split("<b>Для информации</b>", 1)[1]
        self.assertIn(
            "• 11:15 — <b>Пышкин Алексей Александрович</b> — Запрос на усиление команды по ПР-3010: требуется разработчик; нужно ответить, кого можно выделить или как закрыть запрос.",
            react_section,
        )
        self.assertIn(
            "• 10:52 — <b>Дмитрий Селищев (d.selishev@cinimex.ru)</b> — Будет в отпуске 21–22 апреля; по срочным вопросам лучше звонить; нужно учесть отсутствие в планировании и срочных коммуникациях.",
            info_section,
        )

    def test_mailbox_digest_collapses_repeated_threads_into_one_story(self) -> None:
        html = render_mailbox_digest(
            digest_type="interval",
            window_start=datetime(2026, 4, 22, 13, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 4, 22, 14, 30, tzinfo=timezone.utc),
            messages=[
                {
                    "message_id": "m5",
                    "thread_id": "t5",
                    "timestamp": "2026-04-22T17:17:00+03:00",
                    "subject": "ВТБ - СМХ. Заявка консультации.",
                    "sender_display": "Шевченко Галина",
                    "preview": "Денис, акт юристы уже не смотрят, поэтому можно двигаться дальше.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
                {
                    "message_id": "m6",
                    "thread_id": "t6",
                    "timestamp": "2026-04-22T16:48:00+03:00",
                    "subject": "Re: ВТБ - СМХ. Заявка консультации.",
                    "sender_display": "Шевченко Галина",
                    "preview": "Кому: Концесвитная Мария Александровна. Денис, акт юристы уже не смотрят, поэтому можно двигаться дальше.",
                    "has_attachments": False,
                    "attachment_count": 0,
                    "is_low_signal": False,
                },
                {
                    "message_id": "m7",
                    "thread_id": "t7",
                    "timestamp": "2026-04-22T16:26:00+03:00",
                    "subject": "ВТБ - СМХ. Заявка консультации.",
                    "sender_display": "Концесвитная Мария Александровна",
                    "preview": "От: Концесвитная Мария Александровна. Тема: ВТБ - СМХ. Заявка консультации.",
                    "has_attachments": True,
                    "attachment_count": 1,
                    "is_low_signal": False,
                },
            ],
            important_messages=[],
            model_meta=ModelMeta(
                model_id="agentmail-direct",
                tier="primary",
                model_label="без LLM",
                complexity="template",
                memory_mode="mailbox-window",
            ),
        )

        self.assertIn("• Сюжетов: <b>1</b>", html)
        self.assertEqual(html.count("ВТБ - СМХ. Заявка консультации"), 1)
        self.assertIn(
            "• 17:17 — <b>Шевченко Галина</b> — ВТБ - СМХ. Заявка консультации: акт юристы уже не смотрят, поэтому можно двигаться дальше. Вложения: 1. В окне: ещё 2 похожих письма.",
            html,
        )
        self.assertIn(
            "• 17:17 — <b>Шевченко Галина</b> — Акт юристы уже не смотрят, поэтому можно двигаться дальше. В окне: ещё 2 похожих письма.",
            html,
        )


if __name__ == "__main__":
    unittest.main()
