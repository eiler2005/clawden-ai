"""
Batched Telethon channel reader.

For each channel reads:
  - New messages since last_seen_msg_id (up to 50 most recent)
  - Currently pinned messages (up to 5)

Reads channels in parallel batches of config.read_batch_size with
config.read_batch_delay_sec pause between batches to stay within
Telegram rate limits. Telethon auto-handles FloodWait internally.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from telethon import TelegramClient
from telethon.tl.types import Channel, Message
from telethon.tl.types import InputMessagesFilterPinned

import state_store
from models import Post

logger = logging.getLogger(__name__)

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_PATH = "/app/sessions/telethon_digest"


async def _read_channel(
    client: TelegramClient,
    channel: dict,
    folder_name: str,
    folder_priority: int,
    last_seen_id: int,
    lookahead_hours: float,
    pinned_ids: set[int],
    channel_position: int = 0,
    channel_username: str = "",
) -> list[Post]:
    cid = channel["id"]
    cname = channel["name"]
    posts = []

    cutoff_ts = time.time() - lookahead_hours * 3600

    try:
        messages = await client.get_messages(cid, limit=50, min_id=last_seen_id)
    except Exception as e:
        logger.warning(f"Failed to read {cname} ({cid}): {e}")
        return posts

    for msg in messages:
        if not isinstance(msg, Message):
            continue
        if not msg.text:
            continue
        if msg.date.timestamp() < cutoff_ts:
            continue

        posts.append(
            Post(
                channel_id=cid,
                channel_name=cname,
                folder_name=folder_name,
                folder_priority=folder_priority,
                msg_id=msg.id,
                text=msg.text[:2000],  # cap per-message text
                date=msg.date,
                is_pinned=(msg.id in pinned_ids),
                channel_position=channel_position,
                channel_username=channel_username,
            )
        )

    return posts


async def _get_pinned_ids(client: TelegramClient, channel_id: int) -> set[int]:
    try:
        msgs = await client.get_messages(
            channel_id, filter=InputMessagesFilterPinned, limit=5
        )
        return {m.id for m in msgs if isinstance(m, Message)}
    except Exception:
        return set()


def _build_channel_list(config: dict) -> list[tuple[dict, str, int]]:
    """
    Build the (channel, folder_name, priority) list enforcing read-scope rules at runtime.

    Rules (default to most restrictive):
      read_only                    — must be True, otherwise abort
      require_explicit_allowlist   — only folders in allowed_folder_names pass
      read_broadcast_channels_only — only channels with type=="channel" or broadcast==True
      excluded_folder_names        — folders always skipped regardless of allowlist
      excluded_channel_ids         — channels always skipped
    """
    if not config.get("read_only", True):
        raise RuntimeError("read_only is False in config — refusing to proceed")

    require_allowlist = config.get("require_explicit_allowlist", True)
    broadcast_only = config.get("read_broadcast_channels_only", True)
    allowed_folders = set(config.get("allowed_folder_names", []))
    excluded_folders = set(config.get("excluded_folder_names", []))
    excluded_ids = set(config.get("excluded_channel_ids", []))

    result = []
    skipped_allowlist = 0
    skipped_broadcast = 0
    skipped_excluded = 0

    for folder in config.get("folders", []):
        fname = folder["name"]
        if fname in excluded_folders:
            skipped_excluded += len(folder.get("channels", []))
            continue
        if require_allowlist and allowed_folders and fname not in allowed_folders:
            skipped_allowlist += len(folder.get("channels", []))
            continue
        for ch in folder.get("channels", []):
            cid = ch["id"]
            if cid in excluded_ids:
                skipped_excluded += 1
                continue
            if broadcast_only:
                if ch.get("type") not in ("channel",) and not ch.get("broadcast", False):
                    skipped_broadcast += 1
                    continue
            result.append((ch, fname, folder["priority"]))

    total = sum(len(f.get("channels", [])) for f in config.get("folders", []))
    logger.info(
        f"Read allowlist: {len({r[1] for r in result})} folders / {len(result)} channels "
        f"selected from {total} "
        f"(skipped: {skipped_allowlist} not-in-allowlist, "
        f"{skipped_broadcast} non-broadcast, {skipped_excluded} excluded)"
    )
    return result


async def read_all_channels(client: TelegramClient, config: dict) -> list[Post]:
    """Read all configured channels in batches, return flat list of Posts."""
    all_channels = _build_channel_list(config)

    batch_size = config.get("read_batch_size", 10)
    delay = config.get("read_batch_delay_sec", 1.5)
    lookahead = config.get("lookahead_hours", 4)

    all_posts: list[Post] = []

    batches = [
        all_channels[i : i + batch_size]
        for i in range(0, len(all_channels), batch_size)
    ]

    logger.info(
        f"Batched read: {len(all_channels)} channels in {len(batches)} batches "
        f"(batch_size={batch_size})"
    )

    for batch_idx, batch in enumerate(batches):
        tasks = []
        for ch, fname, fpriority in batch:
            last_seen = state_store.get_cursor(ch["id"])
            tasks.append(
                asyncio.ensure_future(
                    _read_channel_with_pins(
                        client, ch, fname, fpriority, last_seen, lookahead
                    )
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Channel read error: {res}")
            else:
                all_posts.extend(res)

        if batch_idx < len(batches) - 1:
            await asyncio.sleep(delay)

    logger.info(f"Read total {len(all_posts)} posts")
    return all_posts


async def _read_channel_with_pins(
    client, channel, folder_name, folder_priority, last_seen_id, lookahead_hours
):
    pinned_ids = await _get_pinned_ids(client, channel["id"])
    return await _read_channel(
        client,
        channel,
        folder_name,
        folder_priority,
        last_seen_id,
        lookahead_hours,
        pinned_ids,
        channel_position=channel.get("position", 0),
        channel_username=channel.get("username", ""),
    )


def update_cursors(posts: list[Post]):
    """Advance watermarks to the highest seen msg_id per channel."""
    max_ids: dict[int, int] = {}
    for p in posts:
        if p.msg_id > max_ids.get(p.channel_id, 0):
            max_ids[p.channel_id] = p.msg_id
    if max_ids:
        state_store.bulk_set_cursors(max_ids)


def build_client() -> TelegramClient:
    return TelegramClient(SESSION_PATH, API_ID, API_HASH)
