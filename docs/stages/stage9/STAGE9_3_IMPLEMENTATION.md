# Stage 9.3: Storage (MinIO/S3) — Implementation

## Цели
- Добавить объектное хранилище (S3-compatible) для файлов (PDF и далее) без хранения blob в Postgres.
- Связать файлы с артефактами/сессиями и пользователем, чтобы:
  - выдавать пользователю список его файлов,
  - защищать скачивание ownership-check’ом.
- Дать воспроизводимый e2e smoke, который прогоняет весь пайплайн локально.

## Архитектура
- **Postgres** хранит метаданные:
  - `artifacts` — логические артефакты (связь с `session_id`, тип, формат, payload, meta).
  - `artifact_files` — физические файлы: `file_id`, `artifact_id`, `bucket`, `object_key`, `content_type`, `size_bytes`, timestamps.
- **MinIO** хранит байты по `bucket/object_key`.
- **API**
  - загружает байты через boto3 `put_object`,
  - генерирует presigned URL для `get_object`,
  - не логирует URL и секреты.

## Infra: MinIO в docker-compose
Файл: [infra/docker-compose.yml](infra/docker-compose.yml)
- Сервис `minio` (S3 endpoint `:9000`, console `:9001`).
- Сервис `minio-init` (образ `minio/mc`) создаёт бакет (idempotent).

Ключевые env:
- `S3_ENDPOINT` — endpoint для внутренних запросов из контейнеров (по умолчанию `http://minio:9000`).
- `S3_PRESIGN_ENDPOINT` — базовый endpoint для URL, который должен быть доступен с хоста (по умолчанию `http://localhost:9000`).
- `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_USE_SSL`.

## API: S3 client
Файл: [api/storage/s3_client.py](api/storage/s3_client.py)
- `upload_bytes(...)`:
  - события `s3_upload_start` / `s3_upload_ok` / `s3_upload_error`.
  - на ошибках дергает `send_alert(...)`.
- `presign_get(...)`:
  - генерирует presigned URL (SigV4) и эмитит `s3_presign_ok` / `s3_presign_error`.
  - IMPORTANT: URL в логах не печатается.
- Для совместимости с локальной сетью docker:
  - загрузка идёт через `S3_ENDPOINT` (`minio:9000`),
  - presigned URL строится на `S3_PRESIGN_ENDPOINT` (`localhost:9000`).

## API: алерты
Файл: [api/alerts.py](api/alerts.py)
- `send_alert(...)` отправляет JSON на `ALERT_WEBHOOK_URL` (если задан).
- Никогда не логирует сам URL.

## Endpoints
(Пути приведены для backend на `http://localhost:8000`.)

- `GET /health/s3`
  - env-only проверка конфигурации S3 (bucket/endpoint/credentials presence).
  - при `DEBUG=1` может делать лёгкий `head_bucket`.

- `POST /debug/s3/put-test-pdf` (DEBUG-only, auth required)
  - генерирует минимальный валидный PDF,
  - создаёт `artifact` + `artifact_file` в Postgres,
  - кладёт файл в MinIO,
  - отдаёт `download_url` (presigned GET).

- `GET /files/{file_id}/download` (auth required)
  - ownership check через join по `sessions.user_id`.
  - возвращает presigned URL.

- `GET /me/files` (auth required)
  - возвращает список файлов пользователя (в т.ч. `doc_id`, если присутствует в `artifacts.meta`).

## Runbook (обязательно)

### Поднять MinIO + API локально
Самый простой способ — через compose:
- `docker compose -f infra/docker-compose.yml up -d --build`

Порты:
- API: `http://localhost:8000`
- MinIO S3: `http://localhost:9000`
- MinIO Console: `http://localhost:9001`

### Проверить /health/s3
- `curl -s http://localhost:8000/health/s3 | python3 -m json.tool`

Ожидаемо: `{"ok": true, "bucket": "...", "endpoint": "..." ...}`.

### Выполнить smoke-stage9.3.sh (одна команда)
- `./scripts/smoke-stage9.3.sh`

Скрипт:
- сам выставляет нужные env (DEBUG, S3, DATABASE_URL),
- делает `docker compose up -d --build`,
- прогоняет mock OTP auth, принимает оффер,
- кладёт тестовый PDF в S3,
- скачивает по presigned URL и проверяет magic bytes `%PDF`,
- проверяет `/me/files`,
- завершает `docker compose down -v`.

ВАЖНО: `down -v` удаляет volumes (Postgres/MinIO данные) — это ожидаемо для чистого воспроизводимого прогона.

### Где смотреть логи
- Backend:
  - `docker compose -f infra/docker-compose.yml logs -f api`
- MinIO:
  - `docker compose -f infra/docker-compose.yml logs -f minio`
- Postgres:
  - `docker compose -f infra/docker-compose.yml logs -f db`

### Ключевые log_event события
- S3 upload:
  - `s3_upload_start`, `s3_upload_ok`, `s3_upload_error`
- Presign:
  - `s3_presign_ok`, `s3_presign_error`
- Файлы:
  - `file_presigned`, `file_created`
- Алерты:
  - `alert_sent` (и ошибки отправки алерта)

## Зависимости и секреты
- Добавлен Python dependency только для S3: `boto3`.
- Секреты не коммитились:
  - ключи/секреты/endpoint’ы — через env;
  - presigned URL не логируется.
