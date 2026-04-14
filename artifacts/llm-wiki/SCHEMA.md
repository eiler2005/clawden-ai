# LLM-Wiki Schema
_The CLAUDE.md of the wiki. Read this before any wiki operation._

---

## Philosophy

The wiki is a **persistent, accumulating artifact**. Unlike plain RAG, every ingest should make the
knowledge base structurally better: more canonical, more cross-linked, and easier to navigate.

Three-layer principle:
- `raw/` — immutable source drops; read-only for the bot
- `wiki/` — curated, bot-maintained markdown knowledge base
- `SCHEMA.md` — human-authored contract the bot must follow

Operational model:
- humans source and inspect
- the bot writes and maintains the wiki
- the wiki is the durable artifact
- LightRAG is the retrieval layer on top of the wiki, not the source of truth

Karpathy-style principle:
- typed pages remain the storage backbone
- thematic navigation is layered on top through metadata and topic maps
- useful answers and syntheses can be filed back into the wiki as new research pages

---

## System Files

Bot-owned system files inside `wiki/`:
- `SCHEMA.md` — conventions and workflows
- `CANONICALS.yaml` — canonical slug and alias registry
- `OVERVIEW.md` — compact cold-start summary
- `TOPICS.md` — thematic navigator
- `INDEX.md` — full page registry
- `IMPORT-QUEUE.md` — curated import queue
- `LOG.md` — append-only operations log

Humans should not manually edit bot-owned system files except `SCHEMA.md`.

---

## Page Types

| Type | Folder | Purpose |
|------|--------|---------|
| `entity` | `entities/` | Named systems, tools, people, projects, orgs, services |
| `concept` | `concepts/` | Ideas, patterns, frameworks, technical concepts |
| `decision` | `decisions/` | ADR-style records for important choices |
| `session` | `sessions/` | Session or operational notes |
| `research` | `research/` | Source-centric or synthesis-heavy analysis pages |

Primary organization is by page type.  
Themes are a **secondary navigation layer**, not a replacement for typed folders.

---

## Canonical Identity Rules

`CANONICALS.yaml` is the machine-readable registry for core identities.

Each canonical record defines:
- `slug`
- `type`
- `subtype`
- `name`
- `aliases`
- `tags`
- `themes`
- `preferred_folder`

Resolution order for importer:
1. exact slug match
2. exact alias match
3. normalized alias match
4. existing page frontmatter aliases
5. heuristic fallback

Rules:
- known core systems should resolve to canonical slugs first
- aliases belong in frontmatter and in `CANONICALS.yaml`
- importer must update canonical pages instead of creating near-duplicates
- heuristic fallback is only for unknown entities/concepts

---

## Slug and Naming Rules

Global rule:
- **basename must be unique across the entire wiki**, not only inside a folder

Naming conventions:
- canonical entity page: `entities/<canonical-slug>.md`
- concept page: semantic slug; if collided, use `-concept`
- research page: source/topic-centric slug; if collided, use `-research`
- decision page: ADR-style verb-led slug; do not use `imported-*`

Forbidden outcomes:
- duplicate-token slugs like `openclaw-openclaw`
- entity pages created from document-title artifacts such as `README`, `Setup and Operations`, `Architecture and Security`
- parallel `entity` / `concept` / `research` pages with the same basename

When a collision exists, keep the canonical anchor and rename the non-canonical page.

---

## Frontmatter Specification

### Entity page

```yaml
---
type: entity
subtype: tool           # tool | person | project | org | service
name: <Human-readable name>
aliases: [Alias1, Alias2]
status: active          # active | deprecated | archived
confidence: CONFIRMED   # CONFIRMED | INFERRED | AMBIGUOUS
hub: false
tags: [tag1, tag2]
themes: [runtime, wiki]
related:
  - research/some-research.md
updated: YYYY-MM-DD
---
```

### Concept page

```yaml
---
type: concept
name: <Human-readable name>
aliases: [Alias1, Alias2]
confidence: CONFIRMED
hub: false
tags: [tag1, tag2]
themes: [memory, retrieval]
related:
  - entities/some-entity.md
updated: YYYY-MM-DD
---
```

### Decision page

```yaml
---
type: decision
name: <Decision title>
date: YYYY-MM-DD
status: closed          # open | closed | revisited
confidence: CONFIRMED
tags: [infra, decisions]
themes: [operations, retrieval]
related:
  - entities/some-entity.md
updated: YYYY-MM-DD
---
```

### Session page

```yaml
---
type: session
date: YYYY-MM-DD
confidence: CONFIRMED
tags: [session, operational]
---
```

### Research page

```yaml
---
type: research
name: <Research title>
confidence: CONFIRMED
tags: [tag1, tag2]
themes: [wiki, memory]
related:
  - concepts/some-concept.md
updated: YYYY-MM-DD
---
```

Rules:
- every non-session page must have `themes`
- entity and concept pages must support `aliases`
- keep frontmatter flat and simple for Obsidian Properties / Bases compatibility

---

## Thematic Navigation

Controlled theme vocabulary:
- `runtime`
- `memory`
- `wiki`
- `retrieval`
- `signals`
- `routing`
- `sync`
- `security`
- `operations`

Rules:
- every non-session page gets 1–3 themes
- themes are chosen from the controlled vocabulary only
- canonical entities get stable themes from `CANONICALS.yaml`
- research pages may be source-centric, but must still have thematic placement

`TOPICS.md` is the bot-maintained thematic navigator.

