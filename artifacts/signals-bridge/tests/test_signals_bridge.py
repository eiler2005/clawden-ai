from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config_store import normalize_config, validate_config
from event_store import append_events, append_new_events
from last30days_runner import build_digest
from matching import build_telegram_message_link, extract_tradingview_username, keyword_matches, local_event_from_candidate, match_email_rule, match_telegram_rule
from models import SignalEvent
from omniroute_client import _local_fallback_batch
from telegram_adapter import resolve_telegram_window


class FakeRedis:
    def __init__(self) -> None:
        self.kv = {}
        self.stream = []

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.kv:
            return False
        self.kv[key] = value
        return True

    def xadd(self, name, fields):
        self.stream.append((name, fields))
        return f"{len(self.stream)}-0"

    def xrange(self, name, min="-", max="+", count=200):
        return []

    def xdel(self, name, *ids):
        return len(ids)


def sample_config() -> dict:
    return {
        "timezone": "Europe/Moscow",
        "scheduler": {"tick_seconds": 300, "cleanup_interval_seconds": 3600},
        "default_poll_interval_seconds": 300,
        "event_retention_days": 14,
        "delivery": {"topic_name": "signals", "mode": "mini_batch"},
        "sources": {
            "email": [
                {"id": "email-tradingview", "kind": "email", "enabled": True, "inbox_ref": "test@example.com"}
            ],
            "telegram": [
                {"id": "telegram-trader-speki", "kind": "telegram", "enabled": True, "chat_id": -1001, "chat_name": "Трейдер"}
            ],
            "web": [],
        },
        "rule_sets": [
            {
                "id": "trading",
                "title": "Trading",
                "enabled": True,
                "poll_interval_seconds": 300,
                "rules": [
                    {
                        "id": "market-alert-user",
                        "source_type": "email",
                        "source_id": "email-tradingview",
                        "enabled": True,
                        "kind": "tradingview_user",
                        "from_email": "noreply@tradingview.com",
                        "tradingview_usernames": ["AnalystA"],
                    },
                    {
                        "id": "telegram-si",
                        "source_type": "telegram",
                        "source_id": "telegram-trader-speki",
                        "enabled": True,
                        "kind": "hashtag",
                        "hashtags": ["#si"],
                    },
                ],
            }
        ],
    }


