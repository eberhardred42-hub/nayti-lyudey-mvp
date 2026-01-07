# Deploy на staging (коротко)

Цель: поднять staging-стенд на домене с TLS и прогнать end-to-end smoke без ручного ковыряния.

## 0) Предварительные условия

- Docker + Docker Compose v2 установлены на сервере.
- DNS записи указывают на IP сервера:
  - `${DOMAIN}`
  - `api.${DOMAIN}`
  - `s3.${DOMAIN}`
- Открыты входящие порты: **22** (SSH), **80**, **443**.

## 1) Подготовить `.env.staging`

В репозитории:

```bash
cp deploy/staging/.env.staging.example deploy/staging/.env.staging
```

Минимально заполнить:
- `DOMAIN`
- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `ADMIN_PHONE_ALLOWLIST`, `ADMIN_PASSWORD_SALT`, `ADMIN_PASSWORD_HASH`

По умолчанию:
- `DEBUG=0`
- `SMS_PROVIDER=mock`
- `LLM_PROVIDER=mock`

## 2) Поднять стэк

```bash
docker compose \
  --env-file deploy/staging/.env.staging \
  -f deploy/staging/docker-compose.staging.yml \
  up -d --build
```

## 3) Быстрая проверка

Health:

```bash
curl -fsS "https://api.${DOMAIN}/health" >/dev/null && echo OK
```

Smoke (end-to-end):

```bash
DOMAIN="${DOMAIN}" bash scripts/smoke-staging.sh
# или
bash scripts/smoke-staging.sh "${DOMAIN}"
```

Если smoke падает — он автоматически печатает `docker compose logs --tail 300` для `api`, `worker`, `render`.

## 4) Где лежат детали

- Staging compose + Caddy: [deploy/staging/README.md](../deploy/staging/README.md)
- Общий индекс доков: [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)
