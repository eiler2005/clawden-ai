"""
Structured data contracts for AgentMail inbox ingestion and digest rendering.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ModelMeta:
    model_id: str = "openclaw"
    tier: str = "primary"
    model_label: str = ""
    provider_fallback: bool = False
    local_fallback: bool = False
    score_pct: int | None = None
    complexity: str = "standard"
    memory_mode: str = "memory"

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "ModelMeta":
        payload = payload or {}
        raw_score = payload.get("score_pct")
        score_pct: int | None = None
        if raw_score not in (None, ""):
            try:
                score_pct = max(0, min(100, int(raw_score)))
            except (TypeError, ValueError):
                score_pct = None
        return cls(
            model_id=str(payload.get("model_id") or "openclaw"),
            tier=str(payload.get("tier") or "primary"),
            model_label=str(payload.get("model_label") or ""),
            provider_fallback=bool(payload.get("provider_fallback", False)),
            local_fallback=bool(payload.get("local_fallback", False)),
            score_pct=score_pct,
            complexity=str(payload.get("complexity") or "standard").strip() or "standard",
            memory_mode=str(payload.get("memory_mode") or "memory").strip() or "memory",
        )


@dataclass
class EmailEvent:
    event_id: str
    run_id: str
    inbox_ref: str
    thread_id: str
    message_ids: list[str]
    received_at: str
    from_name: str
    from_email: str
    sender_domain: str
    subject: str
    summary: str
    importance: float
    categories: list[str] = field(default_factory=list)
    has_attachments: bool = False
    attachment_count: int = 0
    internal_labels: list[str] = field(default_factory=list)
    telegram_topic: str = "inbox-email"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PollPrepResult:
    messages_scanned: int
    threads_considered: int
    threads_selected: int
    low_signal_count: int
    batch_lead: list[str]
    publish_events: list[EmailEvent]
    label_actions: dict[str, list[str]]
    model_meta: ModelMeta
    prefilter_scanned_threads: int = 0
    prefilter_skipped_handled: int = 0
    prefilter_skipped_low_signal: int = 0
    prefilter_candidate_threads: int = 0
    llm_skipped: bool = False

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        run_id: str,
        inbox_ref: str,
        telegram_topic: str,
    ) -> "PollPrepResult":
        events: list[EmailEvent] = []
        for idx, item in enumerate(payload.get("publish_events", []) or [], start=1):
            message_ids = [str(v) for v in item.get("message_ids", []) if str(v).strip()]
            events.append(
                EmailEvent(
                    event_id=f"{run_id}:{idx:02d}",
                    run_id=run_id,
                    inbox_ref=inbox_ref,
                    thread_id=str(item.get("thread_id", "")).strip() or f"thread-{idx}",
                    message_ids=message_ids,
                    received_at=str(item.get("received_at", "")).strip(),
                    from_name=str(item.get("from_name", "")).strip(),
                    from_email=str(item.get("from_email", "")).strip(),
                    sender_domain=str(item.get("sender_domain", "")).strip(),
                    subject=str(item.get("subject", "")).strip() or "(no subject)",
                    summary=str(item.get("summary", "")).strip(),
                    importance=float(item.get("importance", 0.0) or 0.0),
                    categories=[str(v) for v in item.get("categories", []) if str(v).strip()],
                    has_attachments=bool(item.get("has_attachments", False)),
                    attachment_count=int(item.get("attachment_count", 0) or 0),
                    internal_labels=[str(v) for v in item.get("internal_labels", []) if str(v).strip()],
                    telegram_topic=str(item.get("telegram_topic", "")).strip() or telegram_topic,
                )
            )

        label_actions = {
            str(label): [str(v) for v in values if str(v).strip()]
            for label, values in (payload.get("label_actions", {}) or {}).items()
            if str(label).strip()
        }

        return cls(
            messages_scanned=int(payload.get("messages_scanned", 0) or 0),
            threads_considered=int(payload.get("threads_considered", 0) or 0),
            threads_selected=int(payload.get("threads_selected", len(events)) or len(events)),
            low_signal_count=int(payload.get("low_signal_count", 0) or 0),
            prefilter_scanned_threads=int(payload.get("prefilter_scanned_threads", 0) or 0),
            prefilter_skipped_handled=int(payload.get("prefilter_skipped_handled", 0) or 0),
            prefilter_skipped_low_signal=int(payload.get("prefilter_skipped_low_signal", 0) or 0),
            prefilter_candidate_threads=int(payload.get("prefilter_candidate_threads", 0) or 0),
            llm_skipped=bool(payload.get("llm_skipped", False)),
            batch_lead=[str(v) for v in payload.get("batch_lead", []) if str(v).strip()],
            publish_events=events,
            label_actions=label_actions,
            model_meta=ModelMeta.from_payload(payload.get("model_meta")),
        )


@dataclass
class DigestPrepResult:
    digest_type: str
    title: str
    period_label: str
    lead: list[str]
    themes: list[str]
    important_event_ids: list[str]
    actions: list[str]
    watchpoints: list[str]
    low_signal_recap: str
    model_meta: ModelMeta

    @classmethod
    def from_payload(cls, payload: dict[str, Any], *, digest_type: str) -> "DigestPrepResult":
        return cls(
            digest_type=digest_type,
            title=str(payload.get("title", "")).strip() or "Inbox Email",
            period_label=str(payload.get("period_label", "")).strip(),
            lead=[str(v) for v in payload.get("lead", []) if str(v).strip()],
            themes=[str(v) for v in payload.get("themes", []) if str(v).strip()],
            important_event_ids=[str(v) for v in payload.get("important_event_ids", []) if str(v).strip()],
            actions=[str(v) for v in payload.get("actions", []) if str(v).strip()],
            watchpoints=[str(v) for v in payload.get("watchpoints", []) if str(v).strip()],
            low_signal_recap=str(payload.get("low_signal_recap", "")).strip(),
            model_meta=ModelMeta.from_payload(payload.get("model_meta")),
        )
