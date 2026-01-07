# offer_template — Offer template

## Purpose

- PDF-документ "Offer template" в библиотеке пака.
- В Stage 9.4: PDF-заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `offer_template`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/offer_template.pdf`.
- `file_id`: `artifact_files.id` (kind=`offer_template_pdf`).

## Failure modes

- Document disabled.
- Queue/worker errors.

## Debugging

- `render_jobs`.
- `artifacts.meta.render_job_id` → `artifact_files`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI может блокировать действия по `access.is_locked`.
