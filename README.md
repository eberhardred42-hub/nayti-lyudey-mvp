# Найти людей — MVP

Актуальная версия релиза: см. файл `VERSION`.

## Быстрые ссылки (начать за 5 минут)

- Handover (что делать новому агенту): [HANDOVER_PROMPT.md](HANDOVER_PROMPT.md)
- Ops: старт и ритуал: [docs/ops/00_START_HERE.md](docs/ops/00_START_HERE.md)
- Правила разработки/релизов: [docs/ops/01_RULES.md](docs/ops/01_RULES.md)
- Debug runbook: [docs/ops/03_DEBUG_RUNBOOK.md](docs/ops/03_DEBUG_RUNBOOK.md)
- Документация проекта (индекс): [docs/DOCUMENTATION_INDEX.md](docs/DOCUMENTATION_INDEX.md)
- DEV/PROD на одном сервере: [docs/ENVIRONMENTS.md](docs/ENVIRONMENTS.md)
- Историография версий (что меняли и зачем): [docs/ops/06_VERSION_HISTORIOGRAPHY.md](docs/ops/06_VERSION_HISTORIOGRAPHY.md)

## Последние изменения (кратко)

- v2.11: Intro P0: детерминированный бриф ≤10 вопросов + STOP rule; UI confirm/correct; `intro_done` показывает free previews и locked docs без автогенерации.
- v2.10: DEV Deploy: добавлен итоговый summary (локал/домен/пинг/смоук) прямо в GitHub Actions run.
- v2.9: DEV Deploy: исправлен blocking sanity-check локального upstream (убран баг со stdin/heredoc → больше нет ложных `JSONDecodeError`).
- v2.9: DEV Deploy: проверки теперь безопасно парсят JSON только при 200 + `application/json`, добавлена диагностика при падении локального upstream.
- v2.8: добавлен ручной workflow диагностики DEV (`DEV Diagnose`).
- v2.8: DEV Deploy: sanity-check разделён на blocking (локальный upstream) и warn-only (домен), больше нет падений на `JSONDecodeError` при 502.
- v2.8: DEV Deploy: дефолтная LLM-модель по умолчанию совместима с Groq.

## Product Vision & User Journey (MVP) — SOURCE OF TRUTH

Что строим: продукт, который помогает нанимать людей через короткий бриф (≤ 10 вопросов) и набор готовых документов.

MVP флоу:
1) Пользователь вводит «кого хочу нанять».
2) Ассистент собирает бриф максимум за 10 вопросов.
3) После завершения брифа показываем заполненный бриф + результаты бесплатных документов.
4) Платные документы видны как опции, но **до оплаты не генерируются**.
5) После оплаты: генерим выбранные документы и списываем **150 руб за каждый успешно сгенерированный**.

Экономика:
- Free docs: доступны сразу после завершения брифа.
- Paid docs: 150 руб/док (= 15000 коп), списание только за успешный рендер (или debit → refund при fail).

## Ежедневные продуктовые чекпоинты (что считаем прогрессом)

- **A — LLM:** `POST /api/health/llm/ping` → 200 и есть `latency_ms` (реальный запрос наружу).
- **B — Brief:** пройти бриф ≤ 10 вопросов → `ready_to_search=true`.
- **C — Paid doc + wallet:** сгенерить 1 платный документ → появился `wallet.debit`, документ доступен на скачивание.

## Health / Observability (DEV)

- https://dev.naitilyudei.ru/api/health/llm
- https://dev.naitilyudei.ru/api/health/llm/ping
- https://dev.naitilyudei.ru/admin/logs

Trace namespace (обязательно): `auth.*`, `llm.*`, `brief.*`, `doc.*`, `payment.*`.

## Как работаем (задачи и PR)

Политика: любой продуктовый PR следует [docs/ops/01_RULES.md](docs/ops/01_RULES.md) и использует PR template.

