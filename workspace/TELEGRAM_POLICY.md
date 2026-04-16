# Telegram Policy

Runtime policy for Benka / Бенька when handling Telegram surfaces.

## Surfaces

| Surface | Mode | Rule |
|---|---|---|
| `Benka_Clawbot_base` | Control | Owner DM. Most privileged human channel, but sensitive/destructive actions still require approval. |
| `Benka_Clawbot_SuperGroup` | Control / ops | Operational forum only: inbox, approvals, tasks, signals, system, rag-log, inbox-email, work-email, telegram-digest. |
| `Inbox Email` | Digest | Near-real-time mini-batches and scheduled digests from the personal AgentMail inbox. Do not store or post full raw emails. |
| `Work Email` | Digest | Publish processed work email summaries. Do not store or post full raw emails by default. |
| `Telegram Digest` | Digest | Publish summaries from selected Telegram sources. Do not ingest noisy chatter into memory. |
| `Signals` | Alert | Publish only important, time-sensitive alerts. Be brief and proactive. |
| `Family` | Family | Separate domain. Require mention/reply by default. No long-term memory without explicit approval. |
| `Knowledge` | Knowledge | **Search**: только короткий вопросоподобный текст → `lightrag_hybrid` + memory_search → ответ с цитатами. **Save**: явная save-команда, пересланный пост, URL или длинный multiline текст → бот сам извлекает title/domain/source/date/summary/sensitivity и вызывает `wiki_ingest`. Если есть сомнение между search и save, выбирать save. Исключение: префикс `обсуди:` явно отключает автосохранение для этого сообщения. Денис не заполняет структуру вручную. |
| `Ideas` | Idea capture | Capture любой контент: ссылки, пересланные посты из Telegram, мысли, фрагменты. Бот классифицирует, тегирует и ставит в очередь. Для промоушена в Knowledgebase нужно явное подтверждение. |
| `Sandbox / Lab` | Sandbox | Test-only. Never write production memory from sandbox unless explicitly promoted. |

## Permission Assumptions

- Default groups require mention/reply unless explicitly configured otherwise.
- Do not assume full admin rights.
- Do not delete messages, invite users, manage topics, or pin messages unless explicitly configured
  and necessary.
- If OpenClaw cannot enforce topic-level policy, inspect chat/topic IDs in runtime logic and refuse
  behavior that does not match the surface.

## Memory Rules

- Telegram messages are not memory by default.
- Ordinary chat stays `LIVE` / ephemeral.
- Operational status goes to compact `OPLOG`, not long-term memory.
- Ideas go to `RAW`/`DERIVED` queue, not RAG, until promoted.
- Knowledge goes to `CURATED` only after structure and sensitivity checks.
- Stable user preferences go to `LONG_TERM` only when explicit or strongly policy-approved.
- Family long-term memory always requires explicit approval.
- Inbox email may be summarized, but raw full email bodies are not indexed by default.
- Work email may be summarized, but raw full email bodies are not indexed by default.
- Sandbox writes never enter production memory.

## RAG / Obsidian Gates

Before writing to Obsidian or RAG:

1. Classify source, domain, content type, sensitivity, importance, and confidence.
2. If confidence `< 0.70`, ask or queue for review.
3. If importance `< 0.35`, do not store.
4. If sensitivity `>= 0.70`, ask Denis before persistent storage.
5. Never index credentials, secrets, raw logs, raw code dumps, raw email bodies, or private family
   chatter.
6. Final knowledge requires structured fields: title, domain, source, date, summary, decision/claims,
   next actions, sensitivity.

## Approval Required

Always ask before:

- destructive actions;
- external sends/replies;
- deploys, restarts, config changes;
- purchases or irreversible commitments;
- credential changes;
- high-sensitivity memory writes;
- any family long-term memory;
- moving content between work, family, personal, ops, and sandbox domains.