class ConfigValidationTests(unittest.TestCase):
    def test_invalid_source_kind_raises(self) -> None:
        config = sample_config()
        config["sources"]["email"][0]["kind"] = "imap"
        with self.assertRaisesRegex(ValueError, "invalid source kind"):
            validate_config(config)

    def test_rule_without_source_ref_raises(self) -> None:
        config = sample_config()
        config["rule_sets"][0]["rules"][0]["source_id"] = ""
        with self.assertRaisesRegex(ValueError, "missing source ref"):
            validate_config(config)

    def test_telegram_rule_without_stable_ids_raises(self) -> None:
        config = sample_config()
        config["sources"]["telegram"][0]["chat_id"] = ""
        with self.assertRaisesRegex(ValueError, "missing chat_id"):
            validate_config(config)

    def test_normalize_sets_five_minute_scheduler_default(self) -> None:
        config = sample_config()
        del config["scheduler"]["tick_seconds"]
        normalized = normalize_config(config)
        self.assertEqual(normalized["scheduler"]["tick_seconds"], 300)

    def test_external_rule_files_are_merged(self) -> None:
        config = sample_config()
        config["rule_sets"] = []
        config["rule_files"] = ["rules/*.json"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rules_dir = base / "rules"
            rules_dir.mkdir()
            (rules_dir / "trading.json").write_text(
                '{"rule_sets":[{"id":"market-watch","title":"Market Watch","enabled":true,"rules":[{"id":"r1","source_type":"email","source_id":"email-tradingview","enabled":true,"kind":"tradingview_user","from_email":"noreply@tradingview.com","tradingview_usernames":["AnalystA"]}]}]}',
                encoding="utf-8",
            )
            normalized = normalize_config(config, base_path=base)
        self.assertEqual(len(normalized["rule_sets"]), 1)
        self.assertEqual(normalized["rule_sets"][0]["id"], "market-watch")

    def test_normalize_sets_last30days_defaults(self) -> None:
        normalized = normalize_config(sample_config())
        self.assertEqual(normalized["last30days"]["mode"], "compact")
        self.assertEqual(normalized["last30days"]["preset_id"], "broad-discovery-v1")
        self.assertEqual(len(normalized["last30days"]["query_bundle"]), 4)

    def test_invalid_last30days_mode_raises(self) -> None:
        config = sample_config()
        config["last30days"] = {
            "mode": "deep",
            "schedule_expr": "0 7 * * *",
            "query_bundle": ["topic"],
            "telegram": {"topic_id": 0},
        }
        with self.assertRaisesRegex(ValueError, "last30days.mode"):
            validate_config(config)


class MatchingTests(unittest.TestCase):
    def test_extract_tradingview_username(self) -> None:
        self.assertEqual(extract_tradingview_username("Idea by @AnalystA"), "AnalystA")

    def test_extract_tradingview_username_from_russian_subject(self) -> None:
        self.assertEqual(
            extract_tradingview_username("Смотрите, новое мнение от Mamontiara"),
            "Mamontiara",
        )

    def test_extract_tradingview_username_from_russian_body(self) -> None:
        self.assertEqual(
            extract_tradingview_username(
                "TradingView\n\nMamontiara\n\nна которого вы подписаны, опубликовал(-а) новое мнение\n\nCNYRUB_TOM"
            ),
            "Mamontiara",
        )

    def test_email_tradingview_known_user_matches(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "New idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        self.assertIsNotNone(candidate)

    def test_email_tradingview_russian_subject_matches(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        rule["tradingview_usernames"] = ["Mamontiara"]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-ru-1",
                "timestamp": "2026-04-13T07:37:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Смотрите, новое мнение от Mamontiara",
                "preview": "",
                "text_excerpt": "CNYRUB_TOM",
            },
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.metadata["resolved_username"], "Mamontiara")

    def test_email_tradingview_russian_body_matches(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        rule["tradingview_usernames"] = ["Mamontiara"]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-ru-2",
                "timestamp": "2026-04-13T07:37:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Смотрите, новое мнение",
                "preview": "",
                "text_excerpt": "TradingView\n\nMamontiara\n\nна которого вы подписаны, опубликовал(-а) новое мнение\n\nCNYRUB_TOM",
            },
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.metadata["resolved_username"], "Mamontiara")

    def test_email_tradingview_unknown_user_ignored(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "New idea by @unknownauthor",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        self.assertIsNone(candidate)

    def test_non_tradingview_sender_ignored(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "Other",
                "from_email": "test@example.com",
                "sender_domain": "example.com",
                "subject": "New idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        self.assertIsNone(candidate)

    def test_telegram_hashtag_match(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][1]
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Трейдер",
                "message_id": 1,
                "sender_id": 10,
                "author": "Trader",
                "text": "Сегодня #si выглядит интересно",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_missing_hashtag_ignored(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][1]
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Трейдер",
                "message_id": 1,
                "sender_id": 10,
                "author": "Trader",
                "text": "Сегодня рынок выглядит интересно",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNone(candidate)

    def test_telegram_author_keywords_match(self) -> None:
        rule = {
            "id": "telegram-gukov-fx",
            "source_id": "telegram-trader-speki",
            "kind": "author_keywords",
            "sender_ids": [777],
            "keywords": ["юань", "валюта"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Example Trader Chat",
                "message_id": 2,
                "sender_id": 777,
                "author": "Example Author",
                "text": "По паре юань и валюте вижу интересный сетап",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_author_keywords_other_author_ignored(self) -> None:
        rule = {
            "id": "telegram-gukov-fx",
            "source_id": "telegram-trader-speki",
            "kind": "author_keywords",
            "sender_ids": [777],
            "keywords": ["юань", "валюта"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "chat_id": -1001,
                "chat_name": "Example Trader Chat",
                "message_id": 2,
                "sender_id": 778,
                "author": "Другой автор",
                "text": "По паре юань и валюте вижу интересный сетап",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        self.assertIsNone(candidate)

    def test_telegram_content_keywords_video_match(self) -> None:
        rule = {
            "id": "bogdanoff-morning-evening-video",
            "source_id": "telegram-bogdanoff-invest",
            "kind": "content_keywords",
            "require_video": True,
            "keywords": ["утрен", "вечерн", "обзор"],
            "tags": ["video"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000001,
                "chat_name": "Example Market Channel",
                "message_id": 10,
                "sender_id": -1003000000001,
                "author": "Example Market Channel",
                "text": "Утренний обзор рынка",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": True,
            },
        )
        self.assertIsNotNone(candidate)

    def test_telegram_content_keywords_require_video_ignored_without_video(self) -> None:
        rule = {
            "id": "bogdanoff-morning-evening-video",
            "source_id": "telegram-bogdanoff-invest",
            "kind": "content_keywords",
            "require_video": True,
            "keywords": ["утрен", "вечерн", "обзор"],
            "tags": ["video"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000001,
                "chat_name": "Example Market Channel",
                "message_id": 10,
                "sender_id": -1003000000001,
                "author": "Example Market Channel",
                "text": "Утренний обзор рынка",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": False,
            },
        )
        self.assertIsNone(candidate)

    def test_telegram_content_keywords_fx_match(self) -> None:
        rule = {
            "id": "artem-bendak-fx-cny-rub",
            "source_id": "telegram-artem-bendak-channel",
            "kind": "content_keywords",
            "keywords": ["юань", "cny", "рубл", "usd", "валют"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000002,
                "chat_name": "Example FX Channel",
                "message_id": 20,
                "sender_id": -1003000000002,
                "author": "Example FX Channel",
                "text": "Разбор пары юань-рубль и валютного рынка",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": False,
            },
        )
        self.assertIsNotNone(candidate)

    def test_keyword_matches_respects_word_boundaries_for_short_words(self) -> None:
        self.assertFalse(keyword_matches("Моя теория гласит, что рынок жив.", "си"))
        self.assertFalse(keyword_matches("Сейчас и мысли совсем о другом.", "си"))
        self.assertTrue(keyword_matches("По СИ вижу интересный сценарий.", "си"))
        self.assertTrue(keyword_matches("Сишка смотрится бодро.", "сишка"))

    def test_telegram_content_keywords_short_word_inside_longer_word_ignored(self) -> None:
        rule = {
            "id": "artem-bendak-fx-cny-rub",
            "source_id": "telegram-artem-bendak-channel",
            "kind": "content_keywords",
            "keywords": ["си", "сишка"],
            "tags": ["fx"],
        }
        candidate = match_telegram_rule(
            ruleset_id="market-watch",
            ruleset_title="Market Watch",
            rule=rule,
            message={
                "chat_id": -1003000000002,
                "chat_name": "Example FX Channel",
                "message_id": 21,
                "sender_id": -1003000000002,
                "author": "Example FX Channel",
                "text": "Моя теория гласит, что сейчас мысли про акции важнее.",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "has_video": False,
            },
        )
        self.assertIsNone(candidate)

    def test_build_telegram_message_link_for_private_chat(self) -> None:
        self.assertEqual(
            build_telegram_message_link(chat_id=-1003000123456, message_id=1999),
            "https://t.me/c/3000123456/1999",
        )


class DeliveryAndStateTests(unittest.TestCase):
    def test_two_matches_fall_into_one_batch(self) -> None:
        rule = sample_config()["rule_sets"][0]["rules"][0]
        candidate1 = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Chart update",
            },
        )
        candidate2 = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=rule,
            message={
                "message_id": "msg-2",
                "timestamp": "2026-04-12T12:01:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Second chart update",
            },
        )
        batch = _local_fallback_batch(candidates=[candidate1, candidate2], topic_name="signals")
        self.assertEqual(len(batch.events), 2)

    def test_email_and_telegram_same_story_stay_separate(self) -> None:
        email_rule = sample_config()["rule_sets"][0]["rules"][0]
        tg_rule = sample_config()["rule_sets"][0]["rules"][1]
        email_candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=email_rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Про SI",
            },
        )
        tg_candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=tg_rule,
            message={
                "chat_id": -1001,
                "chat_name": "Трейдер",
                "message_id": 5,
                "sender_id": 99,
                "author": "Trader",
                "text": "Похожий взгляд на #si",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        batch = _local_fallback_batch(candidates=[email_candidate, tg_candidate], topic_name="signals")
        self.assertEqual([event.source_type for event in batch.events], ["email", "telegram"])

    def test_no_matches_means_no_events(self) -> None:
        batch = _local_fallback_batch(candidates=[], topic_name="signals")
        self.assertEqual(batch.events, [])

    def test_exact_dedup_blocks_duplicate_external_ref(self) -> None:
        r = FakeRedis()
        events = [
            SignalEvent(
                event_id="1",
                ruleset_id="trading",
                rule_id="rule",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:00+00:00",
                captured_at="2026-04-12T12:00:00+00:00",
                author="A",
                title="T1",
                summary="S1",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
            SignalEvent(
                event_id="2",
                ruleset_id="trading",
                rule_id="rule",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:01+00:00",
                captured_at="2026-04-12T12:00:01+00:00",
                author="A",
                title="T1",
                summary="S1",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
        ]
        ids = append_events(r, events, retention_days=14)
        self.assertEqual(len(ids), 1)

    def test_append_new_events_skips_existing_and_same_batch_duplicates(self) -> None:
        r = FakeRedis()
        events = [
            SignalEvent(
                event_id="1",
                ruleset_id="trading",
                rule_id="rule-a",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:00+00:00",
                captured_at="2026-04-12T12:00:00+00:00",
                author="A",
                title="T1",
                summary="S1",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
            SignalEvent(
                event_id="2",
                ruleset_id="trading",
                rule_id="rule-b",
                source_type="telegram",
                source_id="source",
                external_ref="chat:1",
                occurred_at="2026-04-12T12:00:01+00:00",
                captured_at="2026-04-12T12:00:01+00:00",
                author="A",
                title="T1 duplicate",
                summary="S1 duplicate",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
            SignalEvent(
                event_id="3",
                ruleset_id="trading",
                rule_id="rule-c",
                source_type="telegram",
                source_id="source",
                external_ref="chat:2",
                occurred_at="2026-04-12T12:01:00+00:00",
                captured_at="2026-04-12T12:01:00+00:00",
                author="B",
                title="T2",
                summary="S2",
                tags=["si"],
                confidence=0.8,
                telegram_topic="signals",
            ),
        ]

        ids, appended, skipped = append_new_events(r, events, retention_days=14)
        self.assertEqual(len(ids), 2)
        self.assertEqual([event.external_ref for event in appended], ["chat:1", "chat:2"])
        self.assertEqual([event.external_ref for event in skipped], ["chat:1"])

        ids, appended, skipped = append_new_events(r, events, retention_days=14)
        self.assertEqual(ids, [])
        self.assertEqual(appended, [])
        self.assertEqual([event.external_ref for event in skipped], ["chat:1", "chat:1", "chat:2"])

    def test_overlap_window_uses_last_success_minus_grace(self) -> None:
        now = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        last_success = now - timedelta(minutes=5)
        since = resolve_telegram_window(
            source={"overlap_grace_minutes": 15},
            cursor=20,
            last_success=last_success,
            lookback_minutes=None,
            now=now,
        )
        self.assertEqual(since, last_success - timedelta(minutes=15))

    def test_local_batch_preserves_telegram_link_and_email_excerpt(self) -> None:
        email_rule = sample_config()["rule_sets"][0]["rules"][0]
        tg_rule = sample_config()["rule_sets"][0]["rules"][1]
        email_candidate = match_email_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=email_rule,
            message={
                "message_id": "msg-1",
                "timestamp": "2026-04-12T12:00:00+00:00",
                "from_name": "TradingView",
                "from_email": "noreply@tradingview.com",
                "sender_domain": "tradingview.com",
                "subject": "Idea by @AnalystA",
                "preview": "",
                "text_excerpt": "Full email excerpt about SI and setup",
            },
        )
        tg_candidate = match_telegram_rule(
            ruleset_id="trading",
            ruleset_title="Trading",
            rule=tg_rule,
            message={
                "chat_id": -1001,
                "chat_name": "Example Trader Chat",
                "message_id": 5,
                "sender_id": 99,
                "author": "Trader",
                "text": "Похожий взгляд на #si",
                "timestamp": "2026-04-12T12:00:00+00:00",
            },
        )
        batch = _local_fallback_batch(candidates=[email_candidate, tg_candidate], topic_name="signals")
        self.assertEqual(batch.events[0].source_excerpt, "Full email excerpt about SI and setup")
        self.assertEqual(batch.events[1].source_link, "https://t.me/c/1/5")


class Last30DaysDigestTests(unittest.TestCase):
    @patch("last30days_runner.subprocess.run")
    def test_build_digest_merges_queries_and_keeps_partial_failures(self, mock_run) -> None:
        payload = {
            "provider_runtime": {
                "reasoning_provider": "local",
                "planner_model": "deterministic",
                "rerank_model": "deterministic",
            },
            "query_plan": {
                "intent": "research",
                "freshness_mode": "recent",
                "cluster_mode": "standard",
                "raw_topic": "topic",
                "subqueries": [],
                "source_weights": {},
            },
            "clusters": [
                {
                    "cluster_id": "cluster-1",
                    "title": "Theme 1",
                    "candidate_ids": ["cand-1"],
                    "representative_ids": ["cand-1"],
                    "sources": ["reddit", "x"],
                    "score": 91.0,
                }
            ],
            "ranked_candidates": [
                {
                    "candidate_id": "cand-1",
                    "item_id": "item-1",
                    "source": "reddit",
                    "title": "Theme 1",
                    "url": "https://example.com/theme-1",
                    "snippet": "Compact summary",
                    "subquery_labels": ["primary"],
                    "native_ranks": {},
                    "local_relevance": 0.8,
                    "freshness": 9,
                    "engagement": 120,
                    "source_quality": 0.9,
                    "rrf_score": 0.7,
                    "sources": ["reddit", "x"],
                    "source_items": [{"title": "Reference 1", "url": "https://example.com/theme-1"}],
                    "final_score": 95.0,
                    "cluster_id": "cluster-1",
                }
            ],
            "items_by_source": {"reddit": [{"item_id": "item-1"}], "x": [{"item_id": "item-2"}]},
            "errors_by_source": {"youtube": "timeout"},
        }

        success = Mock(returncode=0, stdout=json.dumps(payload), stderr="")
        failure = Mock(returncode=1, stdout="", stderr="provider error")
        mock_run.side_effect = [success, failure, success, success]

        config = normalize_config(sample_config())
        digest = build_digest(
            config,
            preset_id="broad-discovery-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(digest.total_queries, 4)
        self.assertEqual(digest.successful_queries, 3)
        self.assertEqual(digest.status, "partial")
        self.assertTrue(digest.themes)
        self.assertIn("youtube", digest.errors_by_source)
        self.assertEqual(digest.themes[0].title, "Theme 1")

    @patch("last30days_runner.subprocess.run")
    def test_build_digest_uses_rescue_queries_after_empty_composite_result(self, mock_run) -> None:
        empty = {
            "provider_runtime": {
                "reasoning_provider": "local",
                "planner_model": "deterministic",
                "rerank_model": "deterministic",
            },
            "clusters": [],
            "ranked_candidates": [],
            "items_by_source": {"reddit": [], "hackernews": []},
            "errors_by_source": {},
            "warnings": ["No candidates survived retrieval and ranking."],
        }
        rescue = {
            "provider_runtime": {
                "reasoning_provider": "local",
                "planner_model": "deterministic",
                "rerank_model": "deterministic",
            },
            "clusters": [
                {
                    "cluster_id": "cluster-openai-codex",
                    "title": "OpenAI Codex reaches 3M weekly active users",
                    "candidate_ids": ["codex-1"],
                    "representative_ids": ["codex-1"],
                    "sources": ["hackernews"],
                    "score": 91.0,
                }
            ],
            "ranked_candidates": [
                {
                    "candidate_id": "codex-1",
                    "item_id": "item-codex-1",
                    "source": "hackernews",
                    "title": "OpenAI Codex reaches 3M weekly active users",
                    "url": "https://example.com/openai-codex",
                    "snippet": "OpenAI Codex reached 3M weekly active users in under a month.",
                    "sources": ["hackernews"],
                    "source_items": [{"title": "HN reference", "url": "https://example.com/openai-codex"}],
                    "final_score": 95.0,
                    "cluster_id": "cluster-openai-codex",
                }
            ],
            "items_by_source": {"hackernews": [{"item_id": "item-codex-1"}]},
            "errors_by_source": {},
            "warnings": [],
        }

        def fake_run(cmd, **kwargs):
            query = cmd[2]
            payload = rescue if query == "OpenAI Codex" else empty
            return Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        mock_run.side_effect = fake_run

        config = normalize_config(sample_config())
        digest = build_digest(
            config,
            preset_id="broad-discovery-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(digest.status, "ok")
        self.assertTrue(digest.themes)
        self.assertEqual(digest.themes[0].title, "OpenAI Codex reaches 3M weekly active users")
        self.assertGreaterEqual(digest.source_counts["hn"], 1)
        first_report = digest.reports[0]
        self.assertIn("rescue_queries", first_report)
        self.assertIn("OpenAI Codex", first_report["rescue_queries"])

    @patch("last30days_runner.subprocess.run")
    def test_build_digest_passes_github_repo_hints_for_top_queries(self, mock_run) -> None:
        payload = {
            "provider_runtime": {
                "reasoning_provider": "local",
                "planner_model": "deterministic",
                "rerank_model": "deterministic",
            },
            "clusters": [],
            "ranked_candidates": [],
            "items_by_source": {},
            "errors_by_source": {},
            "warnings": [],
        }
        mock_run.return_value = Mock(returncode=0, stdout=json.dumps(payload), stderr="")

        config = normalize_config(sample_config())
        config["last30days"]["query_bundle"] = ["OpenAI Codex"]
        digest = build_digest(
            config,
            preset_id="broad-discovery-v1",
            now=datetime(2026, 4, 12, 4, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(digest.total_queries, 1)
        first_cmd = mock_run.call_args[0][0]
        self.assertIn("--github-repo", first_cmd)
        idx = first_cmd.index("--github-repo")
        self.assertEqual(first_cmd[idx + 1], "openai/codex")


if __name__ == "__main__":
    unittest.main()
