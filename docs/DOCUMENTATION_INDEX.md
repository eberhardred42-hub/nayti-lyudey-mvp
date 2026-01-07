# Документация (staging release)

Этот индекс — “оглавление книги” для staging-релиза. Он ориентирован на актуальные этапы: Stage 9.3 (S3/MinIO артефакты), Stage 9.4 (render queue + Library) и admin-пакет (план 1.1).

## Рекомендуемый порядок чтения (как книгу)
1. [../README.md](../README.md) — что это за проект и как запустить локально.
2. [REPO_MAP.md](REPO_MAP.md) — карта репозитория.
3. Stage 9.3 (storage):
   - [stages/stage9/STAGE9_3_SUMMARY.md](stages/stage9/STAGE9_3_SUMMARY.md)
   - [stages/stage9/STAGE9_3_IMPLEMENTATION.md](stages/stage9/STAGE9_3_IMPLEMENTATION.md)
4. Stage 9.4 (render pipeline):
   - [stages/stage9.4/STAGE9.4_SUMMARY.md](stages/stage9.4/STAGE9.4_SUMMARY.md)
   - [stages/stage9.4/STAGE9.4_IMPLEMENTATION.md](stages/stage9.4/STAGE9.4_IMPLEMENTATION.md)
5. Документы (реестр и doc_id):
   - [documents/DOCUMENTS_OVERVIEW.md](documents/DOCUMENTS_OVERVIEW.md)
6. Админка (операционка + безопасность):
   - [admin/ADMIN_PLAN_1_1.md](admin/ADMIN_PLAN_1_1.md)
   - [admin/ADMIN_RUNBOOK.md](admin/ADMIN_RUNBOOK.md)
   - [admin/ADMIN_SECURITY.md](admin/ADMIN_SECURITY.md)
7. Тестирование:
   - [testing/TEST_MATRIX.md](testing/TEST_MATRIX.md)
8. Деплой / staging:
   - [deploy/README.md](deploy/README.md)
   - (доп.) [RUNBOOK.md](RUNBOOK.md)

---

## Локальная разработка

### Быстрый старт
- Основной старт: `./start-dev.sh` (обёртка над локальным dev-стеком)
- Инфра/сервисы: [../infra/docker-compose.yml](../infra/docker-compose.yml)

### Smoke/QA сценарии
- Stage 9.3 (S3/MinIO): `./scripts/smoke-stage9.3.sh`
- Stage 9.4 (render queue): `./scripts/smoke-stage9.4.sh`
- Админка (минимальный smoke): `./scripts/smoke-admin.sh`

Для полного перечня и актуальных путей тестов см. [testing/TEST_MATRIX.md](testing/TEST_MATRIX.md).

---

## Stage 9.3 — артефакты в S3/MinIO

**Что это даёт**: хранение файлов (PDF/прочие) в S3-совместимом сторадже (MinIO локально), метаданные в Postgres, скачивание через presigned URL.

- Итоги: [stages/stage9/STAGE9_3_SUMMARY.md](stages/stage9/STAGE9_3_SUMMARY.md)
- Реализация/ранбук: [stages/stage9/STAGE9_3_IMPLEMENTATION.md](stages/stage9/STAGE9_3_IMPLEMENTATION.md)

Ключевые API:
- `GET /files/{file_id}/download` → presigned URL
- `GET /me/files` → список файлов пользователя

---

## Stage 9.4 — render queue + Library

**Что это даёт**: асинхронный рендер PDF по “паку” документов через Redis-очередь и worker.

- Итоги: [stages/stage9.4/STAGE9.4_SUMMARY.md](stages/stage9.4/STAGE9.4_SUMMARY.md)
- Реализация: [stages/stage9.4/STAGE9.4_IMPLEMENTATION.md](stages/stage9.4/STAGE9.4_IMPLEMENTATION.md)

Ключевые API:
- `POST /packs/{pack_id}/render`
- `POST /packs/{pack_id}/render/{doc_id}`
- `GET /packs/{pack_id}/documents`

---

## Документы (doc_id и реестр)

Реестр документов — “single source of truth” для того, какие документы существуют и какие `doc_id` поддерживаются.

- Обзор: [documents/DOCUMENTS_OVERVIEW.md](documents/DOCUMENTS_OVERVIEW.md)
- Детали по документам: папка [documents/](documents/)

---

## Админка (план 1.1)

Что покрывает:
- безопасный вход в админку и сессии
- управление версиями конфигов (draft/validate/dry-run/publish/rollback)
- управление доступностью/tiers для документов
- панель render jobs (просмотр/детали/безопасный requeue)
- просмотр алертов и логов

Документация:
- План: [admin/ADMIN_PLAN_1_1.md](admin/ADMIN_PLAN_1_1.md)
- Runbook: [admin/ADMIN_RUNBOOK.md](admin/ADMIN_RUNBOOK.md)
- Security: [admin/ADMIN_SECURITY.md](admin/ADMIN_SECURITY.md)

---

## Тестирование

Единая точка входа:
- [testing/TEST_MATRIX.md](testing/TEST_MATRIX.md)

---

## Деплой / staging

Стартовая точка:
- [deploy/README.md](deploy/README.md)

Если нужно отладить инцидент/непонятный кейс:
- [RUNBOOK.md](RUNBOOK.md)

---

## Исторические stage-доки (legacy)

В репозитории остаются stage3–stage7 документы (как история разработки). Они могут ссылаться на устаревшие тестовые команды и пути; актуальный список тестов см. в [testing/TEST_MATRIX.md](testing/TEST_MATRIX.md).

```

