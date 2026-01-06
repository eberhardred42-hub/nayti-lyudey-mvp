# Stage 9.3: Storage (MinIO/S3) — Summary

## Что добавили
- MinIO (S3-compatible) в локальный docker-compose + init-job для создания бакета.
- Хранение файлов “гибридно”:
  - метаданные в Postgres (`artifact_files` + расширение `artifacts`)
  - байты в S3 (MinIO) по `bucket` + `object_key`.
- S3-клиент (boto3) с событиями `s3_upload_*` и `s3_presign_*`, плюс алерты через webhook.
- Presigned download:
  - `GET /files/{file_id}/download` (auth required, ownership check) → presigned URL.
  - DEBUG-only `POST /debug/s3/put-test-pdf` → создаёт минимальный PDF, сохраняет в S3, создаёт записи в БД, отдаёт presigned URL.
- Пользовательская “мини-библиотека”:
  - `GET /me/files` (auth required) → список файлов пользователя.
  - Front: `/library` (список + кнопка Download).
- Финальный e2e smoke-тест: `scripts/smoke-stage9.3.sh`.

## Как прогнать smoke (одна команда)
- `./scripts/smoke-stage9.3.sh`

Скрипт сам поднимает docker compose, прогоняет OTP mock auth, кладёт тестовый PDF в S3, скачивает его по presigned URL (проверяет `%PDF`), проверяет `/me/files`, затем делает `docker compose down -v`.

## Безопасность/зависимости
- Добавлена зависимость только для S3: `boto3` (и транзитивные зависимости).
- Секреты не коммитились: используются env-переменные; в репо только дефолтные dev-значения для локального MinIO.
