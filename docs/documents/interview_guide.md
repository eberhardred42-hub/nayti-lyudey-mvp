# interview_guide — Interview guide

## Purpose

- PDF-документ "Interview guide" в библиотеке пака.
- В Stage 9.4: генерируется заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `interview_guide`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/interview_guide.pdf`.
- `file_id`: `artifact_files.id` (kind=`interview_guide_pdf`).

## Failure modes

- Отключённый документ не рендерится.
- Worker: http/invalid pdf/s3/db.

## Debugging

- `render_jobs` статус/ошибки.
- `artifacts.meta.render_job_id`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI может блокировать действия по `access.is_locked`.
