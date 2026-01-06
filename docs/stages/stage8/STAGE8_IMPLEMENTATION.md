# Stage 8: Implementation — Schemas, Repair/Fallback, Quality

## 1) Контракты и слои артефактов

**Идея:** один и тот же pack всегда состоит из двух слоёв:
- `user_result` — то, что «показываем пользователю» (рабочие артефакты)
- `trace` — техническая диагностика, стабильно сохраняемая для отладки

Эталонные JSON-примеры лежат в `contracts/` (v1). Внутри артефактов используем:
- `kind` — основной дискриминатор типа артефакта
- `meta.legacy_kind` — обратная совместимость для старых названий (`tasks_summary`, `screening_questions`, `sourcing_pack`)

## 2) ML как source-of-truth схем

### Вход: `vacancy_profile.v1`
В ML вход валидируется Pydantic-моделью `VacancyProfileV1`.
- Некорректный ввод → `HTTP 400` с `detail.errors`.
- Пример: отсутствие `compensation.range.max` обязано давать 400.

### Выход: `hiring_pack.v1`
ML собирает `hiring_pack` и валидирует его `HiringPackV1` перед возвратом.

### Жёсткое правило Scorecard
`scorecard_json.anchors` должен содержать score 1..5 (ровно/валидно).

## 3) Extract / Repair / Fallback

### Extract
Модуль `ml/json_extract.py` пытается извлечь JSON объект из:
- «чистого» JSON
- fenced code block ```json ... ```
- текста с встроенным `{...}`

Если JSON не извлекается → считаем ответ LLM невалидным.

### Validate
После extract валидируем bundle как `LLMGeneratedArtifactsV1`.

### Repair (до 2 попыток)
Если extract/validate не прошли:
- формируем repair prompt (только JSON, без комментариев)
- вызываем LLM ещё раз
- повторяем максимум 2 раза

События логов:
- `llm_json_extract_failed`
- `llm_schema_validation_failed` (с sanitzed errors)
- `llm_repair_attempt` (attempt=1/2)
- `llm_repair_ok` / `llm_repair_failed`

### Fallback
Если repair не помог:
- строим pack детерминированными билдерами
- выставляем `degraded` качество и warnings (`FALLBACK_USED`, `LLM_OUTPUT_INVALID`)

Цель: **ML всегда возвращает 200 с pack**, если вход валиден, даже при плохом LLM.

## 4) Quality gates и `quality_report`

### Где находится
- `trace.artifacts[]` содержит обязательный `quality_report`.
- `trace.quality` содержит копию того же content (удобно читать без поиска артефакта).

### Поля `quality_report`
- `summary.status`: `pass | degraded | fail`
  - `pass`: все gates true и нет forced-degraded причин
  - `degraded`: любой gate false или был fallback
  - `fail`: `schema_ok=false`
- `gates`: словарь булевых checks
- `score`: число 0..1 (среднее по gates)
- `warnings[]`: коды

### Как вычисляются gates
Реализация: `ml/quality.py`.

- `schema_ok` — сейчас трактуется как «выходной pack собирается без ошибок», а не «LLM ответ валиден». Для LLM-невалидности используем warnings.
- `coverage_ok` — присутствуют обязательные kinds в обоих слоях.
- `actionability_ok` — в `free_report_json.next_steps` есть непустые шаги (или в `free_report_md` есть секция шагов).
- `comparability_ok` — есть `scorecard_json` и валиден anchors 1..5.
- `risk_checks_ok` — если `profile.role.risk_level=high`, то должен присутствовать `compliance_checks_json`.
- `no_emojis_ok` — эвристика по Unicode диапазонам emoji.
- `tone_ty_ok` — лёгкая эвристика по «плохим маркерам».

Warnings-коды (основные):
- `COMPARABILITY_SCORECARD_MISSING`
- `COMPARABILITY_ANCHORS_INVALID`
- `ACTIONABILITY_MISSING`
- `RISK_COMPLIANCE_CHECKS_MISSING`
- `EMOJIS_PRESENT`
- `TONE_BAD`
- `FALLBACK_USED`
- `LLM_OUTPUT_INVALID`

## 5) Persist артефактов в API (Postgres)

### Нормализация и формат
API сохраняет каждый артефакт в таблицу `artifacts` с полями:
- `kind`
- обязательный `format` (`json | md | text`)
- `payload_json` или `payload_text`

### `manifest` в DB
API всегда пишет отдельный DB-артефакт `manifest` с `payload_json.items` — список `{artifact_id, kind, format}`.

Важно: внутри ML pack `manifest` может иметь другую структуру content (например `content.artifacts`). Для отладки persistence ориентируйся на DB-версию через `/artifacts`.

### Как смотреть артефакты
- `GET /artifacts?session_id=...` возвращает массив, где у каждого есть `format`, `payload_json`, `payload_text`, `meta`.

## 6) Mock режимы (для CI)

### Зачем
Чтобы CI тестировал repair/fallback/quality без сетевых вызовов к OpenRouter/провайдерам.

### Как работает
- ML: если `MOCK_MODE` установлен и `llm_call` не передан напрямую, используется встроенный mock LLM.
- API: если `MOCK_MODE` установлен, LLM-клиент для уточняющих вопросов принудительно работает в `mock`.

### Режимы
- `good` — валидный JSON bundle
- `non_json` — не-JSON (приводит к fallback)
- `wrapped_json` — JSON внутри code fence
- `missing_fields` — первая попытка без поля → repair → валидный bundle

## 7) Локальный прогон и отладка

### Unit (без docker)
- `MOCK_MODE=non_json /workspaces/nayti-lyudey-mvp/.venv/bin/python tests/test-stage8-repair.py`
- `/workspaces/nayti-lyudey-mvp/.venv/bin/python tests/test-stage8-quality.py`

### Интеграция (docker)
- `MOCK_MODE=good python3 tests/test-stage8-artifacts.py`
  - тест сам поднимет compose, дернет `/ml/job`, затем проверит `/artifacts`.

### Что проверять в artifacts
- Наличие `kind=quality_report` и его `payload_json.gates`/`payload_json.score`/`payload_json.warnings`.
- Наличие `kind=manifest` и `payload_json.items`.
- У каждого артефакта заполнен `format`.
