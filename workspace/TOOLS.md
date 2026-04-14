# Tools

## Инструменты Бенька (workspace)

- Чтение и запись файлов (только в пределах workspace)
- Поиск по памяти (BM25 + semantic, если включён)
- Веб-фетч (внешние URL по запросу)
- Выполнение кода (по явному разрешению)

### lightrag_query — поиск по базе знаний

Использовать вместо прямого чтения архивных дневников и raw/.
Один вызов ~2KB ответа vs загрузка MB истории.

Что там лежит:
- workspace markdown: identity, tools, memory, daily notes, raw decision records
- Obsidian vault: `wiki/**/*.md` и `raw/signals/**/*.md`

Как обновляется:
- Syncthing кладёт Obsidian markdown на сервер
- workspace deploy кладёт bot markdown в `/opt/openclaw/workspace`
- cron каждые 30 минут запускает `/opt/lightrag/scripts/lightrag-ingest.sh`
- ingest делает `POST /documents/upload`, затем `POST /documents/reprocess_failed`

```
POST http://lightrag:9621/query
Content-Type: application/json

{"query": "почему выбрали PostgreSQL вместо Redis", "mode": "hybrid"}
```

Режимы: `hybrid` (рекомендован) · `local` (граф) · `global` (векторный)

Health-check: `GET http://lightrag:9621/health`

**Важно:** результаты LightRAG — Derived-уровень. Не использовать для ответов о текущем состоянии системы.
Если вопрос влияет на решение, открыть `references[].file_path` и проверить источник.

### Obsidian vault

Путь на сервере: `/opt/obsidian-vault/` (монтируется в LightRAG read-only)
Синхронизация: Syncthing bidirectional sync
Re-index: после bulk-изменений запустить `scripts/lightrag-ingest.sh`

### wiki_read — чтение wiki page

Read-only fetch страницы из `wiki/` по относительному пути.

Пример:
`wiki_read("entities/lightrag.md")`

Когда использовать:
- после `lightrag_query`, чтобы открыть 3–5 самых релевантных wiki-страниц
- для проверки `INDEX.md`, `OVERVIEW.md`, `TOPICS.md`, `SCHEMA.md`

### wiki_ingest — curated import trigger

Оркестрационный вызов во внутренний `wiki-import` bridge.
Сам OpenClaw не пишет в vault напрямую; bridge:
- принимает `source_type: url | text | server_path`
- сохраняет нормализованный source в `raw/articles/` или `raw/documents/`
- сначала canonicalizes identity через `CANONICALS.yaml`
- затем назначает `themes` и обновляет `TOPICS.md`
- обновляет wiki pages, `INDEX.md`, `OVERVIEW.md`, `TOPICS.md`, `LOG.md`

Примеры:
- `wiki_ingest({"source_type":"url","source":"https://..."})`
- `wiki_ingest({"source_type":"text","source":"...markdown/text..."})`
- `wiki_ingest({"source_type":"server_path","source":"/opt/obsidian-vault/raw/documents/file.pdf"})`

### wiki_lint — health check for wiki

Триггер во внутренний `wiki-import` bridge.
Проверяет:
- duplicate basenames / duplicate-token slugs
- source-title-as-entity mistakes
- alias collisions
- missing themes / canonical drift
- stale pages
- empty sections
- missing cross-links
- hub candidates
- queue / index / topics consistency

Возвращает markdown report и агрегированные счётчики.

## Инструменты Дениса (внешние, для контекста)

**AI / Разработка**
- Claude Code — основной AI для разработки и архитектуры
- Cursor — IDE с AI
- ChatGPT — резервный, эксперименты
- Gemini CLI
- Google AI Studio

**Прототипирование**
- Lovable, v0.dev — vibe-coding, быстрые UI-прототипы

**Аналитика / Визуализация**
- Draw.io, PlantUML — архитектурные диаграммы
- Postman — тестирование API

**Управление**
- Jira, Confluence
- Git / Bash

## Стек интересов Дениса (полезно для рекомендаций)

Kafka · Kubernetes · Camunda BPM · WSO2 API Manager · Yandex AI Studio · PostgreSQL · Redis · Elasticsearch · Java · Python · React · Docker
