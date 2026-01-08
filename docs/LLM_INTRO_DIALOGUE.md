# PR-LLM-INTRO-DIALOGUE

## Цель
Добавить в backend LLM-управляемый «вводный диалог», который собирает бриф пользователя (role/goal/constraints) и сохраняет результат в БД.

Флоу **опциональный** и не ломает текущий сценарий Stage 3/5 (vacancy/tasks/clarifications).

## API

### POST /sessions
Тело:
```json
{
  "profession_query": "string",
  "flow": "intro" 
}
```
- Если `flow=intro`, сессия помечается как intro (`chat_state=intro`, `phase=INTRO`, `brief_state={}`).

Ответ:
```json
{ "session_id": "uuid" }
```

### POST /chat/message
Для intro используются типы:
- `intro_start` — начать intro и получить первый вопрос
- `intro_message` — следующий ответ пользователя

Пример:
```json
{ "session_id": "...", "type": "intro_start" }
```

Ответ (ключевые поля):
```json
{
  "ok": true,
  "assistant_text": "...",
  "quick_replies": ["..."],
  "brief_state": {"...": "..."},
  "ready_to_search": false,
  "missing_fields": ["role", "goal", "constraints"],
  "documents_ready": false,
  "documents": []
}
```

Если `ready_to_search=true`, backend сохраняет артефакт `intro_brief` в таблицу `artifacts`.

### GET /me/documents
Авторизация: обязательна (Bearer или `X-User-Id`).

Возвращает список документов intro для текущего пользователя:
```json
{
  "ok": true,
  "documents": [
    {
      "id": "uuid",
      "session_id": "...",
      "kind": "intro_brief",
      "title": "Бриф поиска",
      "payload": {"title": "Бриф поиска", "brief_state": {}}
    }
  ]
}
```

## Промпты
- `api/prompts/intro_system.md`
- `api/prompts/intro_user_template.md`

Важно: промпты не логируются; логируется только размер.

## Переменные окружения (OpenRouter)
Поддерживается OpenAI-совместимый режим:
- `LLM_PROVIDER=openai_compat`
- `LLM_BASE_URL=https://openrouter.ai/api/v1` (или иной совместимый)
- `OPENROUTER_API_KEY=...` (или `LLM_API_KEY=...`)
- `LLM_MODEL=...`

`OPENROUTER_API_KEY` используется как fallback, если `LLM_API_KEY` пуст.

## Устойчивость
Если LLM недоступна/вернула невалидный JSON — backend возвращает fallback-вопрос и **не падает 500**.
