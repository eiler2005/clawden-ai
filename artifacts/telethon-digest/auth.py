"""
Interactive Telethon authentication — run once to create the session file.

Usage:
    docker compose run --rm telethon-digest python auth.py
"""
import asyncio
import os
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

load_dotenv("/app/telethon.env", override=False)
load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
PHONE = os.environ["TELEGRAM_PHONE"]
SESSION_PATH = "/app/sessions/telethon_digest"


async def main():
    client = TelegramClient(SESSION_PATH, API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        await client.send_code_request(PHONE)
        code = input("Enter the code you received: ").strip()
        try:
            await client.sign_in(PHONE, code)
        except SessionPasswordNeededError:
            pw = input("Two-factor auth enabled. Enter your password: ").strip()
            await client.sign_in(password=pw)

    me = await client.get_me()
    print(f"Authorized as: {me.first_name} (@{me.username})")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
