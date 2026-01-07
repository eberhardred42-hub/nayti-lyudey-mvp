# manifest — Manifest

## Purpose

- PDF-документ "Manifest" в библиотеке пака.
- В Stage 9.4: PDF-заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `manifest`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/manifest.pdf`.
- `file_id`: `artifact_files.id` (kind=`manifest_pdf`).

## Failure modes

- Document disabled.
- Queue/worker errors.

## Debugging

- `render_jobs` + worker logs.
- `artifacts.meta.render_job_id` → `artifact_files`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI может блокировать действия по `access.is_locked`.
