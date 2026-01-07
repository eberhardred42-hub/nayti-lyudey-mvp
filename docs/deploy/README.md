# Deploy / Staging

Этот раздел — минимальная “точка входа” для staging/деплоя. В репозитории основной reference для локального и staging-стека — docker-compose.

## Базовый стек
См. compose: [../../infra/docker-compose.yml](../../infra/docker-compose.yml)

Он поднимает:
- `api` (FastAPI)
- `front` (Next.js)
- `db` (Postgres)
- `redis` (очередь render jobs)
- `render-worker` (consumer очереди)
- `render` (render-service)
- `minio` + `minio-init` (S3-compatible storage)

## Переменные окружения
Ключевые env vars (есть дефолты в compose):
- `DATABASE_URL`
- `REDIS_URL`
- `S3_ENDPOINT`, `S3_PRESIGN_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_USE_SSL`
- `RENDER_URL`, `RENDER_TIMEOUT_SEC`
- `CONFIG_SOURCE` (`file` или `db`)
- `ADMIN_PHONE_ALLOWLIST`, `ADMIN_PASSWORD_HASH`, `ADMIN_PASSWORD_SALT` (если нужна админка)

## Команды (compose)
Из корня репозитория:
```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Остановить:
```bash
docker compose -f infra/docker-compose.yml down
```

## Быстрая валидация
Smoke сценарии (последовательность обычно такая):
- Stage 9.3 (storage): `./scripts/smoke-stage9.3.sh`
- Stage 9.4 (render): `./scripts/smoke-stage9.4.sh`
- Admin (если настроено): `./scripts/smoke-admin.sh`

Полный список тестов/qa команд: [../testing/TEST_MATRIX.md](../testing/TEST_MATRIX.md)

## Troubleshooting
См. [../RUNBOOK.md](../RUNBOOK.md)
