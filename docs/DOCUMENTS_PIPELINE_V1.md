# Documents pipeline v1 (LLM → PDF → S3 → list/download)

## Что это
Pipeline генерирует пользовательские PDF-документы на основе `brief_state` (полученного в интро-диалоге):
1) LLM возвращает JSON `{doc_markdown, missing_fields, quality_notes}`
2) сервис `render` конвертирует markdown → PDF (`POST /render/pdf`)
3) PDF кладётся в S3/MinIO
4) пользователь видит документ в `/me/documents` и может скачать

## Основные API
- `POST /sessions` → создаёт сессию (пишет `profession_query`)
- `POST /chat/message`:
  - `type=intro_start` → старт интро
  - `type=intro_message` → шаг интро
- `GET /documents/catalog` → список доступных документов (с `sort_order` и `required_fields`)
- `POST /documents/generate` → синхронная генерация: LLM → render → S3
- `GET /me/documents` → объединённый список (intro artifacts + pdf)
- `GET /documents/{id}/download` → скачивание PDF (stream)
- `POST /documents/{id}/retry` → повтор только для `status=error`

## Переменные окружения (минимум)
- `S3_BUCKET` — bucket для PDF
- `S3_ENDPOINT_URL` или `S3_ENDPOINT` — endpoint MinIO/S3
- `RENDER_URL` — URL сервиса рендера (по умолчанию `http://render:8000`)
- LLM:
  - `LLM_PROVIDER=openai_compat` (иначе в `docker compose` по умолчанию будет `mock`)
  - `OPENAI_API_KEY` или `OPENROUTER_API_KEY` (и опционально `LLM_MODEL`)
  - (опционально) `LLM_BASE_URL` если нужен не-дефолтный endpoint

## Проверка руками (через curl)
Ниже используется header-based идентификация пользователя.

1) Создать пользователя и сессию:
- `export UID=$(uuidgen)`
- `curl -s -H "X-User-Id: $UID" -H "Content-Type: application/json" \
  -d '{"profession_query":"Python разработчик"}' \
  http://localhost:8000/sessions`

2) Старт интро:
- `curl -s -H "X-User-Id: $UID" -H "Content-Type: application/json" \
  -d '{"session_id":"<SESSION>","type":"intro_start"}' \
  http://localhost:8000/chat/message`

3) Пройти несколько сообщений `intro_message` до `ready_to_search=true`.

4) Взять первый документ из каталога:
- `curl -s http://localhost:8000/documents/catalog | jq`

5) Сгенерировать документ:
- `curl -s -H "X-User-Id: $UID" -H "Content-Type: application/json" \
  -d '{"session_id":"<SESSION>","doc_id":"search_brief"}' \
  http://localhost:8000/documents/generate | jq`

Ожидаемо:
- `status=ready` и `download_url` заполнен
- при недостающих данных: `status=needs_input` и `missing_fields`
- при сбоях LLM/render/S3: `status=error` и `error_code`

6) Скачать PDF:
- `curl -L -H "X-User-Id: $UID" \
  -o out.pdf \
  http://localhost:8000/documents/<DOC_ID>/download`

7) Проверить список:
- `curl -s -H "X-User-Id: $UID" http://localhost:8000/me/documents | jq`

## Smoke-тест (e2e через docker compose)
- Запускает полный флоу через фронтовые прокси `/api/*`: `sessions → intro → documents/generate → download → me/documents`
- По умолчанию использует `LLM_PROVIDER=mock` (без внешних ключей), но проверяет всю цепочку: render → S3 → download.

Команда:
- `scripts/smoke-documents-v1.sh`

## DoD (Definition of Done)
- Генерация по `/documents/generate` не отдаёт наружу 500 при сбоях LLM/render/S3 (возвращает `ok=true` + `status=error|needs_input`)
- Идемпотентность: повторный `generate` с теми же входными данными возвращает существующую запись
- `download` стримит PDF из S3 и требует ownership (user_id)
- `retry` работает только для `status=error` и запрещён, если `source_hash` устарел
- Минимальная интеграция UI: после интро-готовности запускается генерация первого документа и доступна кнопка «Скачать»
