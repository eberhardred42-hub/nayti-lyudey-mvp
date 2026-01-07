# Admin 1.1 — быстрые ссылки (контекст)

## Stage 9.4 API endpoints (FastAPI)
- Pack render (создаёт render jobs по registry, кладёт в Redis): [api/main.py](api/main.py#L1654)
- Pack render single doc (регенерация doc_id): [api/main.py](api/main.py#L1739)
- Pack documents statuses (status + file_id): [api/main.py](api/main.py#L1810)
- File download (presigned URL, auth + ownership): [api/main.py](api/main.py#L1449)

## DB schema / таблицы
- `artifacts`, `artifact_files`, `render_jobs` создаются в `init_db()`: [api/db.py](api/db.py#L122)
- `packs` (группировка документов): [api/db.py](api/db.py#L204)

## Связка render_job → artifact/file
- Worker пишет `artifacts.meta.render_job_id` при создании артефакта: [api/worker.py](api/worker.py#L150)
- API резолвит `file_id` из `artifacts.meta->>'render_job_id'`: [api/db.py](api/db.py#L1054)
- `GET /packs/{pack_id}/documents` берёт `file_id` только если job `ready`: [api/main.py](api/main.py#L1840)

## Documents registry
- Registry лежит в [api/documents.v1.json](api/documents.v1.json)
- Загрузка registry и фильтр `is_enabled`: [api/main.py](api/main.py#L210)

## Events / alerting
- Клиентские события (логирование, без storage): [api/main.py](api/main.py#L1861)
- Alerting webhook (env `ALERT_WEBHOOK_URL`, без логирования URL): [api/alerts.py](api/alerts.py#L22)
- Отправка alert при окончательном fail render job: [api/worker.py](api/worker.py#L207)
