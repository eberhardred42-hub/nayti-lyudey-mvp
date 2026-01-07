# budget_reality_check — Budget reality check

## Purpose

- PDF-документ "Budget reality check" в библиотеке пака.
- В Stage 9.4: генерируется заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `budget_reality_check`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/budget_reality_check.pdf`.
- `file_id`: `artifact_files.id` (kind=`budget_reality_check_pdf`).

## Failure modes

- Документ отключён → не будет в pack render/list.
- Worker/очередь ошибки как у остальных документов.

## Debugging

- `render_jobs` по `doc_id`.
- `artifacts.meta.render_job_id` → `artifact_files`.

## Tier/access notes

- Registry: `tier=free`, `is_enabled=true`.
- Оверлей `document_access` может изменить tier/enabled.
