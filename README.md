Проект: Nayti-Lyudey MVP

Коротко:
Минимально работоспособный прототип (MVP) для генерации отчётов из Vacancy KB и демонстрации UI.

Quick start:
1. Собрать и запустить сервисы Docker:

   docker compose -f infra/docker-compose.yml up --build

2. Открыть UI: http://localhost:3000

Документация:
  docs/DOCUMENTATION_INDEX.md

Запуск тестов (локально):

python3 tests/unit/test_parsing_stage3.py
python3 tests/unit/test_free_report_generation.py
bash scripts/qa/test_vacancy_kb_flow.sh
bash scripts/qa/test_free_report_flow.sh

Legacy-команды сохранены (wrapper’ы):

python3 tests/test-parsing.py
python3 tests/test-free-report.py
bash tests/test-stage3.sh
bash tests/test-stage4.sh

Матрица тестов:
  docs/testing/TEST_MATRIX.md

