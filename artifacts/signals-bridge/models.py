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
