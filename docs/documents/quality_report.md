# quality_report — Quality report

## Purpose

- PDF-документ "Quality report" в библиотеке пака.
- В Stage 9.4: генерируется PDF-заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `quality_report`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/quality_report.pdf`.
- `file_id`: `artifact_files.id` (kind=`quality_report_pdf`).

## Failure modes

- Отключённый документ не попадёт в `/packs/{pack_id}/render`.
- Ошибки очереди/Redis.
- Worker: `render_http_*`, `render_invalid_pdf`, S3/DB ошибки.

## Debugging

- `render_jobs` (`status/last_error/attempts`).
- `artifacts.meta.render_job_id` + `artifact_files`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI может блокировать действия по `access.is_locked`.