Per theme it should show:
- anchor entities
- core concepts
- active decisions
- key research / synthesis pages

Do not introduce domain folders for themes; use metadata and topic maps instead.

---

## Relationship Tagging

Every claim in `Connections` should carry explicit confidence when needed:

| Marker | Meaning |
|--------|---------|
| _(no marker)_ | CONFIRMED |
| `(INFERRED)` | Reasonable synthesis, not directly stated |
| `(AMBIGUOUS)` | Conflicting or unresolved evidence |

Example:

```markdown
## Connections
- **Powers:** [[lightrag]] — graph+vector retrieval for the wiki
- **Alternative to:** plain RAG (INFERRED: persistent compilation is more valuable for this vault)
- **Integrates with:** [[omniroute]] (AMBIGUOUS: direct or gateway-mediated path unclear)
```

---

## Hub Rule

A hub page is any page with 5 or more incoming `[[wikilinks]]`.

Rules:
- lint sets `hub: true` when threshold is crossed
- hub pages appear in `INDEX.md`, `OVERVIEW.md`, and relevant sections of `TOPICS.md`
- hubs are graph properties, not a separate page type or folder

---

## Cross-Linking Rules

1. Link on first mention inside a section.
2. Use canonical slug, not prose title.
3. Do not over-link repeated mentions.
4. Link pages, not folders.
5. If an important entity/concept is mentioned and no page exists, create or update the canonical page.

The canonical slug should win over temporary or source-title slugs.

---

## Ingest Workflow

Trigger:
- `wiki_ingest(...)`
- or curated processing of a new source in `raw/`

Steps:
1. Read the source in full.
2. Resolve canonical entities first using `CANONICALS.yaml` and existing aliases.
3. Update canonical entity pages.
4. Create or update one source-centric `research/` page.
5. Create or update concepts only if they are real concepts, not aliases or document-title artifacts.
6. Create a decision page only for explicit ADR-like material.
7. Add cross-links and themes.
8. Update hub flags.
9. Rebuild `INDEX.md`, `OVERVIEW.md`, `TOPICS.md`.
10. Append to `LOG.md`.

Rule of thumb:
- one source should usually touch multiple pages
- canonical pages should get better over time
- a source should not produce duplicate entity families

---

## Query Workflow

Trigger:
- user asks the bot a historical or knowledge question

Steps:
1. Start from `OVERVIEW.md` or `TOPICS.md` to orient quickly.
2. Use `INDEX.md` when full registry-level navigation is needed.
3. Use `lightrag_query(..., mode="hybrid")` for retrieval.
4. Read 3–5 relevant wiki pages directly.
5. Synthesize the answer with citations.
6. If the answer creates a durable new synthesis, save it as `research/`.

Good answers can become new research pages instead of disappearing into chat history.

---

## Lint Workflow

Trigger:
- weekly cron
- or manual `wiki_lint()`

Checks:
1. duplicate basenames
2. duplicate-token slugs
3. source-title-as-entity mistakes
4. alias collisions
5. missing themes
6. broken canonical references
7. stale pages
8. missing links
9. hub candidates
10. empty sections
11. `TOPICS.md` drift

`repair=true` may:
- merge duplicate canonical entities
- rewrite wiki links to canonical slugs
- rename colliding concept/research pages
- remove low-signal auto-generated decision pages
- normalize aliases/themes
- rebuild `INDEX.md`, `OVERVIEW.md`, `TOPICS.md`

---

## INDEX.md Protocol

Rules:
- one row per page
- no duplicate basenames
- always link page names with relative markdown links
- list system pages at the top
- keep hub section current

---

## OVERVIEW.md Protocol

Purpose:
- cold-start summary small enough to read every session

Sections:
- `Active Focus`
- `Active Themes`
- `Hub Pages`
- `Active Decisions`
- `Recent Updates`
- `Import Queue`

Rules:
- keep compact
- prefer signal over exhaustiveness
- dedupe by canonical basename

---

## TOPICS.md Protocol

Purpose:
- human-readable thematic navigation layer

For each controlled theme, list:
- anchor entities
- core concepts
- active decisions
- research and synthesis pages

Rules:
- build from page metadata
- do not invent ad-hoc themes outside the controlled vocabulary
- keep canonical anchors visible

---

## IMPORT-QUEUE.md Protocol

Storage format:
- JSON array wrapped inside the `wiki-import-queue` markers
- one object per source fingerprint

Fields:
- `fingerprint`
- `status`
- `source_type`
- `target_kind`
- `title`
- `source`
- `raw_path`
- `research_path`
- `updated`
- `error`

Queue is bot-owned. Re-import updates the existing entry instead of creating a duplicate.

---

## LOG.md Protocol

Format:

```markdown
## [YYYY-MM-DD] <operation> | <source title or description>
Source: <URL or file path or "manual">
Pages created: page1.md, page2.md
Pages updated: page3.md, INDEX.md
Key insight: <one sentence>
```

Operations:
- `ingest`
- `lint`
- `query-saved`
- `migration`

Rules:
- append only
- one block per operation
- keep the insight concise and specific

---

## Obsidian Integration Notes

- frontmatter becomes Obsidian Properties
- aliases help with unlinked mentions and backlinks
- `[[wikilinks]]` drive graph view
- themes can later back Obsidian Bases / Dataview views
- humans should browse and inspect the wiki in Obsidian, but bot-owned system files stay bot-maintained
