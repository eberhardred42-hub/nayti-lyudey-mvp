# Staging deploy (Caddy + docker compose)

Цель: поднять staging на отдельном сервере с публичными портами **только 80/443** (reverse proxy Caddy) и автоматическим TLS (ACME).

## Предварительные условия

- DNS записи указывают на IP сервера:
  - `A`/`AAAA` для `${DOMAIN}`
  - `A`/`AAAA` для `api.${DOMAIN}`
  - `A`/`AAAA` для `s3.${DOMAIN}`
- На сервере установлены Docker и Docker Compose v2.
- На уровне сервера (security group / firewall) открыты входящие порты: **22** (SSH), **80** и **443**.

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

Если хотите реальную отправку OTP по SMS через SMSAero:
- установите `SMS_PROVIDER=smsaero`
- заполните `SMSAERO_EMAIL` и `SMSAERO_API_KEY`
- при необходимости заполните `SMS_SENDER`

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

Минимальная проверка «сквозного» флоу (через публичный домен):

```bash
export DOMAIN="${DOMAIN}"
export API="https://api.${DOMAIN}"
export USER_ID="staging-smoke"

# 1) Создать сессию
SESSION_ID=$(curl -fsS -X POST "$API/sessions" \
  -H 'Content-Type: application/json' \
  -H "X-User-Id: $USER_ID" \
  -d '{"profession_query":"QA smoke"}' | python3 -c 'import sys, json; print(json.load(sys.stdin)["session_id"])')
echo "session_id=$SESSION_ID"

# 2) Прочитать оферту (опционально)
curl -fsS -H "X-User-Id: $USER_ID" "$API/legal/offer" >/dev/null

# 3) Принять оферту (обязательно для pack/render)
curl -fsS -X POST -H "X-User-Id: $USER_ID" "$API/legal/offer/accept" >/dev/null

# 4) Создать pack
PACK_ID=$(curl -fsS -X POST "$API/ml/job" \
  -H 'Content-Type: application/json' \
  -H "X-User-Id: $USER_ID" \
  -d "{\"session_id\":\"$SESSION_ID\"}" | python3 -c 'import sys, json; print(json.load(sys.stdin)["pack_id"])')
echo "pack_id=$PACK_ID"

# 5) Запустить render
curl -fsS -X POST -H "X-User-Id: $USER_ID" "$API/packs/$PACK_ID/render" >/dev/null

# 6) Дождаться появления файлов и взять ссылку на скачивание
for i in $(seq 1 60); do
  FILE_ID=$(curl -fsS -H "X-User-Id: $USER_ID" "$API/me/files" | python3 -c 'import sys, json; d=json.load(sys.stdin); f=(d.get("files") or []); print(f[0]["file_id"] if f else "")')
  if [ -n "$FILE_ID" ]; then break; fi
  sleep 2
done
echo "file_id=$FILE_ID"

curl -fsS -H "X-User-Id: $USER_ID" "$API/files/$FILE_ID/download" | python3 -c 'import sys, json; print(json.load(sys.stdin)["url"])'
```

Открыть фронт:
- `https://${DOMAIN}`

Проверить S3 endpoint (без консоли):
- `https://s3.${DOMAIN}` (это S3 API, не web UI)

## Примечания

- Сервисы `db`, `redis`, `minio`, `render` **не публикуют порты наружу**.
- Все сервисы находятся в одном docker network (`staging`).
- MinIO console намеренно не публикуется.
- По умолчанию `DEBUG=0`, а `/debug/*` недоступны.
