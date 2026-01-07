# Staging deploy (Caddy + docker compose)

Цель: поднять staging на отдельном сервере с публичными портами **только 80/443** (reverse proxy Caddy) и автоматическим TLS (ACME).

## Предварительные условия

- DNS записи указывают на IP сервера:
  - `A`/`AAAA` для `${DOMAIN}`
  - `A`/`AAAA` для `api.${DOMAIN}`
  - `A`/`AAAA` для `s3.${DOMAIN}`
- На сервере установлены Docker и Docker Compose v2.
- Открыты входящие порты **80** и **443**.

## 1) Создать `.env.staging`

В каталоге репозитория:

```bash
cp deploy/staging/.env.staging.example deploy/staging/.env.staging
```

Заполните минимум:
- `DOMAIN`
- `POSTGRES_PASSWORD`
- `MINIO_ROOT_PASSWORD`
- `ADMIN_PHONE_ALLOWLIST`, `ADMIN_PASSWORD_SALT`, `ADMIN_PASSWORD_HASH`

По умолчанию `ACME_CA` указывает на Let’s Encrypt **staging**. Для боевого сертификата замените на production directory (и учтите rate limits).

## 2) Поднять стэк

```bash
docker compose \
  --env-file deploy/staging/.env.staging \
  -f deploy/staging/docker-compose.staging.yml \
  up -d --build
```

## 3) Проверка

Проверить API health:

```bash
curl -fsS https://api.${DOMAIN}/health
```

Открыть фронт:
- `https://${DOMAIN}`

Проверить S3 endpoint (без консоли):
- `https://s3.${DOMAIN}` (это S3 API, не web UI)

## Примечания

- Сервисы `db`, `redis`, `minio`, `render` **не публикуют порты наружу**.
- Все сервисы находятся в одном docker network (`staging`).
- MinIO console намеренно не публикуется.
