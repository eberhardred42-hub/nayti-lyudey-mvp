# Admin Runbook

Этот документ — операторский гайд по админ‑консоли и основным эксплуатационным сценариям.

Админ‑API защищено заголовком `X-Admin-Token`.

## Как устроен доступ

Доступ состоит из двух шагов:

1) **OTP user login** → получаем user token (Bearer)
2) **Admin login** → проверяем allowlist телефона + admin password → получаем `admin_token` для `X-Admin-Token`

### 1) OTP user login

В этом репо OTP — **mock** (для локальных сценариев):
- `POST /auth/otp/request` — генерирует и сохраняет код в памяти процесса API
- `POST /auth/otp/verify` — проверяет код и возвращает user token (Bearer)

Для локальной отладки можно получить код через debug эндпоинт (только если `DEBUG=1`):
- `GET /debug/otp/latest?phone=<E164>`

Также поддержан упрощённый способ для ручных тестов без OTP:
- `Authorization: Bearer mockphone:+79991234567`

Важно: админ‑проверка использует **номер телефона из Bearer user token**, поэтому номер должен совпадать с allowlist.

### 2) Allowlist телефона (ADMIN_PHONE_ALLOWLIST)

- `ADMIN_PHONE_ALLOWLIST` — список номеров в E.164 через запятую.
- Если allowlist пуст — админ‑логин отключён (`admin_login_disabled`).
- Если номер не в allowlist — `not_allowed`.

### 3) Admin password (ADMIN_PASSWORD_HASH / ADMIN_PASSWORD_SALT)

- `ADMIN_PASSWORD_SALT` — соль.
- `ADMIN_PASSWORD_HASH` — ожидаемый hash в hex.
- Алгоритм: `PBKDF2-HMAC-SHA256(password, salt, 100000)`.

Как сгенерировать hash (пример; НЕ коммитить реальный пароль):

```bash
python3 - <<'PY'
import hashlib
pwd = "admin123"         # пример
salt = "smoke-salt"      # пример
dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt.encode("utf-8"), 100_000)
print(dk.hex())
PY
```

### 4) Admin session TTL 12h

- TTL задаётся `ADMIN_SESSION_TTL_HOURS` (по умолчанию 12 часов).
- При `POST /admin/login` создаётся запись в БД `admin_sessions` со сроком действия.
- В `X-Admin-Token` передаётся **одноразово выданный** `admin_token` (plain), в БД хранится только `token_hash`.

## Где хранятся значения и как менять безопасно

### Где лежит конфигурация доступа

Локально (docker compose) переменные прокидываются в сервис `api` из окружения:
- `ADMIN_PHONE_ALLOWLIST`
- `ADMIN_PASSWORD_HASH`
- `ADMIN_PASSWORD_SALT`
- `ADMIN_SESSION_TTL_HOURS`

См. [infra/docker-compose.yml](../../infra/docker-compose.yml).

Шаблон локальных значений (без секретов): [infra/.env.example](../../infra/.env.example).

### Как менять безопасно

- Никогда не коммитить реальные значения секретов в репозиторий.
- Менять env только через секрет‑хранилище/переменные окружения окружения (staging/prod), затем перезапуск `api`.
- При смене `ADMIN_PASSWORD_SALT` все текущие `X-Admin-Token` фактически станут невалидными (удобно для принудительного logout).

## Как устроен аудит

Аудит пишется в два слоя:

### 1) admin_audit_log (таблица)

Таблица: `admin_audit_log`.
Пишется через `record_admin_audit(...)`.

Что там есть (по факту схемы):
- `admin_user_id`, `admin_session_id`
- `action` (например: `config_publish`, `document_access_update`, `admin_login`)
- `target_type` (например: `config_store`, `document_access`, `admin_session`)
- `target_id`
- `before_hash` / `after_hash` (SHA256 от JSON “до/после”, без хранения полного объекта)
- `request_id`, `ip`, `user_agent`, `created_at`

Эндпоинт:
- `GET /admin/audit?limit=50&action=config_publish&target_type=config_store`

