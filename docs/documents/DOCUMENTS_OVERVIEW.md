# Documents overview (registry → render jobs → PDF)

Этот раздел — «единая правда» про документы (doc_id), которые участвуют в Stage 9.4 (рендер-очередь + библиотека PDF).

## Источник истины (registry/config)

**Базовый реестр документов (file fallback):**
- `api/documents.v1.json`

**Как реестр попадает в рантайм:**
- В коде API используется конфиг-ключ `documents_registry`, который резолвится через `resolve_config()`.
- По умолчанию используется file-source (`CONFIG_SOURCE!=db`) и берётся `api/documents.v1.json`.
- Если `CONFIG_SOURCE=db`, то берётся активная валидная версия из `config_store` (и только если она `valid`), иначе выполняется fallback на файл.

Кодовые точки:
- `api/main.py`: `resolve_config()`, `_load_file_config()` и `_load_documents_registry()`.
- `api/main.py`: endpoints Stage 9.4: `POST /packs/{pack_id}/render`, `POST /packs/{pack_id}/render/{doc_id}`, `GET /packs/{pack_id}/documents`, `GET /files/{file_id}/download`.
- `api/worker.py`: загрузка PDF в S3 и создание `artifacts`/`artifact_files`.

## Как enabled/tier влияют на рендер и доступность

### Enabled/disabled
- Источник по умолчанию: поле `is_enabled` в registry.
- Оверлей из БД: таблица `document_access.enabled` (имеет приоритет над registry).

Влияние:
- `POST /packs/{pack_id}/render` и `GET /packs/{pack_id}/documents` **фильтруют документы** по «effective enabled».
- `POST /packs/{pack_id}/render/{doc_id}` возвращает `400 DOCUMENT_DISABLED`, если документ отключён.

### Free/paid (tier)
- Источник по умолчанию: поле `tier` в registry (`free|paid`).
- Оверлей из БД: `document_access.tier`.
- Переменные окружения:
  - `DOCS_FORCE_ALL_FREE=true` — принудительно делает effective tier = `free`.
  - `PAID_DOCS_VISIBLE=false` — влияет на `access.reason` для paid документов (в UI можно скрывать/блокировать).

Влияние:
- API возвращает `access` в `GET /packs/{pack_id}/documents`, где есть:
  - `tier`, `enabled`, `is_locked`, `reason`
- В текущей реализации **рендер не блокируется по tier** (рендер создаётся для enabled документов), но UI «Library» блокирует действия (скачивание/пересборка) если `is_locked=true`.

## Что именно рендерится (PDF, хранение, выдача)

### Рендер
- На каждый `doc_id` создаётся отдельный `render_job`.
- В текущей реализации содержимое документа — **заглушка**: `_build_render_request()` формирует секции с текстом "Базовый layout. Данные будут добавлены позже.".

### Хранение
- Worker кладёт PDF в S3 (MinIO) в bucket из `S3_BUCKET`.
- Object key: `renders/<render_job_id>/<doc_id>.pdf`.

### Как появляется `file_id`
- Worker создаёт запись в `artifacts` (kind: `<doc_id>_pdf`, meta включает `doc_id`, `pack_id`, `render_job_id`).
- Затем создаёт запись в `artifact_files`; её `id` и есть `file_id`.
- `GET /packs/{pack_id}/documents` при статусе `ready` резолвит `file_id` через `artifacts.meta.render_job_id`.

### Как скачивается
- Клиент использует `GET /files/{file_id}/download` (auth-required), API возвращает presigned URL (TTL 600 секунд).

## Список doc_id (из реального registry)

Реестр: `api/documents.v1.json` (version 1.0).

| doc_id | title (registry) | tier (registry) | is_enabled (registry) |
|---|---|---|---|
| free_report | Бесплатный отчёт | free | true |
| vacancy_profile | Профиль вакансии | paid | true |
| scorecard | Scorecard | paid | true |
| screening_script | Скрипт скрининга | paid | true |
| sourcing_pack | Sourcing pack | paid | true |
| hiring_pack | Hiring pack | paid | true |
| role_snapshot | Role snapshot | paid | true |
| budget_reality_check | Budget reality check | free | true |
| quality_report | Quality report | paid | true |
| manifest | Manifest | paid | true |
| interview_guide | Interview guide | paid | true |
| offer_template | Offer template | paid | true |

## Примечания по «источникам данных»

По факту текущего репо (Stage 9.4):
- Документы **не читают vacancy_kb или артефакты** для наполнения контентом.
- Единственные входные данные, которые попадают в render-request: `doc_id`, вычисленный `title`, `meta.pack_id`, `meta.session_id` и статические `sections`.
- На каждый `render_job` дополнительно пишется артефакт `config_snapshot` (best-effort) с текущими версиями/хэшами конфигов.
