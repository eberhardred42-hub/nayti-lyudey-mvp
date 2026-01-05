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

python3 tests/test-parsing.py
python3 tests/test-free-report.py
bash tests/test-stage3.sh
bash tests/test-stage4.sh

