# sourcing_pack — Sourcing pack

## Purpose

- PDF-документ "Sourcing pack" в библиотеке пака.
- В текущей реализации Stage 9.4: генерируется **заглушка** (базовый layout), без подключения данных.

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `sourcing_pack`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/sourcing_pack.pdf`.
- `file_id`: `artifact_files.id` (kind=`sourcing_pack_pdf`).

## Failure modes

- Документ отключён → не попадает в render/list.
- Redis enqueue error.
- Worker: `render_http_*`, `render_invalid_pdf`, S3/DB ошибки, исчерпан `max_attempts`.

## Debugging

- `render_jobs` по `pack_id + doc_id`.
- `last_error` и `attempts`.
- PDF артефакт: `artifacts.meta.render_job_id` → `artifact_files`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI может блокировать действия при `access.is_locked=true`.