- Одна задача за раз; 1 PR = 1 вертикальный кусок.
- Для продуктовых задач: bump `VERSION` (+1) и запись в истории версий.
- План дня: [docs/ops/DAILY_PLAN_TEMPLATE.md](docs/ops/DAILY_PLAN_TEMPLATE.md)
- Шаблон задачи: [docs/ops/04_TASK_TEMPLATE.md](docs/ops/04_TASK_TEMPLATE.md)
- Шаблон PR (расширенный): [docs/ops/05_PR_TEMPLATE.md](docs/ops/05_PR_TEMPLATE.md)

## Локальный запуск (минимум)

1) Поднять Docker stack:

```bash
docker compose -f infra/docker-compose.yml up --build
```

2) Открыть UI: http://localhost:3000

3) Быстрые тесты:

```bash
bash tests/quick-test.sh
```

## LLM: переключение провайдера (через env)

Коротко (цель на сегодня — Groq, без правок кода):
- Groq base_url: `https://api.groq.com/openai/v1`
- Нужные DEV secrets/vars: `DEV_LLM_BASE_URL`, `DEV_LLM_API_KEY`, `DEV_LLM_MODEL`

Клиент работает с любым OpenAI-compatible провайдером. Для стендов DEV/PROD конфигурация берётся **только из secrets/vars** (`DEV_LLM_*` / `PROD_LLM_*`).

Общее:
- `LLM_PROVIDER=openai_compat`
- `NLY_ENV=dev|prod` — выбирает, какие переменные использовать (`DEV_LLM_*` или `PROD_LLM_*`).

DEV/PROD (через secrets/vars):
- `DEV_LLM_BASE_URL` / `PROD_LLM_BASE_URL`
- `DEV_LLM_API_KEY` / `PROD_LLM_API_KEY`
- `DEV_LLM_MODEL` / `PROD_LLM_MODEL`

Локальная разработка (опционально, для удобства):
- `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (если `NLY_ENV` не задан).

Пресеты (задавайте через env, без правки кода):
- OpenAI: `LLM_BASE_URL=https://api.openai.com/v1`
- Groq: `LLM_BASE_URL=https://api.groq.com/openai/v1`
- Together: `LLM_BASE_URL=https://api.together.xyz/v1`
- Mistral: `LLM_BASE_URL=https://api.mistral.ai/v1`
- DeepSeek: `LLM_BASE_URL=https://api.deepseek.com`

Рекомендуемые стартовые модели (пример):
- Groq: `LLM_MODEL=llama-3.1-8b-instant` (или актуальная из их `/models`)
- DeepSeek: `LLM_MODEL=deepseek-chat`

DEV деплой ожидает (Secrets/Vars):
- `DEV_LLM_BASE_URL` (secret)
- `DEV_LLM_API_KEY` (secret)
- `DEV_LLM_MODEL` (var)

PROD деплой ожидает (Secrets/Vars):
- `PROD_LLM_BASE_URL` (secret)
- `PROD_LLM_API_KEY` (secret)
- `PROD_LLM_MODEL` (var)

Пруф “реально стучимся наружу”:
- ручной вызов `POST /api/health/llm/ping` (и workflow `LLM Ping (DEV)`) показывает `latency_ms`/`model`/`base_url`.

Важно: не предполагаем “бесплатность” — провайдер должен быть совместимым и иметь валидные кредиты/ключ.


## Полезные документы (глубже)

- Документы pipeline v1: [docs/DOCUMENTS_PIPELINE_V1.md](docs/DOCUMENTS_PIPELINE_V1.md)
- Runbook (setup/testing/troubleshooting): [docs/RUNBOOK.md](docs/RUNBOOK.md)
- Stages (история разработки по этапам): [docs/stages/](docs/stages/)

## Инварианты для ресёрча/изменений

1) UI ходит в API через `/api/*`, а FastAPI роуты без `/api` (префикс срезается прокси).
2) Никаких бинарников/рендеров в git (артефакты — только S3/MinIO).
3) DEV acceptance всегда включает реальный LLM ping.
