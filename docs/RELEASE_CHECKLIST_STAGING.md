# Release checklist — staging

Цель: чтобы можно было быстро и безопасно поднять “стенд жив” и проверить end-to-end сценарии без ручного шаманства.

## Перед выкладкой (pre-release)

1) Синхронизировать ветку/теги
- Убедиться, что используется ветка релиза (например, `release-prep-staging`) и в ней есть последние изменения.
- Убедиться, что workflow для первого запуска присутствует: [.github/workflows/staging-first-run.yml](../.github/workflows/staging-first-run.yml)

2) Прогнать проверки
- QA: см. [testing matrix](testing/TEST_MATRIX.md)
- Минимум:
  - `bash scripts/qa/test_persistence_postgres.sh`
  - `bash scripts/qa/test_observability_request_ids.sh`
  - `bash scripts/qa/test_llm_clarifications.sh`
  - `bash scripts/smoke-stage9.4.sh`
  - `bash scripts/staging/first-run-check.sh` (или через Actions)

3) Проверить конфиги/документы (если есть изменения)
- Конфиги и реестр документов управляются через админку (см. [docs/admin/](admin/))
- Если меняли документы/флаги доступа — убедиться, что “эффективная” доступность ожидаемая (disabled docs не попадают в рендер)

4) Подготовить доступы админа
- Проверить, что `ADMIN_PHONE_ALLOWLIST`, `ADMIN_PASSWORD_HASH`, `ADMIN_PASSWORD_SALT` заданы (на стенде)
- Проверить, что токены/секреты не требуют внешних провайдеров для smoke (SMS/LLM должны работать в `mock`)

## После выкладки (post-release)

1) Быстрый статус
- Открыть UI (front)
- Проверить `/health`, `/health/db`, `/health/s3`, `/health/sms`, `/health/llm`

2) End-to-end рендер
- Запустить manual workflow “Staging first run” или локально `scripts/staging/first-run-check.sh`
- Убедиться, что:
  - создаётся pack
  - создаются render jobs
  - хотя бы один документ становится `ready`
  - скачивание даёт PDF (magic `%PDF`)

3) Админка
- Войти и проверить:
  - логи/алерты
  - очередь render jobs (есть ли stuck jobs)

## Что мониторим

Минимальный список сигналов:
- API health: `/health`, `/health/db`
- Render pipeline: доля job’ов в `failed`, рост `attempts`, время до `ready`
- Storage: ошибки S3/MinIO, невозможность presign/download
- Redis: доступность, backlog очереди `render_jobs`
- Ошибки рендера: `render_job_failed` alerts

## Если что-то упало (triage / rollback)

1) Сначала собрать факты
- Посмотреть `docker compose ps` и логи сервисов (api, render-worker, render, redis, minio, db)
- Проверить admin logs/alerts (см. [admin runbook](admin/ADMIN_RUNBOOK.md))

2) Быстрые “гейты” без отката кода
- Если документ/рендер ломает стенд: временно выключить документ (`enabled=false`/tier overlays) через админку
- Если проблема в конфиге: сделать rollback на предыдущую валидную версию конфигурации через админку

3) Ререндер / requeue
- Для единичных падений: requeue конкретных `failed` jobs через админку (без дублирования активных jobs)

4) Откат релиза
- Если проблема системная и не чинится настройками:
  - откатить деплой на предыдущий working revision (конкретный механизм зависит от окружения)
  - повторить post-release проверки
