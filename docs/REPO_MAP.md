# Repo map (release prep)

## Верхний уровень
- README и входные скрипты: [README.md](../README.md), [start-dev.sh](../start-dev.sh)
- Backend/API: [api/](../api/)
- Frontend (Next.js): [front/](../front/)
- Инфраструктура локального стенда (compose): [infra/](../infra/)
- Render-сервис (HTML→PDF): [render/](../render/)
- ML сервис (mock/инференс): [ml/](../ml/)
- Smoke/ops скрипты: [scripts/](../scripts/)
- Тесты stage*: [tests/](../tests/)
- Документация (stages + runbooks): [docs/](./)

## Docker / окружения (dev/staging)
- Единственный docker-compose в репозитории: [infra/docker-compose.yml](../infra/docker-compose.yml)
  - Поднимает: `api`, `front`, `db` (Postgres), `redis`, `minio`, `render`, `render-worker`, `ml`
  - Отдельного staging-compose сейчас нет (ориентир для будущего: добавить рядом, не трогая dev).

## Scripts / QA
- Smoke (E2E): [scripts/smoke-stage9.4.sh](../scripts/smoke-stage9.4.sh), [scripts/smoke-admin.sh](../scripts/smoke-admin.sh)
- Тесты стадий: [tests/](../tests/)
- CI: [.github/workflows/ci.yml](../.github/workflows/ci.yml)

## Docs
- Индекс: [docs/DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md)
- Общий runbook: [docs/RUNBOOK.md](RUNBOOK.md)
- Админский runbook: [docs/admin/ADMIN_RUNBOOK.md](admin/ADMIN_RUNBOOK.md)
- История стадий: [docs/stages/](stages/)

## Конфиги и «где что хранится»
- Версионируемые конфиги (DB-store + fallback на файл) реализованы в [api/main.py](../api/main.py)
  - Список поддерживаемых ключей: `documents_registry`, `blueprint`, `resources` (см. [api/main.py](../api/main.py))
  - Файл-фоллбек для `documents_registry`: [api/documents.v1.json](../api/documents.v1.json)
  - Для `blueprint/resources` файлового бэкапа пока нет (фоллбек отдаёт `{}`), это важно для staging.
- Документы (registry):
  - База: [api/documents.v1.json](../api/documents.v1.json)
  - Загрузка/фильтрация (enabled) и сборка пакета: [api/main.py](../api/main.py)
- Доступы документов (`tier/enabled`) и метаданные (title/description):
  - Таблицы и CRUD-хелперы: [api/db.py](../api/db.py)
  - Админ-эндпоинты для правок: [api/main.py](../api/main.py)
- Pricing / promos / flags:
  - В UI админки есть страницы-заглушки: [front/src/app/admin/(app)/pricing/page.tsx](../front/src/app/admin/(app)/pricing/page.tsx), [front/src/app/admin/(app)/flags/page.tsx](../front/src/app/admin/(app)/flags/page.tsx)
  - Отдельного хранилища/контрактов для pricing/promos/flags в API пока нет (ориентир: завести как config key в DB-store по аналогии с `documents_registry`).

## Stage 9.4: ключевые пользовательские endpoints
Backend (FastAPI):
- /packs:
  - render all docs: [api/main.py](../api/main.py)
  - render single doc: [api/main.py](../api/main.py)
  - documents status: [api/main.py](../api/main.py)
- /files:
  - download: [api/main.py](../api/main.py)
- /sessions, /ml/job и прочее: основной роутинг в [api/main.py](../api/main.py)

Frontend (Next.js API routes / proxy):
- /api/packs/*: [front/src/app/api/packs/](../front/src/app/api/packs/)
- /api/files/*: [front/src/app/api/files/](../front/src/app/api/files/)
- /library (страница): [front/src/app/library/page.tsx](../front/src/app/library/page.tsx)

## Admin: вход и env
- Backend admin auth/сессии:
  - Таблица `admin_sessions` и аудит/артефакты: [api/db.py](../api/db.py)
  - Admin endpoints (login/me/configs/docs/jobs/alerts/logs): [api/main.py](../api/main.py)
  - Alerts helper: [api/alerts.py](../api/alerts.py)
- Frontend admin UI:
  - Логин: [front/src/app/admin/(auth)/login/page.tsx](../front/src/app/admin/(auth)/login/page.tsx)
  - Разделы админки: [front/src/app/admin/(app)/](../front/src/app/admin/(app)/)
  - Proxy к backend admin API: [front/src/app/api/admin/](../front/src/app/api/admin/)
- Переменные окружения (без секретов):
  - Пример: [.env.example](../.env.example)
  - Проброс в compose: [infra/docker-compose.yml](../infra/docker-compose.yml)
