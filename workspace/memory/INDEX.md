# Daily Memory Index

Index of daily conversation logs. Read this before loading any daily file.

## Active Files

<!-- Bot maintains this list. Format: | date | topics | key decisions | -->

| Date | Topics | Key decisions / notes |
|------|--------|----------------------|
| _(none yet)_ | — | — |

## Archive

Files older than 14 days are moved to `memory/archive/`.

| Period | Archive path | Summary |
|--------|-------------|---------|
| _(none yet)_ | — | — |

---

## Load Policy

1. Check this INDEX first (1KB) — don't scan the folder blindly
2. Load today's file if the topic is relevant
3. Load yesterday's file only if today has <3 entries
4. Files older than 7 days → use `lightrag_query` instead
5. Files in archive/ → use `lightrag_query` only, never load directly

---

## Compression Schedule

| Age | Action |
|-----|--------|
| 1–7 days | Full verbatim daily note |
| 8–14 days | Bot compresses to 5-line summary, replaces note in-place |
| 15+ days | Summary moves to `archive/`, INDEX entry updated |

Compression is triggered during weekly HEARTBEAT check — not per-message.

---

## Entry Format for Daily Notes

Each daily note (`YYYY-MM-DD.md` or `YYYY-MM-DD-{topic}.md`) uses this structure:

```markdown
# Session Log: YYYY-MM-DD [topic]

## Decisions
- [DECISION] X chosen over Y. Reason: Z.

## Key Facts
- [FACT] New infrastructure entity / preference / constraint discovered.

## Open Items
- [TODO] Something unresolved, carry forward.

## Root Causes / #canon
- [CANON] Root cause or architectural truth. Tag: #canon
```

Max 3 lines per entry. No prose. Compress at write time.
