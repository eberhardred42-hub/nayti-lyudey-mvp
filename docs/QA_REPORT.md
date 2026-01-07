# QA Report — staging prep

Дата (UTC): 2026-01-07 02:56:07Z  
Ветка: `release-prep-staging`  
Commit: `801bacc`

## Окружение / предпосылки

Прогон выполнялся локально в dev container на Ubuntu 24.04.x, через `docker compose` из `infra/docker-compose.yml`.

Ключевые допущения:
- Внешние провайдеры не используются: SMS и LLM работают в режиме mock.
- Хранилище — MinIO (S3-compatible), загрузка PDF проверяется по magic `%PDF`.

Типовые значения (скрипты выставляют их сами):
- `DEBUG=1`
- `SMS_PROVIDER=mock`
- `LLM_PROVIDER=mock`
- `S3_ENDPOINT=http://minio:9000`
- `S3_PRESIGN_ENDPOINT=http://localhost:9000`

## Результаты прогона

Все проверки ниже завершились с кодом выхода `0`.

### QA
- `scripts/qa/quick_validate_repo.sh` — PASS
- `scripts/qa/test-stage5-code-only.sh` — PASS
- `scripts/qa/test_observability_request_ids.sh` — PASS
- `scripts/qa/test_llm_clarifications.sh` — PASS
- `scripts/qa/test_free_report_flow.sh` — PASS
- `scripts/qa/test_vacancy_kb_flow.sh` — PASS
- `scripts/qa/test_persistence_postgres.sh` — PASS

### Smoke / first-run
- `scripts/staging/first-run-check.sh` — PASS
- `scripts/smoke-stage9.4.sh` — PASS
- `scripts/smoke-admin.sh` — PASS

## Примечания по стабильности прогонов

В рамках подготовки staging прогон был сделан более детерминированным:
- Mock OTP: код OTP возвращается прямо из `/auth/otp/request` при `SMS_PROVIDER=mock` (без зависимости от debug-only endpoint).
- Проверка PDF: вместо `curl | head -c 4` используется запрос с `curl --range 0-3` (избегает ложных падений под `set -euo pipefail`).
- Bash QA-скрипты: JSON парсится без heredoc-stdin коллизий (устранены ложные "Failed to create session" / `JSONDecodeError`).
