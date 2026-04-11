"""
Main digest orchestrator.

Modes:
  python digest_worker.py          — starts APScheduler daemon (local/debug only)
  python digest_worker.py --now    — runs one digest cycle immediately and exits

Environment: loads /app/telethon.env (inside container).
Config: /app/config.json.
"""
import argparse
import asyncio
import copy
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from dotenv import load_dotenv

# Load env before importing modules that reference os.environ
load_dotenv("/app/telethon.env", override=False)

import state_store
from reader import build_client, read_all_channels, update_cursors
from scorer import score_posts
from dedup import deduplicate_posts
from link_builder import attach_links
from summarizer import summarize
from poster import post_digest
from persistence import persist_digest
from models import DigestStats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("digest_worker")

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.json"))
TZ_MSK = pytz.timezone("Europe/Moscow")


def _get_digest_type(config: dict) -> str:
    """Determine digest type by current MSK hour, with env override for testing."""
    override = os.environ.get("DIGEST_TYPE_OVERRIDE", "").strip()
    if override:
        return override
    tz = pytz.timezone(config.get("timezone", "Europe/Moscow"))
    hour = str(datetime.now(tz).hour)
    return config.get("digest_types", {}).get(hour, "interval")


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text())


def _as_int_set(values: list[int | str]) -> set[int]:
    return {int(v) for v in values}


def apply_read_allowlist(config: dict) -> dict:
    """
    Enforce least-privilege reads before Telethon sees the channel list.

    Telegram user sessions do not support API scopes, so the service must
    fail closed at application level: only configured folders/channel IDs are
    read, and only broadcast channels are read by default.
    """
    if config.get("read_only") is not True:
        raise ValueError("Telethon Digest requires read_only=true")

    allowed_folders = set(config.get("allowed_folder_names", []))
    allowed_channel_ids = _as_int_set(config.get("allowed_channel_ids", []))
    excluded_folders = set(config.get("excluded_folder_names", []))
    excluded_channel_ids = _as_int_set(config.get("excluded_channel_ids", []))
    broadcast_only = config.get("read_broadcast_channels_only", True)

    if config.get("require_explicit_allowlist", True) and not (
        allowed_folders or allowed_channel_ids
    ):
        raise ValueError("No allowed folders or channel IDs configured")

    filtered = copy.deepcopy(config)
    filtered_folders = []
    before_channels = sum(len(f.get("channels", [])) for f in config.get("folders", []))

    for folder in config.get("folders", []):
        folder_name = folder.get("name", "")
        if folder_name in excluded_folders:
            continue

        folder_allowed = not allowed_folders or folder_name in allowed_folders
        kept_channels = []
        for channel in folder.get("channels", []):
            channel_id = int(channel["id"])
            if channel_id in excluded_channel_ids:
                continue
            if not (folder_allowed or channel_id in allowed_channel_ids):
                continue
            if broadcast_only and channel.get("broadcast") is not True:
                continue
            kept_channels.append(channel)

        if kept_channels:
            next_folder = copy.deepcopy(folder)
            next_folder["channels"] = kept_channels
            filtered_folders.append(next_folder)

    filtered["folders"] = filtered_folders
    after_channels = sum(len(f.get("channels", [])) for f in filtered_folders)
    logger.info(
        "Read allowlist: %s folders / %s channels selected from %s channels",
        len(filtered_folders),
        after_channels,
        before_channels,
    )
    if after_channels == 0:
        raise ValueError("Read allowlist selected 0 channels")
    return filtered


async def run_digest(config: dict | None = None):
    """Execute one full digest cycle."""
    if config is None:
        config = load_config()

    digest_type = _get_digest_type(config)
    logger.info(f"Digest type: {digest_type}")

    config = apply_read_allowlist(config)
    channels_in_scope = sum(len(folder.get("channels", [])) for folder in config.get("folders", []))

    period_end = datetime.now(timezone.utc)
    period_start_ts = state_store.get_last_run()
    if period_start_ts == 0:
        # First run: use lookahead_hours as window
        period_start_ts = time.time() - config.get("lookahead_hours", 4) * 3600
    period_start = datetime.fromtimestamp(period_start_ts, tz=timezone.utc)

    logger.info(
        f"Digest cycle: {period_start.isoformat()} → {period_end.isoformat()}"
    )

    client = build_client()
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("Telethon session not authorized. Run auth.py first.")
        await client.disconnect()
        return

    try:
        # 1. Read channels
        all_posts = await read_all_channels(client, config)
    finally:
        await client.disconnect()

    if not all_posts:
        logger.info("No new posts — skipping digest")
        state_store.set_last_run()
        return

    # 2. Score & filter
    top_posts = score_posts(all_posts, config)

    if not top_posts:
        logger.info("No posts above min_score — skipping digest")
        state_store.set_last_run()
        return

    # 3. LLM dedup (clusters similar posts across channels)
    top_posts = await deduplicate_posts(top_posts, config)

    # 4. Attach links
    attach_links(top_posts)

    stats = DigestStats(
        channels_in_scope=channels_in_scope,
        new_posts_seen=len(all_posts),
        posts_selected=len(top_posts),
        active_channels_seen=len({post.channel_id for post in all_posts}),
        folder_message_counts=dict(Counter(post.folder_name for post in all_posts)),
        folder_channel_counts={
            folder_name: len(channel_ids)
            for folder_name, channel_ids in _folder_channel_sets(all_posts).items()
        },
    )

    # 5. Summarize into one structured digest document
    digest_document = await summarize(
        top_posts,
        config=config,
        digest_type=digest_type,
        period_start=period_start,
        period_end=period_end,
        stats=stats,
    )

    # 6. Post to Telegram via OpenClaw bot token
    posted = await post_digest(digest_document)
    if not posted:
        logger.error("Digest publication failed — state not advanced")
        return

    # 7. Persist processed digest after successful Telegram publication
    try:
        await persist_digest(
            digest_document,
            config=config,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:
        logger.error("Digest persistence failed: %s", exc)

    # 8. Advance watermarks
    update_cursors(all_posts)
    state_store.set_last_run()

    logger.info("Digest cycle complete")


def _folder_channel_sets(posts):
    by_folder = defaultdict(set)
    for post in posts:
        by_folder[post.folder_name].add(post.channel_id)
    return by_folder


def _job_listener(event):
    if event.exception:
        logger.error(f"Scheduled job failed: {event.exception}")
    else:
        logger.info("Scheduled job completed successfully")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", action="store_true", help="Run once immediately")
    args = parser.parse_args()

    config = load_config()
    schedule_hours = config.get("schedule_hours", [8, 9, 12, 15, 19, 21])
    tz = config.get("timezone", "Europe/Moscow")

    if args.now:
        logger.info("Running digest immediately (--now mode)")
        asyncio.run(run_digest(config))
        return

    # Local APScheduler daemon fallback; production scheduling is handled by OpenClaw Cron Jobs.
    scheduler = AsyncIOScheduler(timezone=tz)
    scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    hours_str = ",".join(str(h) for h in schedule_hours)
    scheduler.add_job(
        run_digest,
        trigger="cron",
        hour=hours_str,
        minute=0,
        misfire_grace_time=300,  # skip if container was down; don't catch up
        kwargs={"config": config},
        id="digest",
        name="Telegram Digest",
    )

    scheduler.start()
    logger.info(
        f"APScheduler started. Digest at hours {schedule_hours} ({tz}). "
        f"Next run: {scheduler.get_job('digest').next_run_time}"
    )

    # Keep event loop alive
    loop = asyncio.get_event_loop()
    try:
        loop.run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    main()
