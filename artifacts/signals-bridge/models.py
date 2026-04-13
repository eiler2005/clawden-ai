"""
Structured data contracts for the signals bridge.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ModelMeta:
    model_id: str = "local"
    tier: str = "light"
    provider_fallback: bool = False
    local_fallback: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ModelMeta":
        payload = payload or {}
        return cls(
            model_id=str(payload.get("model_id") or "local"),
            tier=str(payload.get("tier") or "light"),
            provider_fallback=bool(payload.get("provider_fallback", False)),
            local_fallback=bool(payload.get("local_fallback", False)),
        )


@dataclass
class SignalCandidate:
    ruleset_id: str
    ruleset_title: str
    rule_id: str
    source_type: str
    source_id: str
    external_ref: str
    occurred_at: str
    captured_at: str
    author: str
    subject: str
    excerpt: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "external_ref": self.external_ref,
            "occurred_at": self.occurred_at,
            "author": self.author,
            "subject": self.subject,
            "excerpt": self.excerpt,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class SignalEvent:
    event_id: str
    ruleset_id: str
    rule_id: str
    source_type: str
    source_id: str
    external_ref: str
    occurred_at: str
    captured_at: str
    author: str
    title: str
    summary: str
    source_link: str = ""
    source_excerpt: str = ""
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    telegram_topic: str = "signals"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreparedSignalBatch:
    events: list[SignalEvent]
    model_meta: ModelMeta
    dropped_external_refs: list[str] = field(default_factory=list)


@dataclass
class Last30DaysTheme:
    theme_id: str
    title: str
    snippet: str
    url: str
    sources: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    score: float = 0.0
    source_titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Last30DaysDigest:
    preset_id: str
    mode: str
    generated_at: str
    topic_name: str
    topic_id: int
    query_bundle: list[str]
    themes: list[Last30DaysTheme] = field(default_factory=list)
    source_counts: dict[str, int] = field(default_factory=dict)
    errors_by_source: dict[str, str] = field(default_factory=dict)
    query_errors: dict[str, str] = field(default_factory=dict)
    successful_queries: int = 0
    total_queries: int = 0
    suggestions: list[str] = field(default_factory=list)
    reports: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    status: str = "ok"
    persisted_paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["themes"] = [theme.to_dict() for theme in self.themes]
        return payload
