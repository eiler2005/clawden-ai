"""
Shared data models — no Telethon, no LLM dependencies.

All pipeline modules import from here so that I/O, LLM, rendering, and
persistence stay loosely coupled and exchange structured data only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Post:
    channel_id: int
    channel_name: str
    folder_name: str
    folder_priority: int
    msg_id: int
    text: str
    date: datetime
    is_pinned: bool = False
    url: str | None = None
    channel_url: str | None = None
    score: float = 0.0
    channel_position: int = 0
    channel_username: str = ""
    also_mentioned: list[str] = field(default_factory=list)


@dataclass
class ModelMeta:
    model_id: str
    tier: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider_fallback: bool = False
    local_fallback: bool = False


@dataclass
class DigestItem:
    channel: str
    channel_url: str | None
    post_url: str
    summary: str
    kind: str
    pinned: bool = False
    also_mentioned: list[str] = field(default_factory=list)
    extra_post_urls: list[str] = field(default_factory=list)
    why_important: str = ""


@dataclass
class DigestSection:
    folder: str
    tier: str
    folder_link: str | None = None
    items: list[DigestItem] = field(default_factory=list)


@dataclass
class DigestStats:
    channels_in_scope: int
    new_posts_seen: int
    posts_selected: int
    active_channels_seen: int = 0
    folder_message_counts: dict[str, int] = field(default_factory=dict)
    folder_channel_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class DigestDocument:
    digest_type: str
    title: str
    period_label: str
    lead: list[str]
    new_glance: list[DigestItem]
    must_read: list[DigestItem]
    sections: list[DigestSection]
    low_signal: list[str]
    model_meta: ModelMeta
    stats: DigestStats
    executive_summary: list[str] = field(default_factory=list)
    themes: list[str] = field(default_factory=list)
    quiet_folders: list[str] = field(default_factory=list)
    watchpoints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CuratedDigestNote:
    title: str
    domain: str
    source: str
    date: str
    summary: str
    claims: list[str] = field(default_factory=list)
    decision: str = ""
    next_actions: list[str] = field(default_factory=list)
    sensitivity: str = "low"
    references: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMCompletion:
    text: str
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider_fallback: bool = False


_MODEL_NAMES: dict[str, str] = {
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
    "claude-haiku-4.5": "Claude Haiku 4.5",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    "claude-3-5-haiku-20241022": "Claude Haiku 3.5",
    "gemini-2.0-flash": "Gemini 2.0 Flash",
    "gemini-2.5-flash": "Gemini 2.5 Flash",
    "gpt-4o-mini": "GPT-4o Mini",
    "gpt-4o": "GPT-4o",
    "gpt-5.4": "GPT-5.4",
    "local": "Local fallback",
}


def friendly_model(model_id: str) -> str:
    return _MODEL_NAMES.get(model_id, model_id)
