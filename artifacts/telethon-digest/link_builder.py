"""
Build t.me deep links to Telegram messages.
For public channels: t.me/<username>/<msg_id>
For private channels/supergroups: t.me/c/<channel_id_without_prefix>/<msg_id>
"""
from __future__ import annotations

from models import Post


def build_link(post: Post, channel_usernames: dict[int, str] | None = None) -> str:
    """
    channel_usernames: optional mapping channel_id → @username
    If username known, builds public link; otherwise private supergroup link.
    """
    if channel_usernames:
        username = channel_usernames.get(post.channel_id)
        if username:
            clean = username.lstrip("@")
            return f"https://t.me/{clean}/{post.msg_id}"

    # Private channel: strip -100 prefix
    raw_id = str(post.channel_id)
    if raw_id.startswith("-100"):
        cid = raw_id[4:]
    elif raw_id.startswith("-"):
        cid = raw_id[1:]
    else:
        cid = raw_id

    return f"https://t.me/c/{cid}/{post.msg_id}"


def build_channel_link(post: Post, channel_usernames: dict[int, str] | None = None) -> str | None:
    username = ""
    if channel_usernames:
        username = channel_usernames.get(post.channel_id, "") or ""
    if not username:
        username = post.channel_username or ""
    if not username:
        return None
    return f"https://t.me/{username.lstrip('@')}"


def attach_links(posts: list[Post], channel_usernames: dict[int, str] | None = None):
    """Mutate posts in-place, setting post.url and post.channel_url."""
    for p in posts:
        p.url = build_link(p, channel_usernames)
        p.channel_url = build_channel_link(p, channel_usernames)
