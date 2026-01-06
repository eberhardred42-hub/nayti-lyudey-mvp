# Stage 8: Schemas v1 + Repair/Fallback + Quality Gates

## Что добавили
- Контракты v1 как эталоны (JSON-примеры) и договорённости по `kind`/слоям: `contracts/`.
- ML как source-of-truth для схем: строгая валидация входного `vacancy_profile` и выходного `hiring_pack`.
- Надёжный пайплайн обработки ответов LLM: extract → validate → repair (до 2 попыток) → fallback.
- Quality gates (формализованная «полезность») + обязательный артефакт `quality_report` в каждом pack.
- Детеминированные mock-режимы для CI (`MOCK_MODE`), чтобы не было внешних сетевых вызовов.

## Эндпоинты и data-flow
- ML:
  - `POST /run` — принимает `vacancy_profile.v1`, возвращает `hiring_pack.v1`.
  - `GET /health` — health.
- API:
  - `POST /ml/job` — дергает ML `/run`, нормализует и сохраняет артефакты в Postgres.
  - `GET /artifacts?session_id=...` — отдаёт сохранённые артефакты.

## Обязательные артефакты (оба слоя)

### user_result.artifacts (обязательные kinds)
- `role_snapshot_json`
- `sourcing_pack_json`
- `screening_script_json`
- `budget_reality_check_json`
- `scorecard_json` (anchors 1..5)
- `free_report_json`
- `free_report_md`
- `compliance_checks_json` — обязателен логически для `risk_level=high` (см. gate `risk_checks_ok`)

### trace.artifacts (обязательные kinds)
- `manifest`
- `quality_report`

Дополнительно в trace есть «сводка качества» `trace.quality` (копия content из `quality_report`).

## Что валидируем (schemas v1)
- Вход ML: `vacancy_profile` (включая обязательный `compensation.range.max`). Некорректный ввод → `400`.
- Выход ML: `hiring_pack` + вложенные артефакты.
- Scorecard anchors: строго scores 1..5.

## Repair pipeline
1. LLM возвращает текст.
2. Извлекаем JSON даже если он «обёрнут» (code fences/текст вокруг/встроенный объект).
3. Валидируем по Pydantic-схеме.
4. Если невалидно — делаем до 2 repair-попыток (просим вернуть только JSON по схеме).
5. Если всё равно плохо — fallback: собираем pack детерминированно и помечаем качество как `degraded` + warnings.

Логи (JSON lines) по шагам: `llm_json_extract_failed`, `llm_schema_validation_failed`, `llm_repair_attempt`, `llm_repair_ok`, `llm_repair_failed`, `fallback_used`.

## Quality gates
Артефакт `quality_report` содержит:
- `gates` (булевы проверки)
- `score` (0..1)
- `warnings[]` (коды)

Основные gates:
- `schema_ok`
- `coverage_ok`
- `actionability_ok`
- `comparability_ok`
- `risk_checks_ok`
- `tone_ty_ok`
- `no_emojis_ok`

## Как отлаживать по артефактам
1. Запусти сервисы и создай `session_id`.
2. Вызови `POST /ml/job`.
3. Открой `GET /artifacts?session_id=...`.
4. Ищи:
   - `kind=manifest` (в DB-версии у него `payload_json.items` — список `{artifact_id, kind, format}`)
   - `kind=quality_report` (gates/score/warnings)
   - наличие `format` у каждого артефакта (`json|text|md`) и корректное разнесение в `payload_json` / `payload_text`.

## Mock режимы (CI / локально)
Переменная `MOCK_MODE` отключает любые внешние LLM-вызовы.

Поддерживаемые значения:
- `good`
- `non_json`
- `wrapped_json`
- `missing_fields`

Примеры:
- Unit tests: `MOCK_MODE=non_json /workspaces/nayti-lyudey-mvp/.venv/bin/python tests/test-stage8-repair.py`
- Docker compose: `MOCK_MODE=wrapped_json docker compose -f infra/docker-compose.yml up -d --build`

## Тесты Stage 8
- `tests/test-stage8-schemas.py` — валидация схем и ошибок 400.
- `tests/test-stage8-repair.py` — repair/fallback сценарии (через `MOCK_MODE`).
- `tests/test-stage8-quality.py` — quality gates (happy path + anchors missing).
- `tests/test-stage8-artifacts.py` — docker-интеграция сохранения артефактов.
