# role_snapshot — Role snapshot

## Purpose

- PDF-документ "Role snapshot" в библиотеке пака.
- В Stage 9.4: генерируется заглушка (базовый layout).

## Input schema

- `pack_id`: UUID (строка)
- `doc_id`: `role_snapshot`
- `session_id`: UUID (строка)
- Render request: `doc_id`, `title`, `sections` (статический текст), `meta.pack_id`, `meta.session_id`.

## Output

- S3: `renders/<render_job_id>/role_snapshot.pdf`.
- `file_id`: `artifact_files.id` (kind=`role_snapshot_pdf`).

## Failure modes

- Документ отключён (registry/DB overlay).
- Worker: invalid PDF / http errors / S3_BUCKET missing / DB errors.

## Debugging

- `render_jobs` статус/ошибки.
- `artifacts.meta.render_job_id` и `artifact_files`.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- UI может блокировать действия при `access.is_locked=true`.
