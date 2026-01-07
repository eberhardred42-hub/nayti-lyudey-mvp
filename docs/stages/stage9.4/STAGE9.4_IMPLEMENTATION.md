# Stage 9.4 — реализация (render queue + Library)

Этот документ описывает, как устроен Stage 9.4 на уровне кода/инфраструктуры: очередь рендера, worker, render-service, артефакты (S3/MinIO) и API, которые использует фронт.

## Компоненты

### Инфраструктура
Опорный compose-файл: [../../../infra/docker-compose.yml](../../../infra/docker-compose.yml)

Ключевые сервисы:
- `api` — FastAPI (публичные endpoints + админка)
- `redis` — очередь рендера (Redis list)
- `render-worker` — consumer очереди, исполняет рендер
- `render` — render-service (HTML → PDF)
- `minio` + `minio-init` — S3-compatible storage (артефакты)
- `db` — Postgres

### Backend (FastAPI)
Основные endpoints Stage 9.4 находятся в `api/main.py`:
- `POST /packs/{pack_id}/render` — поставить в очередь рендер всех доступных документов для пака
- `POST /packs/{pack_id}/render/{doc_id}` — поставить в очередь рендер конкретного документа
- `GET /packs/{pack_id}/documents` — получить статусы/`file_id` по документам

Сопутствующие части:
- хранение статусов jobs + выборка «последняя job на doc_id»: `api/db.py`
- presigned скачивание готовых PDF: `GET /files/{file_id}/download` (Stage 9.3)

### Worker
Worker реализован в `api/worker.py` и запускается как отдельный сервис `render-worker`.

Задачи worker:
- забрать сообщение из Redis queue
- atomically перевести job из `queued` в `rendering`
- вызвать render-service `POST /render`
- сохранить PDF в S3 (MinIO)
- создать записи `artifacts` + `artifact_files`
- пометить job как `ready`

При ошибках worker увеличивает `attempts` и возвращает job в `queued` (с backoff), либо помечает как `failed`.

## Данные и статусы

### Таблица `render_jobs`
Создаётся в `api/db.py` (init_db). Полезные поля:
- `id` (UUID) — render job id
- `pack_id` (UUID)
- `session_id` (UUID/строка в текущей схеме)
- `doc_id` (TEXT)
- `status` (TEXT)
- `attempts`, `max_attempts`
- `last_error`

Статусы, используемые кодом:
- `queued` — job ожидает обработки
- `rendering` — job взят worker-ом
- `ready` — PDF создан и сохранён в S3
- `failed` — исчерпаны попытки или ошибка признана non-retryable

### Артефакты и файлы
Worker сохраняет PDF в S3 и пишет метаданные в Postgres:
- `artifacts` — логическая сущность артефакта
- `artifact_files` — конкретный файл в S3 (bucket + key)

Связка render job ↔ файл делается через `artifacts.meta.render_job_id`.

## Протокол очереди (Redis)

Очередь — Redis list (по умолчанию `render_jobs`).

Сообщение — JSON:
```json
{
  "job_id": "...",
  "pack_id": "...",
  "session_id": "...",
  "doc_id": "...",
  "render_request": { "...": "..." }
}
```

Worker читает `BLPOP`, после чего:
- валидирует payload (должны быть `job_id` и объект `render_request`)
- загружает job из БД
- пытается `queued → rendering` через `UPDATE ... WHERE status='queued'`

## Поток выполнения (end-to-end)

### 1) Создание jobs (API)
`POST /packs/{pack_id}/render`:
- читает реестр документов (config `documents_registry`)
- применяет оверлеи доступа/включенности документов
- создаёт `render_jobs` для документов, у которых нет активной job (`queued/rendering/ready`)
- пушит сообщения в Redis queue
- дополнительно пишет `config_snapshot` artifact для трассировки (какими версиями конфигов рендерили)

`POST /packs/{pack_id}/render/{doc_id}`:
- проверяет doc_id по реестру
- проверяет, что документ эффективным образом `enabled`
- создаёт job + пушит в очередь

### 2) Рендер (worker)
`api/worker.py`:
- вызывает render-service: `POST ${RENDER_URL}/render`
- проверяет, что ответ начинается с `%PDF`
- пишет файл в S3: `renders/{job_id}/{doc_id}.pdf`
- создаёт `artifact` и `artifact_file`
- выставляет статус `ready`

Ошибки:
- `attempts++`, статус возвращается в `queued`
- экспоненциальный backoff (с ограничением)
- если ошибка `render_http_4xx` или `attempts >= max_attempts` → `failed` + alert

### 3) Отображение статусов (API)
`GET /packs/{pack_id}/documents`:
- строит список документов из реестра (с учётом enabled/access overlays)
- подтягивает «последнюю» job на каждый `doc_id` через `DISTINCT ON (doc_id)`
- если job `ready`, резолвит `file_id` через `artifacts.meta.render_job_id`

### 4) Скачивание
Файл скачивается через Stage 9.3 endpoint:
- `GET /files/{file_id}/download` → presigned URL (S3/MinIO)

## Важные env vars
Задаются через compose ([../../../infra/docker-compose.yml](../../../infra/docker-compose.yml)):
- `DATABASE_URL`
- `REDIS_URL`
- `RENDER_URL`, `RENDER_TIMEOUT_SEC`
- `S3_ENDPOINT`, `S3_PRESIGN_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_USE_SSL`

## Как проверить
- Быстрый e2e: `./scripts/smoke-stage9.4.sh`
- Ожидание: smoke доходит до `ready`, получает `file_id`, скачивает PDF (первые байты `%PDF`).
