# DEV/PROD окружения на одном сервере

Цель: одновременно держать два docker-compose стека на одном хосте:
- **PROD**: домен `https://naitilyudei.ru` → порты `3000/8000/...`
- **DEV**: домен `https://dev.naitilyudei.ru` → порты `3100/8100/...` (не конфликтуют с PROD)

Маршрутизацию делает Caddy (TLS + reverse proxy) по [Caddyfile](../Caddyfile).

## Как это устроено

- Два независимых compose-проекта:
  - `docker compose -p prod -f infra/docker-compose.yml ...`
  - `docker compose -p dev -f infra/docker-compose.yml ...`
- Порты хоста параметризованы через переменные окружения в [infra/docker-compose.yml](../infra/docker-compose.yml).
- Caddy запущен отдельным контейнером в `--network host` и проксирует на `localhost:<HOST_PORT>`.

## Порты

**PROD (по умолчанию):**
- `FRONT_HOST_PORT=3000`
- `API_HOST_PORT=8000`
- `ML_HOST_PORT=8001`
- `RENDER_HOST_PORT=8002`
- `MINIO_HOST_PORT=9000`
- `MINIO_CONSOLE_HOST_PORT=9001`
- `DB_HOST_PORT=5432`
- `REDIS_HOST_PORT=6379`

**DEV (рекомендуемые):**
- `FRONT_HOST_PORT=3100`
- `API_HOST_PORT=8100`
- `ML_HOST_PORT=8101`
- `RENDER_HOST_PORT=8102`
- `MINIO_HOST_PORT=9100`
- `MINIO_CONSOLE_HOST_PORT=9101`
- `DB_HOST_PORT=15432`
- `REDIS_HOST_PORT=16379`

Важно: если меняете порты, обновите соответствующие `reverse_proxy localhost:...` в [Caddyfile](../Caddyfile).

## Деплой

### DEV (автоматически)
- Workflow: `.github/workflows/dev-deploy.yml`
- Триггер: `push` в `main` (и вручную `workflow_dispatch`)
- Поведение: `git reset --hard origin/main` и `docker compose -p dev ... up -d --build`

### PROD (вручную)
- Workflow: `.github/workflows/stage-deploy.yml` (название в GitHub Actions: **PROD Deploy**)
- Триггер: `workflow_dispatch`
- Параметр: `ref` (branch/tag/sha). По умолчанию `main`.
- Поведение: деплоит выбранный `ref` и поднимает `docker compose -p prod ...`

## Быстрые проверки

- PROD:
  - `curl -fsS https://naitilyudei.ru/ >/dev/null`
  - `curl -fsS https://naitilyudei.ru/api/docs >/dev/null`

- DEV:
  - `curl -fsS https://dev.naitilyudei.ru/ >/dev/null`
  - `curl -fsS https://dev.naitilyudei.ru/api/docs >/dev/null`

## Вспомогательные workflow

Workflow’ы `Stage Status`, `Stage Logs`, `Stage Smoke Deep` принимают параметр `env` (`dev|prod`) и показывают статус/логи/проверки нужного стека.
