# Knowledge Management: Ideas + Knowledgebase

Система управления знаниями построена на двух топиках в `Ben'ka_Clawbot_SuperGroup` и трёх бэкендах хранения.

---

## Архитектура

```
Любой источник
  │
  ├─► 💡 Ideas (topic_id=639)        ← быстрый захват, без структуры
  │     │ авто-захват + теги
  │     │ промоушен по команде
  │     ▼
  └─► 📚 Knowledgebase (topic_id=232) ← база знаний
        │ поиск (вопрос → ответ с цитатами)
        │ сохранение (любой контент → авто-структура)
        ▼
   wiki-import bridge
        │
        ├─► Obsidian vault (wiki/**/*.md)   — читаемая база
        ├─► LightRAG index                  — поиск (граф + вектор)
        └─► workspace memory                — контекст агента
```

---

## 💡 Ideas — захват без усилий

**Что кидать:**
- Пересланные посты из Telegram-каналов
- Ссылки на статьи, видео, документы
- Мысли, фрагменты, черновые тезисы
- Скриншоты с подписью

**Как работает (автоматически):**
1. Бенька читает всё в топике без упоминания
2. Извлекает суть, присваивает теги (domain, source_type)
3. Оценивает важность; если < 0.35 — молча игнорирует
4. Добавляет в очередь (RAW/DERIVED, вне RAG)
5. Отвечает кратко: `✅ Захвачено: [тема]. Тег: [domain]`

**Промоушен в Knowledgebase:**
```
Бенька, промоутни лучшее из Ideas за эту неделю
Бенька, сохрани последний пост в базу знаний
Бенька, добавь это в knowledgebase (в ответ на конкретный пост)
```
Бот покажет список и попросит подтверждение перед записью.

**Что НЕ происходит автоматически:**
- Контент НЕ уходит в RAG/Obsidian без промоушена
- Бот НЕ пишет длинный анализ на каждый пост

---

## 📚 Knowledgebase — поиск и хранение

### Режим 1: Поиск

Напиши любой вопрос открытым текстом:

```
почему выбрали LightRAG?
что знаем про Syncthing?
как работает signals-bridge?
расскажи про eb1 визу
```

Бенька ищет по трём источникам одновременно:
- `LightRAG hybrid` — граф + вектор (workspace + Obsidian wiki + signals)
- `memory search` — BM25 + Gemini (быстрый recall)

Формат ответа:
```
🔍 Запрос: «почему выбрали LightRAG»

📌 1. entities/lightrag.md (91%)
LightRAG выбран за гибридный поиск (вектор + граф знаний)...
Источник: wiki/entities/lightrag.md

📌 2. decisions/2026-03-lightrag.md (78%)
Решение принято в марте 2026, альтернативы: Weaviate, Qdrant...
Источник: workspace/raw/...
```

### Режим 2: Сохранение знания

Пересылай пост, кидай ссылку или пиши текст — **никакой ручной структуры не нужно**.

Бот сам извлекает: title, domain, source, date, summary, sensitivity — и вызывает `wiki_ingest`.

```
[пересланный пост из канала]
→ ✅ Сохранено: «Новые возможности Claude 4» → AI/LLM

https://some-article.com/interesting
→ ✅ Сохранено: «Статья про X» → AI/research

просто текст который хочу запомнить
→ ✅ Сохранено: «Личная заметка» → personal
```

Бот инжестит в Obsidian wiki → LightRAG (переиндексация через 30 мин).

---

## Полный флоу: от поста до базы знаний

```
1. Видишь интересный пост в Telegram
   │
   ▼
2. Пересылаешь в 💡 Ideas
   (без комментария — работает само)
   │
   ▼
3. Бенька: ✅ Захвачено: [тема]. Тег: AI/LLM
   │
   ▼
4. Когда удобно (хоть через неделю):
   «Бенька, промоутни лучшее из Ideas»
   │
   ▼
5. Бенька показывает список захваченного,
   ты говоришь «да» / «нет» / «вот этот»
   │
   ▼
6. wiki_ingest → Obsidian wiki → LightRAG index
   │
   ▼
7. Через 30 мин поиск находит это в 📚 Knowledgebase
```

---

## Источники данных для поиска

| Источник | Путь | Обновление |
|---|---|---|
| Obsidian wiki | `/opt/obsidian-vault/wiki/**/*.md` | Syncthing + LightRAG cron 30 мин |
| Workspace memory | `/opt/openclaw/workspace/*.md` | Deploy workspace |
| Signals/digests | `/opt/obsidian-vault/raw/signals/**/*.md` | Telethon Digest → LightRAG cron |
| Ideas (после промоушена) | → wiki/ | wiki-import bridge |

---

## Команды быстрого доступа

| Команда | Где | Что делает |
|---|---|---|
| Любой вопрос | 📚 Knowledgebase | Поиск по всей базе |
| Любой пост / ссылка / текст | 📚 Knowledgebase | Авто-структура + сохранение в wiki |
| Любой пост / ссылка / текст | 💡 Ideas | Авто-захват в очередь |
| `Бенька, промоутни из Ideas` | inbox / DM | Пакетный промоушен с подтверждением |
| `Бенька, что в очереди Ideas?` | inbox / DM | Показать накопленное |

---

## Связанные документы

- [docs/10-memory-architecture.md](10-memory-architecture.md) — классы памяти (RAW/DERIVED/CURATED)
- [docs/11-lightrag-setup.md](11-lightrag-setup.md) — LightRAG API и индексация
- [docs/15-llm-wiki-query-flow.md](15-llm-wiki-query-flow.md) — как работает поиск внутри
- [docs/12-telegram-channel-architecture.md](12-telegram-channel-architecture.md) — все Telegram-поверхности
