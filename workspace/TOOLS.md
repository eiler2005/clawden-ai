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
- Obsidian vault: внешний AI Wiki, книги/статьи, проектные и личные заметки

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
