# Admin Runbook

Этот документ — краткий операторский гайд по админ‑консоли и основным сценариям эксплуатации.

## Доступ в админку

Админ‑эндпоинты требуют заголовок `X-Admin-Token`.

### Предусловия (env)

В docker‑compose `api` читает:

- `ADMIN_PHONE_ALLOWLIST` — номера в E.164 через запятую (пример: `+79990000000,+79990000001`)
- `ADMIN_PASSWORD_SALT` — соль для PBKDF2
- `ADMIN_PASSWORD_HASH` — hex(PBKDF2-HMAC-SHA256(password, salt, 100000))
- `ADMIN_SESSION_TTL_HOURS` — TTL админ‑сессии (по умолчанию 12)

### Как сгенерировать `ADMIN_PASSWORD_HASH`

```bash
python3 - <<'PY'
import hashlib
pwd = "admin123"
salt = "smoke-salt"
dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt.encode("utf-8"), 100_000)
print(dk.hex())
PY
```

### Логин (curl)

1) Получите user token (через OTP / mock OTP).
2) Выполните админ‑логин:

```bash
curl -sS -X POST http://localhost:8000/admin/login \
  -H "Authorization: Bearer <USER_TOKEN>" \
  -H 'Content-Type: application/json' \
  --data '{"admin_password":"<PASSWORD>"}'
```

Ответ содержит `admin_token`. Его нужно прокидывать в `X-Admin-Token`.

## Alerts Center

### Что это

Каждый вызов `send_alert(...)` записывает событие в БД как artifact `kind=alert_event` (best‑effort) и (опционально) шлёт webhook, если задан `ALERT_WEBHOOK_URL`.

### Операции

- Список: `GET /admin/alerts?limit=100&severity=warning&event=bad_config_fallback`
- Ack: `POST /admin/alerts/{id}/ack`

Ack хранится в `artifacts.meta`:
- `acked_at`
- `acked_by_user_id`

## Logs Viewer

Единый просмотр «следов» из двух источников:

- artifacts (любые `kind`, включая `admin_event`, `alert_event`, и т.д.)
- render jobs (как записи `kind=render_job`)

Эндпоинт:

- `GET /admin/logs?kind=<artifact_kind|render_job>&pack_id=<...>&doc_id=<...>&status=<...>&limit=200`

UI делает клиентское маскирование потенциально чувствительных данных в JSON.

## Config lifecycle (безопасное управление конфигами)

Ключевая идея: при `CONFIG_SOURCE=db` сервис берёт активную валидную версию из БД, а при отсутствии/невалидности — fallback на file + запись алерта `bad_config_fallback`.

Основные операции:

- Draft: `POST /admin/config/{key}/draft`
- Update: `POST /admin/config/{key}/update`
- Validate: `POST /admin/config/{key}/validate?version=N`
- Dry-run: `POST /admin/config/{key}/dry-run?version=N`
- Publish: `POST /admin/config/{key}/publish?version=N`
- Rollback: `POST /admin/config/{key}/rollback`

Поддерживаемые ключи: `documents_registry`, `blueprint`, `resources`.

## Documents governance

- Список: `GET /admin/documents`
- Метаданные: `POST /admin/documents/{doc_id}/metadata`
- Доступ: `POST /admin/documents/{doc_id}/access` (`enabled`, `tier=free|paid`)

## Render jobs

- Список: `GET /admin/render-jobs`
- Детали: `GET /admin/render-jobs/{id}`
- Requeue: `POST /admin/render-jobs/{id}/requeue` (только `failed`)
- Requeue failed batch: `POST /admin/render-jobs/requeue-failed`

## Smoke / QA

- End-to-end рендер пайплайна: `./scripts/smoke-stage9.4.sh`
- Админ‑сценарии (alerts/logs/config/docs + рендер): `./scripts/smoke-admin.sh`

