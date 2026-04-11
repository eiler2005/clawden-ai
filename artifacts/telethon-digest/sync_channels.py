"""
Utility: sync Telegram dialog folders to config.json.

Reads all DialogFilter (folder) entities via Telethon and updates
the 'folders' section in config.json. Existing priority values are
preserved when the folder name matches. New folders get priority=1.

Usage:
    docker compose run --rm telethon-digest python sync_channels.py [--dry-run]
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/app/telethon.env", override=False)

from telethon import TelegramClient
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import DialogFilter, Channel, Chat

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("sync_channels")

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_PATH = "/app/sessions/telethon_digest"
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.json"))


async def sync(dry_run: bool = False):
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        logger.error("Not authorized. Run auth.py first.")
        return

    # Fetch folder definitions
    filters = await client(GetDialogFiltersRequest())
    logger.info(f"Found {len(filters.filters)} dialog filters (folders)")

    # Load existing config
    config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    existing_folders = {f["name"]: f for f in config.get("folders", [])}

    new_folders = []
    for df in filters.filters:
        if not isinstance(df, DialogFilter):
            continue  # skip "All chats" default filter

        folder_name = df.title
        prior_entry = existing_folders.get(folder_name, {})
        priority = prior_entry.get("priority", 1)

        channels = []
        for peer in df.include_peers:
            try:
                entity = await client.get_entity(peer)
            except Exception as e:
                logger.warning(f"Could not resolve peer {peer}: {e}")
                continue

            if not isinstance(entity, (Channel, Chat)):
                continue

            cid = entity.id
            # Telethon returns bare IDs; supergroup/channel peers need -100 prefix
            if isinstance(entity, Channel):
                full_id = int(f"-100{cid}")
                chat_type = "channel" if entity.broadcast else "supergroup"
            else:
                full_id = -cid
                chat_type = "group"

            channels.append(
                {
                    "id": full_id,
                    "name": entity.title or str(cid),
                    "type": chat_type,
                    "broadcast": bool(getattr(entity, "broadcast", False)),
                    "megagroup": bool(getattr(entity, "megagroup", False)),
                    "position": len(channels),                              # 0-based index in folder (Telegram order)
                    "username": getattr(entity, "username", "") or "",   # for public t.me links (Channel only)
                }
            )

        new_folders.append(
            {"name": folder_name, "priority": priority, "channels": channels}
        )
        logger.info(f"  Folder '{folder_name}' (priority={priority}): {len(channels)} channels")

    await client.disconnect()

    config["folders"] = new_folders

    if dry_run:
        print(json.dumps(config, indent=2, ensure_ascii=False))
        logger.info("Dry-run — config NOT written")
    else:
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False))
        logger.info(f"Config written to {CONFIG_PATH}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print result without saving")
    args = parser.parse_args()
    asyncio.run(sync(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