### 2) admin_event artifacts (артефакты)

В БД в таблицу `artifacts` пишутся события `kind=admin_event` (best-effort). Это используется для “следов” в Logs Viewer.

### Как найти «что сломалось после publish»

1) В `GET /admin/audit` найти событие `action=config_publish` и забрать `request_id`.
2) В `GET /admin/logs` отфильтровать по этому `request_id` (и/или `kind=admin_event`).
3) Проверить Alerts:
   - `GET /admin/alerts?event=bad_config_fallback`
   - `GET /admin/alerts?event=render_job_failed`
4) Проверить рендер‑очередь:
   - `GET /admin/render-jobs?status=failed`

## Разделы админки (UI) и что реально работает

Примечание: часть разделов присутствует как UI‑страницы, но некоторые из них сейчас **заглушки**.

### Overview

- UI: заглушка.
- API: `GET /admin/overview` существует (можно использовать через прокси роуты фронта).

### Jobs (requeue/retry)

- UI: есть.
- API:
  - `GET /admin/render-jobs`
  - `GET /admin/render-jobs/{job_id}`
  - `POST /admin/render-jobs/{job_id}/requeue` (только для `failed`)
  - `POST /admin/render-jobs/requeue-failed`

### Packs (render/regenerate)

- UI: заглушка.
- Пак‑операции сейчас живут в user API Stage 9.4:
  - `POST /packs/{pack_id}/render`
  - `POST /packs/{pack_id}/render/{doc_id}`
  - `GET /packs/{pack_id}/documents`

### Documents (описания/tier/enabled)

- UI: есть.
- API:
  - `GET /admin/documents`
  - `POST /admin/documents/{doc_id}/metadata`
  - `POST /admin/documents/{doc_id}/access`

### Configs (draft/validate/dry-run/publish/rollback)

- UI: есть.
- API:
  - `POST /admin/config/{key}/draft`
  - `POST /admin/config/{key}/update`
  - `POST /admin/config/{key}/validate?version=N`
  - `POST /admin/config/{key}/dry-run?version=N`
  - `POST /admin/config/{key}/publish?version=N`
  - `POST /admin/config/{key}/rollback`

Ключи: `documents_registry`, `blueprint`, `resources`.

### Pricing/Promos

- UI: заглушка.
- Backend API для pricing/promos в этом репо не реализован.

### Flags

- UI: заглушка.
- Backend API для flags в этом репо не реализован.

### Alerts/Logs

- UI: есть.
- API:
  - `GET /admin/alerts`, `POST /admin/alerts/{id}/ack`
  - `GET /admin/logs`

## Правила безопасного админа

- Всегда делать `validate` + `dry-run` перед `publish`.
- `publish` делать только в staging.
- После publish мониторить:
  - рост `admin/alerts` (например `bad_config_fallback`, `render_job_failed`)
  - рост failed render jobs (`/admin/render-jobs?status=failed`)
  - всплеск 500/ошибок в логах (по `request_id`)
- Если после publish выросли ошибки рендера/500 — делать `rollback` на предыдущую валидную версию.

## Частые проблемы и куда смотреть

### request_id

Почти все существенные события логируются с `request_id`. Это ключ для склейки:
- API logs
- admin_event artifacts
- audit entries

### render_job_id

Если ломается рендер PDF:
- смотреть `render_jobs.last_error`, `attempts`, `max_attempts`
- в worker логах искать `render_error` / `render_retry_scheduled`
- `file_id` резолвится по `artifacts.meta.render_job_id` (см. `get_latest_file_id_for_render_job`)

### artifacts.meta.render_job_id

Если status `ready`, но в UI нет `file_id`:
- проверить, что у PDF‑артефакта проставлен `meta.render_job_id`
- проверить, что `artifact_files` создан и связан с artifact

## Smoke / QA (локально)

- End-to-end рендер пайплайна: `./scripts/smoke-stage9.4.sh`
- Админ‑сценарии (alerts/logs/config/docs + рендер): `./scripts/smoke-admin.sh`

