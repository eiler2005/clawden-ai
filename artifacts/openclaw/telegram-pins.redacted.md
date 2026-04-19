# Telegram Pinned Messages

Canonical text templates for forum-topic pinned messages in `Ben'ka_Clawbot_SuperGroup`.

Use these when re-posting or refreshing topic instructions via Telegram Bot API.
Machine-readable source files:

- `artifacts/openclaw/telegram-pins/knowledgebase.txt`
- `artifacts/openclaw/telegram-pins/ideas.txt`

---

## Knowledgebase

```text
📚 Knowledgebase — база знаний

Что сюда кидать:
- любой пересланный пост
- ссылку на статью / видео / документ
- длинную заметку или тезисы
- вопрос, если хочешь поиск по базе

Как это работает:
- короткий вопрос → я ищу по wiki + workspace + signals
- по умолчанию это локальный поиск по базе; интернет ищу только если ты явно просишь: `поищи в интернете`
- пересланный пост / URL / длинный текст → я считаю это сохранением в базу

Чтобы точно сохранить:
- просто пришли пост / ссылку / текст сюда
- или явно напиши: «сохрани в базу»

Ответ, если всё хорошо:
✅ Сохранено в wiki: [название]
Страница: wiki/research/[slug].md
LightRAG: queued / indexed / delayed

Если хочешь не сохранять, а только обсудить:
- начни сообщение с `обсуди:`

Если сомневаюсь между «обсудить» и «сохранить», выбираю сохранение 🙂 
```

---

## Ideas

```text
💡 Ideas — захват без усилий

Что сюда кидать:
- пересланные посты
- ссылки
- мысли, черновики, фрагменты

Что происходит:
- я захватываю суть
- ставлю теги
- создаю страницу в wiki/research/ с light curation

Ответ:
✅ Захвачено в wiki: [тема]
Страница: wiki/research/[slug].md

Это уже видно в wiki, но более глубокая canonical curation делается при promotion.

Чтобы потом сохранить лучшее:
- «промоутни из Ideas»
- «сохрани последний пост в базу»

Если хочешь сразу в базу, кидай сразу в 📚 Knowledgebase 🙂
```
