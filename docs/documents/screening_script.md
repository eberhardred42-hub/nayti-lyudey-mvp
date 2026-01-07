# screening_script — Скрипт скрининга

## Purpose

- PDF-документ "Скрипт скрининга" в библиотеке пака.
- В текущей реализации Stage 9.4: PDF-заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `screening_script`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/screening_script.pdf`.
- `file_id`: `artifact_files.id` (kind=`screening_script_pdf`).

## Failure modes

- `DOCUMENT_DISABLED` при регенерации, если выключен.
- Ошибки очереди/Redis.
- Worker: `render_http_*`, `render_invalid_pdf`, `S3_BUCKET_not_configured`, ошибки БД/артефактов.

## Debugging

- Статус/ошибки: `render_jobs` (`status/attempts/last_error`).
- PDF-файл: `artifacts.meta.render_job_id` + `artifact_files`.
- Worker logs: `render_error` / `render_retry_scheduled`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI блокирует действия при `access.is_locked=true`.
