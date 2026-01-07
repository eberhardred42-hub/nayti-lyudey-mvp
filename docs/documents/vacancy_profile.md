# vacancy_profile — Профиль вакансии

## Purpose

- PDF-документ "Профиль вакансии" в библиотеке пака.
- В текущей реализации Stage 9.4: рендерит **заглушку** (базовый layout), без данных из vacancy_kb/артефактов.

## Input schema

Минимально (по факту Stage 9.4):
- `pack_id`: UUID (строка)
- `doc_id`: `vacancy_profile`
- `session_id`: UUID (строка) — берётся из `packs.session_id`
- Render request:
  - `doc_id`: `vacancy_profile`
  - `title`: registry или `document_metadata.title`
  - `sections`: сейчас статический текстовый блок
  - `meta.pack_id`, `meta.session_id`

## Output

- Результат: отдельный PDF-файл.
- S3 key: `renders/<render_job_id>/vacancy_profile.pdf`.
- `file_id`: `artifact_files.id` у артефакта (kind: `vacancy_profile_pdf`).

## Failure modes

- `DOCUMENT_DISABLED` при регенерации, если выключен.
- Ошибка enqueue в Redis.
- Worker: `render_http_*`, `render_invalid_pdf`, `S3_BUCKET_not_configured`, ошибки БД/артефактов, исчерпание `max_attempts`.

## Debugging

- `render_jobs`: искать по `pack_id + doc_id`.
- `render_jobs.last_error` и рост `attempts`.
- `artifacts.meta.render_job_id` → `artifact_files.id` (= `file_id`).
- `renders/<render_job_id>/vacancy_profile.pdf` в S3 bucket=`S3_BUCKET`.
- `GET /files/{file_id}/download` выдаёт presigned URL (TTL 600s) при наличии доступа у пользователя.

## Tier/access notes

- Registry: `tier=paid`, `is_enabled=true`.
- Оверлей `document_access.tier/enabled` может менять effective tier/enabled.
- В UI "Library" действия блокируются при `access.is_locked=true` (paid документы).
