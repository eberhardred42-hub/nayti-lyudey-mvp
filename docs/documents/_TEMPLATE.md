# <doc_id> — <title>

## Purpose

- Что это за документ для пользователя.
- Что именно сейчас делает реализация (если это заглушка — явно указать).

## Input schema

Минимально (по факту текущей реализации):
- `pack_id`: UUID (строка)
- `doc_id`: строка
- `session_id`: UUID (строка) — берётся из пака
- Render request (то, что уезжает в очередь worker’у):
  - `doc_id`: string
  - `title`: string
  - `sections`: array (в Stage 9.4 — статический текстовый блок)
  - `meta.pack_id`: string
  - `meta.session_id`: string

## Output

- Результат: PDF.
- Где появляется `file_id`:
  - создаётся запись в `artifact_files` (id = `file_id`)
  - отдаётся в `GET /packs/{pack_id}/documents` для `status=ready`
  - скачивание: `GET /files/{file_id}/download` → presigned URL

## Failure modes

- Ошибки API (например, pack not found / forbidden / DOCUMENT_DISABLED).
- Ошибки очереди (не удалось enqueue в Redis).
- Ошибки worker’а (HTTP к render-service, invalid PDF, проблемы S3/DB, ретраи и max_attempts).

## Debugging

- `render_job_id`: см. таблицу `render_jobs` и admin logs.
- `render_jobs.last_error`, `render_jobs.attempts/max_attempts`.
- Артефакты PDF: `artifacts.meta.render_job_id`, `artifacts.meta.doc_id`, `artifact_files.id`.
- Логи worker’а: события `render_start`, `render_ok`, `render_error`, `render_retry_scheduled`.
- Артефакт `config_snapshot` (best-effort): `artifacts.kind=config_snapshot` + `meta.render_job_id`.

## Tier/access notes

- Источник по умолчанию: `tier` и `is_enabled` из registry.
- Оверлей: `document_access` в БД (admin может менять `tier/enabled`).
- UI может блокировать paid документы по `access.is_locked`.
