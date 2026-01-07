# free_report — Бесплатный отчёт

## Purpose

- PDF-документ "Бесплатный отчёт" в библиотеке пака.
- В текущей реализации Stage 9.4: рендерит **заглушку** (базовый layout с текстовым блоком), без подключения данных из vacancy_kb/артефактов.

## Input schema

Минимально (по факту Stage 9.4):
- `pack_id`: UUID (строка)
- `doc_id`: `free_report`
- `session_id`: UUID (строка) — берётся из `packs.session_id`
- Render request (уходит в очередь worker’у):
  - `doc_id`: `free_report`
  - `title`: берётся из registry (или оверлея `document_metadata.title`)
  - `sections`: массив секций; сейчас формируется `_build_render_request()` и содержит статический текст
  - `meta.pack_id`, `meta.session_id`

## Output

- Результат: отдельный PDF-файл.
- S3 key: `renders/<render_job_id>/free_report.pdf`.
- `file_id` появляется как `artifact_files.id` у PDF-артефакта (kind: `free_report_pdf`).

## Failure modes

- Документ отключён (effective enabled=false) → не попадёт в `/packs/{pack_id}/render` и `/packs/{pack_id}/documents`; регенерация вернёт `400 DOCUMENT_DISABLED`.
- Ошибка enqueue в Redis → `500 Failed to enqueue render job`.
- Worker:
  - `render_http_<code>` (render-service вернул не 200)
  - `render_invalid_pdf` (ответ не начинается с `%PDF`)
  - `S3_BUCKET_not_configured`
  - ошибки записи в БД (`artifact_create_failed` и др.)
  - после `max_attempts` → статус `failed`

## Debugging

- Найти job: `render_jobs` по `pack_id + doc_id` (или через UI/эндпоинты админки render jobs).
- Смотреть `render_jobs.status`, `attempts`, `max_attempts`, `last_error`.
- Найти PDF-файл: `artifacts.meta.render_job_id = <render_job_id>` → join с `artifact_files` (id = `file_id`).
- Проверить загрузку в S3: bucket=`S3_BUCKET`, key=`renders/<render_job_id>/free_report.pdf`.
- Проверить, что `GET /packs/{pack_id}/documents` резолвит `file_id` только при `status=ready`.
- Артефакт snapshot: `artifacts.kind=config_snapshot` и `meta.render_job_id=<render_job_id>` (best-effort).

## Tier/access notes

- Registry: `tier=free`, `is_enabled=true`.
- Оверлей: `document_access` может менять `tier/enabled`.
- `DOCS_FORCE_ALL_FREE=true` принудительно делает tier=free (effective).
