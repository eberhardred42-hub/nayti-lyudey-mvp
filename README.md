# Nayti-Lyudey MVP

Nayti-Lyudey — MVP продукта, который собирает данные по вакансии (Vacancy KB) и генерирует набор PDF-документов ("пак") с библиотекой скачиваний, а также имеет админ-панель для операционного контроля (конфиги, доступность документов, render jobs, логи/алерты).

## Локальный запуск (docker compose)

Поднять стек:
```bash
docker compose -f infra/docker-compose.yml up -d --build
```

Открыть фронт:
- http://localhost:3000

Проверить здоровье:
```bash
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8000/health/db
curl -fsS http://localhost:8000/health/llm
curl -fsS http://localhost:8000/health/sms
curl -fsS http://localhost:8000/health/s3
```

Остановить и почистить volume’ы:
```bash
docker compose -f infra/docker-compose.yml down -v --remove-orphans
```

## Основные проверки (QA/Smoke)

Скрипты (актуальные):
- QA: папка [scripts/qa/](scripts/qa/)
- Smoke: [scripts/smoke-stage9.3.sh](scripts/smoke-stage9.3.sh), [scripts/smoke-stage9.4.sh](scripts/smoke-stage9.4.sh), [scripts/smoke-admin.sh](scripts/smoke-admin.sh)

Рекомендуемый минимум перед релизом:
```bash
bash scripts/qa/test_persistence_postgres.sh
bash scripts/qa/test_observability_request_ids.sh
bash scripts/qa/test_llm_clarifications.sh
bash scripts/smoke-stage9.4.sh
```

Полная матрица тестов: [docs/testing/TEST_MATRIX.md](docs/testing/TEST_MATRIX.md)

## Документация

Оглавление (читать “как книгу”): [docs/DOCUMENTATION_INDEX.md](docs/DOCUMENTATION_INDEX.md)

## Staging first-run check

### Локально (тот же сценарий, что в Actions)
Поднятый compose-стек должен быть доступен на `http://localhost:8000`.
```bash
bash scripts/staging/first-run-check.sh
```

### Через GitHub Actions (manual)
Workflow: [.github/workflows/staging-first-run.yml](.github/workflows/staging-first-run.yml)

## Админка

Общий принцип:
- включается через переменные окружения (allowlist телефона + пароль)
- вход через админ-логин, затем токен/сессия используется для admin endpoints

Подробности:
- Runbook: [docs/admin/ADMIN_RUNBOOK.md](docs/admin/ADMIN_RUNBOOK.md)
- Security: [docs/admin/ADMIN_SECURITY.md](docs/admin/ADMIN_SECURITY.md)

