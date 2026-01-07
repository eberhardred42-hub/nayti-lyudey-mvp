# hiring_pack — Hiring pack

## Purpose

- PDF-документ "Hiring pack" в библиотеке пака.
- В текущей реализации Stage 9.4: PDF-заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `hiring_pack`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/hiring_pack.pdf`.
- `file_id`: `artifact_files.id` (kind=`hiring_pack_pdf`).

## Failure modes

- Отключённый документ не рендерится (effective enabled=false).
- Ошибки очереди/Redis.
- Worker: `render_http_*`, `render_invalid_pdf`, S3/DB ошибки.

## Debugging

- `render_job_id` и `render_jobs.last_error`.
- `artifacts.meta.render_job_id` → `artifact_files.id`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- Paid документы могут быть заблокированы UI по `access.is_locked`.
