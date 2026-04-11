"""
Prompt builders for the AgentMail inbox-email pipeline.
"""
from __future__ import annotations

import json
from datetime import datetime

from models import EmailEvent


def build_prepare_poll_prompt(
    *,
    inbox_ref: str,
    topic_name: str,
    since_iso: str,
    until_iso: str,
    labels: dict[str, str],
    low_signal_hints: list[str],
    mode: str = "poll",
) -> str:
    skip_labels = [labels["polled"], labels["low_signal"], labels["digested"]]
    no_side_effects = (
        "No side effects: do not send, draft, archive, mark read, or update labels."
        if mode == "poll"
        else "No Telegram posting and no mailbox side effects in this phase."
    )
    batch_note = (
        "Prepare one compact mini-batch for Telegram topic inbox-email."
        if mode == "poll"
        else "This is catch-up mode for a future digest. batch_lead may be empty."
    )
    return f"""You are preparing Benka's inbox-email ingestion window.

You have access to AgentMail inside OpenClaw through MCP tools with the `agentmail__` prefix.
Use only these mailbox tools when needed: `agentmail__list_inboxes`, `agentmail__list_threads`,
`agentmail__get_thread`, `agentmail__update_message`.

Inbox: {inbox_ref}
Window start (inclusive): {since_iso}
Window end (inclusive): {until_iso}
Mode: {mode}

Rules:
- Read only this inbox.
- {no_side_effects}
- Use extracted_text or extracted_html when available so quoted history is stripped.
- Group new mail by thread_id. Multiple new messages in the same thread become one publish_event.
- Skip messages that already carry any of these internal labels unless a newer unlabeled message in the same
  thread arrived inside the window: {", ".join(skip_labels)}.
- Keep attachments as metadata only. Do not dump raw email bodies.
- Treat obvious promo / newsletter / marketing / cold-sales noise as low signal.
- Use these low-signal hints if helpful: {", ".join(low_signal_hints) or "(none)"}.
- {batch_note}
- Return strict JSON only. No markdown fences, no explanation.

JSON schema:
{{
  "ok": true,
  "messages_scanned": 0,
  "threads_considered": 0,
  "threads_selected": 0,
  "low_signal_count": 0,
  "batch_lead": ["short bullet"],
  "publish_events": [
    {{
      "thread_id": "thread id",
      "message_ids": ["message id"],
      "received_at": "ISO-8601",
      "from_name": "sender name",
      "from_email": "sender@example.com",
      "sender_domain": "example.com",
      "subject": "email subject",
      "summary": "1-2 short sentences",
      "importance": 0.0,
      "categories": ["actionable"],
      "has_attachments": false,
      "attachment_count": 0,
      "internal_labels": ["{labels["polled"]}"],
      "telegram_topic": "{topic_name}"
    }}
  ],
  "label_actions": {{
    "{labels["polled"]}": ["message id"],
    "{labels["low_signal"]}": ["message id"]
  }},
  "model_meta": {{
    "model_id": "model id",
    "tier": "primary",
    "provider_fallback": false,
    "local_fallback": false
  }}
}}

Important:
- If there are no publishable events, return publish_events as [].
- If there are no low-signal messages, return "{labels["low_signal"]}": [].
- Do not invent IDs. Only include message_ids and thread_ids you actually observed.
"""


def build_commit_labels_prompt(*, inbox_ref: str, label_actions: dict[str, list[str]]) -> str:
    lines = [f"- {label}: {json.dumps(message_ids, ensure_ascii=False)}" for label, message_ids in label_actions.items()]
    actions = "\n".join(lines) if lines else "- no-op"
    return f"""Use only the AgentMail MCP tool `agentmail__update_message`. Apply internal labels to messages in inbox {inbox_ref}.

Hard rules:
- Add labels only. Do not remove labels.
- Do not mark messages read or unread.
- Do not send, draft, archive, forward, or reply.
- If a message already has the label, that is fine.
- Return strict JSON only.

Apply these labels:
{actions}

JSON schema:
{{
  "ok": true,
  "applied": {{
    "label/name": 0
  }},
  "model_meta": {{
    "model_id": "model id",
    "tier": "primary",
        "provider_fallback": false,
        "local_fallback": false
  }}
}}
"""


def build_digest_prompt(
    *,
    digest_type: str,
    topic_name: str,
    window_start: datetime,
    window_end: datetime,
    events: list[EmailEvent],
) -> str:
    compact_events = [
        {
            "event_id": event.event_id,
            "received_at": event.received_at,
            "from_name": event.from_name,
            "from_email": event.from_email,
            "sender_domain": event.sender_domain,
            "subject": event.subject,
            "summary": event.summary,
            "importance": round(event.importance, 3),
            "categories": event.categories,
            "has_attachments": event.has_attachments,
            "attachment_count": event.attachment_count,
        }
        for event in sorted(events, key=lambda item: item.importance, reverse=True)
    ]
    return f"""Prepare a high-level inbox-email recap for Telegram topic {topic_name}.

Digest type: {digest_type}
Window start: {window_start.isoformat()}
Window end: {window_end.isoformat()}

Use only the derived email events provided below. Do not read the mailbox, do not use external tools,
and do not repeat every item. The result should be a concise recap that highlights themes, actions,
watchpoints, and the few threads worth re-mentioning.

Return strict JSON only:
{{
  "ok": true,
  "title": "Inbox Email · Digest",
  "period_label": "08:00-13:00 MSK",
  "lead": ["top storyline"],
  "themes": ["cross-cutting theme"],
  "important_event_ids": ["event id"],
  "actions": ["follow-up or deadline"],
  "watchpoints": ["risk or reminder"],
  "low_signal_recap": "short note",
  "model_meta": {{
    "model_id": "model id",
    "tier": "primary",
    "provider_fallback": false,
    "local_fallback": false
  }}
}}

Derived events JSON:
{json.dumps(compact_events, ensure_ascii=False, indent=2)}
"""
