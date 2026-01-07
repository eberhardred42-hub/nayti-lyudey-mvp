# Stage 9.4 — очередь рендера и библиотека PDF (итоги)

Implementation (детали): [STAGE9.4_IMPLEMENTATION.md](STAGE9.4_IMPLEMENTATION.md)

## Что было целью
Собрать end-to-end пайплайн генерации PDF-документов по «паку»:
- API создаёт render jobs и кладёт их в очередь.
- Worker забирает jobs из Redis, рендерит PDF через render-service (Playwright), кладёт файл в S3-совместимое хранилище (MinIO) и отмечает job как `ready`.
- API отдаёт статус документов и `file_id`, а также выдаёт presigned URL на скачивание.
- Front показывает «Library» со статусами и ссылками на скачивание.

## Что реализовано (границы Stage 9.4)
**Инфраструктура (docker-compose)**
- Postgres для persistence.
- Redis очередь `render_jobs`.
- MinIO (S3 compatible) + presign endpoint.
- Render service (HTML → PDF через Playwright).
- Render worker (consumer очереди).

**API (FastAPI)**
- Триггер рендера пака: `POST /packs/{pack_id}/render` (создаёт jobs по реестру документов).
- Регенерация конкретного документа: `POST /packs/{pack_id}/render/{doc_id}`.
- Список документов с текущим статусом и `file_id`: `GET /packs/{pack_id}/documents`.
- Скачивание файла: `GET /files/{file_id}/download` (возвращает presigned URL).

**Хранилище / Артефакты**
- Worker сохраняет PDF в S3 (MinIO).
- В БД создаются `artifacts`/`artifact_files` и связываются с render job через `artifacts.meta.render_job_id`.

**Front (Next.js)**
- Страница Library отображает список паков/документов и их статусы, позволяет скачивать готовые PDF.

## Что починили в этой итерации
1) **Smoke Stage 9.4 падал не из-за бэка**, а из-за бага в самом smoke-скрипте.
   - В `scripts/smoke-stage9.4.sh` polling использовал `python3 - <<'PY' ... PY <<<"$DOCS_JSON"`.
   - В таком виде `python3 -` читает код из stdin (heredoc), и JSON из stdin туда уже не попадает.
   - Итог: парсер всегда видел пустой stdin и никогда не находил `ready/file_id`.
   - Исправление: перейти на `python3 -c ... <<<"$DOCS_JSON"`.

2) **Уточнили выборку для /documents**: на уровне БД `list_latest_render_jobs_for_pack` возвращает *последнюю* job на каждый `doc_id` (Postgres `DISTINCT ON (doc_id)`), чтобы статусы не “откатывались” на старые записи при повторных рендерах.

## Как проверить
- Локально: `./scripts/smoke-stage9.4.sh`.
- Ожидаемый результат: `[smoke] OK` + скачанный файл начинается с `%PDF`.

## Не входит в Stage 9.4 (осознанно)
- Платёжные ограничения (paid/free), биллинг.
- Реальный SMS-провайдер и боевой auth.
- SLA/ретраи/алерты прод-уровня (есть базовые ретраи, но без прод-обвязки).

