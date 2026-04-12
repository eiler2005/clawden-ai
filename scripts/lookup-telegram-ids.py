#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat, User


def _load_env() -> None:
    for candidate in [
        Path("secrets/telethon-digest/telethon.env"),
        Path("secrets/signals-bridge/signals.env"),
    ]:
        if candidate.exists():
            load_dotenv(candidate, override=False)


def _session_path() -> str:
    return os.environ.get("SIGNALS_TELETHON_SESSION_PATH") or os.environ.get(
        "TELETHON_SESSION_PATH",
        str(Path.cwd() / ".tmp-signals-telethon-session"),
    )


def _display_name(entity) -> str:
    if isinstance(entity, User):
        parts = [entity.first_name or "", entity.last_name or ""]
        return " ".join(part.strip() for part in parts if part.strip()).strip() or (entity.username or str(entity.id))
    return getattr(entity, "title", "") or getattr(entity, "username", "") or str(getattr(entity, "id", ""))


async def _search_chat(client: TelegramClient, query: str) -> list[dict]:
    results: list[dict] = []
    query_cf = query.casefold()
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        title = _display_name(entity)
        hay = " ".join(filter(None, [title, getattr(entity, "username", "")])).casefold()
        if query_cf not in hay:
            continue
        results.append(
            {
                "id": getattr(entity, "id", None) if isinstance(entity, User) else dialog.id,
                "title": title,
                "username": getattr(entity, "username", None),
                "type": type(entity).__name__.lower(),
            }
        )
    return results


async def _search_member(client: TelegramClient, chat_id: int, query: str, limit: int) -> list[dict]:
    entity = await client.get_entity(chat_id)
    query_cf = query.casefold()
    results: list[dict] = []
    async for user in client.iter_participants(entity, limit=limit):
        title = _display_name(user)
        username = getattr(user, "username", "") or ""
        hay = " ".join(filter(None, [title, username])).casefold()
        if query_cf not in hay:
            continue
        results.append(
            {
                "id": user.id,
                "name": title,
                "username": username or None,
                "is_bot": bool(getattr(user, "bot", False)),
            }
        )
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="Lookup Telegram chat_id or participant sender_id via Telethon.")
    parser.add_argument("--chat", help="Substring to search across dialogs for chat/group/channel ids.")
    parser.add_argument("--chat-id", type=int, help="Concrete chat id to inspect participants in.")
    parser.add_argument("--member", help="Substring to search among participants of --chat-id.")
    parser.add_argument("--limit", type=int, default=200, help="Participant scan limit for --member (default: 200).")
    args = parser.parse_args()

    if not args.chat and not (args.chat_id and args.member):
        parser.error("Use either --chat <name> or --chat-id <id> --member <name>.")

    _load_env()
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    session_path = _session_path()

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise SystemExit(
                "Telethon session is not authorized. Run auth first, for example: "
                "cd artifacts/signals-bridge && docker compose run --rm signals-bridge python auth.py"
            )

        if args.chat:
            print(json.dumps(await _search_chat(client, args.chat), ensure_ascii=False, indent=2))
            return

        print(
            json.dumps(
                await _search_member(client, args.chat_id, args.member, args.limit),
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
