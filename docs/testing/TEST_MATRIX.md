# Матрица тестов

Цель: понятные имена тестов + стабильные legacy-команды.

## Быстрые локальные проверки (без Docker)

- `bash scripts/qa/quick_validate_repo.sh` — быстрая валидация репозитория (py_compile + парсинг + базовые проверки файлов).
- `python3 tests/unit/test_parsing_stage3.py` — smoke-тесты парсинга Stage 3 (без FastAPI).
- `python3 tests/unit/test_free_report_generation.py` — unit-тест генерации free report (без FastAPI).

## Интеграционные тесты (нужен поднятый стек или Docker)

| Что проверяет | Новый канонический скрипт | Legacy wrapper (не ломаем CI/привычки) | Требования |
|---|---|---|---|
| Vacancy KB flow (Stage 3) | `bash scripts/qa/test_vacancy_kb_flow.sh` | `bash tests/test-stage3.sh` | API на `:8000` (и опционально Front на `:3000`) |
| Free report flow (Stage 4) | `bash scripts/qa/test_free_report_flow.sh` | `bash tests/test-stage4.sh` | API на `:8000` |
| Postgres persistence (Stage 5) | `bash scripts/qa/test_persistence_postgres.sh` | `bash tests/test-stage5.sh` | Docker (желательно) или поднятый стек |
| Observability / request-id + debug (Stage 6) | `bash scripts/qa/test_observability_request_ids.sh` | `bash tests/test-stage6.sh` | Docker (желательно) или поднятый стек |
| LLM clarifications + quick replies (Stage 7) | `bash scripts/qa/test_llm_clarifications.sh` | `bash tests/test-stage7.sh` | Docker (желательно) или поднятый стек |

## Политика совместимости

- Все старые имена (`tests/test-stage*.sh`, `tests/test-parsing.py`, `tests/test-free-report.py`, `tests/quick-test.sh`) оставлены как wrapper’ы.
- Wrapper печатает `DEPRECATED` в stderr и `exec`/`runpy`-запускает канонический тест, сохраняя exit code.
