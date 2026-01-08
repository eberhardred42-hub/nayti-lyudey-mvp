# OpenRouter (LLM)

Цель: включить реальный LLM через OpenRouter на stage/prod без ручного SSH.

## ENV контракт

В API поддерживается провайдер:

- `LLM_PROVIDER=openrouter`

Параметры:

- `OPENROUTER_API_KEY` (секрет)
- `OPENROUTER_BASE_URL` (default `https://openrouter.ai/api/v1`)
- `OPENROUTER_MODEL` (default `xiaomi/mimo-v2-flash:free`)
- `OPENROUTER_FALLBACK_MODELS` (csv, опционально; default `nvidia/nemotron-3-nano-30b-a3b:free`)
- `OPENROUTER_HTTP_REFERER` (default `https://naitilyudei.ru`)
- `OPENROUTER_APP_TITLE` (default `nayti-lyudey`)

Общие лимиты:

- `LLM_TIMEOUT_S` (default `20`)
- `LLM_MAX_TOKENS` (default `600`)

Важно: для OpenRouter мы отправляем рекомендованные заголовки `HTTP-Referer` и `X-Title`.

## Как включить на stage

1) В GitHub репозитории добавьте секрет:

- `OPENROUTER_API_KEY`

2) (Опционально) добавьте GitHub Variables:

- `OPENROUTER_MODEL`
- `OPENROUTER_FALLBACK_MODELS`

3) Сделайте deploy на stage (workflow `Stage Deploy`).

Проверка:

- `GET https://naitilyudei.ru/api/health/llm`

Ожидаемо (пример):

```json
{"ok": true, "provider": "openrouter", "model": "xiaomi/mimo-v2-flash:free", "base_url": "https://openrouter.ai/api/v1"}
```

Если ключ не задан/недоступен, сервис не падает: `health/llm` вернёт `ok:false`, а UI будет деградировать до шаблонных вопросов.

## Важное предупреждение

Free-endpoint’ы у OpenRouter могут логировать промпты/ответы. Для stage это приемлемо, но для реальных чувствительных данных лучше перейти на платную модель или другой провайдер.
