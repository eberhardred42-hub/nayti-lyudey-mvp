# scorecard — Scorecard

## Purpose

- PDF-документ "Scorecard" в библиотеке пака.
- В текущей реализации Stage 9.4: генерируется **заглушка** (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `scorecard`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статические), `meta.pack_id`, `meta.session_id`.

## Output

- PDF в S3: `renders/<render_job_id>/scorecard.pdf`.
- `file_id`: `artifact_files.id` (артефакт kind=`scorecard_pdf`).

## Failure modes

- Отключённый документ не рендерится (effective enabled=false).
- Ошибки очереди/Redis.
- Ошибки worker (HTTP к render-service, invalid PDF, S3/DB).

## Debugging

- `render_job_id`: `render_jobs` + worker logs.
- `render_jobs.last_error`.
- PDF: `artifacts.meta.render_job_id` → `artifact_files`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI может блокировать действия при `access.is_locked=true`.
