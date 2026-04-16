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

### knowledge_channel — топик Knowledgebase (topic_id=232)

Два режима. Определять автоматически по намерению сообщения.

Правило приоритета:
1. Явная команда сохранения (`сохрани`, `добавь в базу`, `запомни это`) → **Save**
2. Пересланный пост / сообщение с URL / длинный multiline текст → **Save**
3. Только короткий вопросоподобный текст → **Search**
4. Если есть сомнение между `Search` и `Save`, в `Knowledgebase` выбирать **Save**, а не conversational reply
5. Если пользователь явно пишет префикс `обсуди:`, не сохранять автоматически; это запрос на обсуждение без ingest

**Режим 1 — Поиск** (если сообщение выглядит как вопрос):
Признаки: короткий вопросоподобный текст; содержит `?` или начинается с «что», «как», «почему», «расскажи», «кто», «когда», «где», «объясни».
Не использовать `Search`, если это пересланный пост, длинный тезисный блок, заметка в несколько абзацев или сообщение с явным URL для сохранения.
Если сообщение начинается с `обсуди:`, отвечать как на обычный диалог и не запускать `wiki_ingest`, пока Денис отдельно не попросит сохранить.

1. Вызвать `lightrag_query(query, mode="hybrid")`
2. Дополнительно использовать встроенный memory search
3. Ответить в канал:

```
🔍 Запрос: «{query}»

📌 1. {source_title} ({relevance}%)
{snippet — 1-2 предложения}
Источник: {file_path}

📌 2. ...
_(если ничего нет: «Ничего не найдено. Попробуй другие ключевые слова.»)_
```

**Режим 2 — Сохранение** (если сообщение выглядит как контент для сохранения):
Признаки: пересланный пост, URL, длинный текст, явная команда «сохрани», «добавь в базу».

Денис НЕ заполняет структуру вручную. Бот сам:
1. Прочитать контент (текст + источник пересылки если есть)
2. Автоматически извлечь поля:
   - `title` — краткое название (1 строка)
   - `domain` — тематика (AI, finance, ops, личное, ...)
   - `source` — откуда (канал/автор/URL если есть, иначе «personal note»)
   - `date` — сегодня если не указана явно
   - `summary` — суть в 2-4 предложениях
   - `sensitivity` — low (по умолчанию), medium/high если чувствительное
3. Если есть надёжный canonical URL статьи/поста — предпочесть `wiki_ingest({source_type: "url", source: "https://..."})`
4. Иначе вызвать `wiki_ingest({source_type: "text", source: "[извлечённый markdown]"})`
5. Ответить кратко: `✅ Сохранено: [title] → [domain]`

Если содержание слишком короткое или непонятное (<0.35 importance) — уточнить у Дениса одним вопросом.
Не давать сначала длинный содержательный комментарий на такой пост. В `Knowledgebase` при save-intent сначала ingest + короткое подтверждение, и только потом при отдельной просьбе обсуждение.
Pinned UX для топика должен явно объяснять это правило: длинный контент здесь сохраняется по умолчанию; для разговора без сохранения использовать префикс `обсуди:`.

### ideas_capture — авто-захват контента в топике Ideas

Любое сообщение в топике `💡 Ideas` (topic_id=639) обрабатывается автоматически — без команды, без упоминания.

Что принимать:
- Пересланные посты из любых Telegram каналов/чатов
- Ссылки (статьи, твиты, видео, docs)
- Сырой текст, мысли, фрагменты
- Скриншоты с подписью

Что делать при получении:
1. Извлечь суть: о чём, откуда, ключевые тезисы
2. Присвоить теги (domain, topic, source_type)
3. Оценить важность (0.0–1.0); если < 0.35 — игнорировать молча
4. Добавить в очередь (RAW/DERIVED, no rag_index, no obsidian_sync)
5. Ответить кратко: `✅ Захвачено: [тема]. Тег: [domain]. Очередь: +1`

Промоушен в Knowledgebase:
- Только по явной команде Дениса: «промоутни», «сохрани в базу», «добавь в knowledgebase»
- Перед промоушеном запросить подтверждение
- При промоуте использовать самый короткий write-path:
  - если у элемента есть исходный URL → `wiki_ingest({source_type: "url", source: "<url>"})`
  - если URL нет, но есть внятный текст/пересланное сообщение → `wiki_ingest({source_type: "text", source: "[извлечённый markdown]"})`
- Queue listing, confirmation и promotion — это `medium` или прямой deterministic workflow, не `smart`, если Денис не просит глубокий разбор

НЕ делать:
- Не промоутить автоматически без явной команды
- Не сохранять в RAG/Obsidian до промоушена
- Не отвечать на каждый пост длинным анализом — только краткое подтверждение захвата

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
