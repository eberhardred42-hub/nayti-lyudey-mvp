Проект: Nayti-Lyudey MVP

Версия: см. файл VERSION

## Изменения за 2026-01-09

- v1.7: Observability — trace-события (intro/LLM/render/S3) теперь пишутся в `artifacts` и видны в `/admin/logs`.
- v1.7: CI переведён в manual-only; DEV deploy оставляет только быстрые curl-проверки.
- v1.8: LLM обязателен (OpenRouter) — деплой падает без ключа; `/api/health/llm` теперь показывает provider/model/base_url/key_present/mode.
- v1.10: GitHub Actions — исправлена генерация runtime env (`.env` на сервере), чтобы compose стабильно подхватывал `LLM_*`/`OPENROUTER_API_KEY`.
- v2.0: Guest auth без логина — `POST /sessions` выдаёт HttpOnly cookie (Domain=.naitilyudei.ru), `/api/me/documents` для гостя возвращает 200 вместо 401; фронт шлёт cookies через `credentials: "include"`.
- v2.1: DEV Deploy — smoke checks сделаны non-blocking (warn-only) с ретраями.
- v2.2: Auth self-heal — при битой/просроченной guest-cookie она сбрасывается и перевыдаётся (без 401); Domain разведен для DEV/PROD. Добавлен ручной `POST /api/health/llm/ping`.
- v2.3: DEV “STOP 401” — гостевой auth сделан железобетонным: host-only cookie `__Host-nly_auth` (без Domain) + cleanup legacy `nly_auth`; `POST /api/sessions` и `GET /api/me/documents` никогда не возвращают 401 без Bearer. Добавлен `GET /api/health/auth`.
- v2.4: LLM провайдер теперь переключается только env-переменными (`LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`); OpenRouter больше не “особенный” (это просто base_url). PROD deploy поддерживает `PROD_LLM_*`.

## Как переключить LLM провайдера (через env)

Клиент работает с любым OpenAI-compatible провайдером.

- `LLM_PROVIDER=openai_compat`
- `LLM_BASE_URL` — базовый URL (OpenAI-compatible)
- `LLM_API_KEY` (или `OPENROUTER_API_KEY`) — ключ (но base_url нужно указать явно)
- `LLM_MODEL` — модель (строка, зависит от провайдера)

Важно: OpenRouter не “особенный”. Если вы задаёте только ключ (`OPENROUTER_API_KEY`/`OPENAI_API_KEY`) без `LLM_BASE_URL`, то LLM будет считаться не настроенным.

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

## Изменения за 2026-01-08
 v1.8: /health/llm теперь показывает key_source/provider_effective/reason; LLM_REQUIRE_KEY=true отключает silent mock и даёт 503 при отсутствии ключа
- Интро-диалог: добавлен минимальный A/B/C/D сценарий (текст вакансии / своими словами / короткие вопросы / пропустить) с подтверждением и возможностью исправить.
- v1.9: интро-диалог без циклов: детерминированный P0 порядок, STOP после DONE, без спама артефактами; в /admin/logs видны intro_missing_fields/intro_done/intro_stop
- Документы: добавлен `POST /documents/generate_pack` — последовательная генерация всего бесплатного `auto_generate`-пака.
- Документы: идемпотентность по `(user_id, session_id, doc_id)` и `force=true` для принудительной регенерации.
- Промпты документов: добавлены per-doc шаблоны для всех doc_id бесплатного пака в `api/prompts/docs/<doc_id>/`.
- Смоук-тесты: обновлены под новый интро-флоу и формат ответа `generate_pack`.

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

# Stage-стенд (MVP) — naitilyudei.ru

## Цель стенда (что считается "готово")
Стенд считается готовым, когда:
- сайт открывается по HTTPS на реальном домене `https://naitilyudei.ru/`
- UI позволяет пройти end-to-end флоу (создание сессии + отправка сообщения)
- понятно, где смотреть логи (Caddy / front / api / ml / render)
- деплой воспроизводим (git pull + docker compose up)

На текущий момент: **E2E флоу работает**  
`POST /api/sessions -> 200`  
`POST /api/chat/message -> 200`

---

## Инфраструктура (факты)
- Провайдер: Yandex Cloud VM (Ubuntu)
- Public IP: `84.252.135.148` (статический)
- Internal IP: `10.130.0.20`
- DNS: `naitilyudei.ru -> 84.252.135.148` (A-запись в Timeweb)
- Firewall (security group):
  - SSH 22 открыт только с доверенного IP (например, `87.248.239.14/32`)
  - 80/443 открыты наружу (0.0.0.0/0)

---

## Репозиторий и директории
- Репо: `https://github.com/eberhardred42-hub/nayti-lyudey-mvp.git`
- Путь на сервере: `~/app`
- Docker Compose: `~/app/infra/docker-compose.yml`

---

## Сервисы (docker compose)
Поднимаются контейнеры:
- `front`  : `:3000`
- `api`    : `:8000`
- `ml`     : `:8001`
- `render` : `:8002` (внутри контейнера 8000)
- `db`     : `:5432`
- `redis`  : `:6379`
- `minio`  : `:9000-9001`

Проверка статуса:
```bash
cd ~/app
docker compose -f infra/docker-compose.yml ps

```


Внешний вход: Caddy (TLS + reverse proxy)

Caddy запускается отдельным контейнером в host network:

docker run -d --name caddy --restart unless-stopped --network host \
  -v "$PWD/Caddyfile:/etc/caddy/Caddyfile" \
  -v caddy_data:/data -v caddy_config:/config caddy:2

Рабочий Caddyfile (ВАЖНО)

Ключевой момент: фронт ходит на /api/*, а FastAPI внутри имеет роуты без /api.
Нужно проксировать /api/* в backend и срезать префикс /api.

naitilyudei.ru {
  # /api/* -> backend, но без префикса /api
  handle_path /api/* {
    reverse_proxy localhost:8000
  }

  # /health -> backend (если используется)
  handle /health* {
    reverse_proxy localhost:8000
  }

  # всё остальное -> фронт
  reverse_proxy localhost:3000
}


Перезапуск caddy после правок:

docker restart caddy
docker logs --tail=200 caddy

Быстрые проверки

Проверка, что API доступен с домена через префикс /api:

curl -I https://naitilyudei.ru/api/docs | head -n 5

End-to-end юзерфлоу (как проверяем)

Открыть https://naitilyudei.ru/

DevTools → Network → Preserve log

Нажать “Найти людей”, отправить сообщение

Убедиться, что:

POST https://naitilyudei.ru/api/sessions → 200

POST https://naitilyudei.ru/api/chat/message → 200

Логи и дебаг (где смотреть ошибки)
Caddy
docker logs --tail=200 caddy

Сервисы compose
cd ~/app
docker compose -f infra/docker-compose.yml logs --tail=200 front
docker compose -f infra/docker-compose.yml logs --tail=200 api
docker compose -f infra/docker-compose.yml logs --tail=200 ml
docker compose -f infra/docker-compose.yml logs --tail=200 render
docker compose -f infra/docker-compose.yml logs --tail=200 render-worker

Проверка, что порты слушаются
ss -lntp | egrep ':(80|443|3000|8000|8001|8002|5432|6379|9000|9001)\b' || true

Обновление стенда (деплой)

Обычный цикл:

cd ~/app
git pull
docker compose -f infra/docker-compose.yml up -d --build
docker restart caddy

---

# Система: полное описание (для чтения/ресёрча кода)

## TL;DR

Это full-stack MVP:

- `front/` (Next.js) — одностраничник + прокси `/api/*`.
- `api/` (FastAPI) — сессии, чат, документы, админка, storage.
- `render/` — сервис рендера PDF из markdown.
- `db`/`redis`/`minio` — Postgres + очередь + S3-совместимое хранилище.

Ключевой E2E флоу: **ввод профессии → интро-диалог (бриф) → генерация PDF-документа → скачивание**.

## Сервисы и роли

См. `infra/docker-compose.yml`:

- `front` — Next.js UI. Важно: браузер никогда не ходит напрямую в `api`; всё через `/api/*`.
- `api` — FastAPI. Основные маршруты: сессии, чат, документы, health.
- `render` — HTTP сервис `POST /render/pdf` (markdown → PDF).
- `render-worker` — выполняет фоновые задачи, использует Redis.
- `db` — Postgres.
- `redis` — Redis.
- `minio` — S3 API для файлов.

## Границы и роутинг (Caddy + /api)

Критичный инвариант:

- UI обращается к API через `/api/*`.
- FastAPI роуты определены **без префикса `/api`**.
- Поэтому Caddy/Next proxy должны **срезать** `/api` (через `handle_path /api/*`).

## Данные и хранение

Две большие категории данных:

1) **Состояние/метаданные** в Postgres (сессии, сообщения, документы, файлы, job’ы).
2) **Файлы** (PDF) в S3/MinIO (bucket + key), с раздачей через download/presign/stream.

## Чат: как устроен интро-диалог

Точка входа: `POST /chat/message` (через фронтовый `/api/chat/message`).

Основные типы сообщений:

- `intro_start` — выдаёт стартовый вопрос и быстрые ответы.
- `intro_message` — принимает текст пользователя, обновляет `brief_state`, выдаёт следующий вопрос.

Текущий интро-флоу (минимальный):

- A) вставить текст вакансии
- B) описать своими словами
- C) ответить на короткие вопросы
- D) пропустить и начать

После сбора вводных ассистент показывает краткое резюме и спрашивает «Все верно?» (можно подтвердить или отправить правку).

В ответе возвращаются поля:

- `reply` / `assistant_text` — текст ассистента.
- `quick_replies` — массив до 4 кнопок.
- `brief_state` + `brief_patch` — текущее состояние брифа и патч.
- `ready_to_search` — признак, что бриф заполнен достаточно.

### Quick replies: динамика vs fallback

- Кнопки (`quick_replies`) используются для A/B/C/D выбора и для подтверждения.
- При `LLM_PROVIDER=mock` флоу должен оставаться рабочим (без падений).

## Documents pipeline v1 (LLM → PDF → S3)

Каталог документов лежит в `api/documents/catalog.json`.

Промпты документов лежат в `api/prompts/docs/<doc_id>/`.

Схема:

1) `POST /documents/generate` — создаёт/обновляет запись документа, генерирует markdown (LLM или fallback).
2) markdown отправляется в `render` → получаем PDF.
3) PDF загружается в S3/MinIO и регистрируется в Postgres.
4) UI видит PDF в `/me/documents` и даёт скачать через `/documents/{id}/download`.

## LLM: как подключается

LLM обёрнут в `api/llm_client.py` и использует OpenAI-compatible API.

Ключевые env:

- `LLM_PROVIDER` (`mock` или `openai_compat`)
- `LLM_BASE_URL`, `LLM_API_KEY`
- `OPENROUTER_API_KEY`, `OPENAI_API_KEY` (опционально)
- `LLM_MODEL`

Важно: большая часть флоу должна **деградировать**, но не падать при `LLM_PROVIDER=mock`.

## Тестирование и смоки

Локально:

```bash
bash tests/quick-test.sh
```

Локальный E2E смоук documents v1 (поднимает compose и проверяет PDF download):

```bash
bash scripts/smoke-documents-v1.sh
```

DEV e2e (не трогает контейнеры, только ходит в API):

```bash
BASE_URL="https://dev.naitilyudei.ru/api" bash scripts/smoke-documents-v1-dev.sh
```

## Последние изменения (кратко)

См. историю `git log -n 10 --oneline`. В последних коммитах:

- Интро-диалог: минимальный A/B/C/D флоу с подтверждением/исправлением (контракт `assistant_text/quick_replies/brief_state/ready_to_search` сохранён).
- Документы: `POST /documents/generate_pack` — последовательная генерация всего бесплатного `auto_generate`-пака (строгий список из `api/documents/catalog.json`, без `search_brief`).
- Идемпотентность документов: кеш по `(user_id, session_id, doc_id)` + `force=true` для принудительной регенерации.
- Промпты: добавлены per-doc шаблоны для всех doc_id бесплатного пака в `api/prompts/docs/<doc_id>/`.
- Смоуки обновлены под новый интро-флоу и формат ответа `generate_pack`.

## Инструкция для ChatGPT-ресёрчера

Если вы используете другой LLM/агент для анализа кода, держитесь этих правил:

1) Всегда сохраняйте инвариант `/api`-префикса (UI) vs роутов FastAPI (без `/api`).
2) Любой прокси-роут Next.js должен быть устойчив к пустому/не-JSON ответу.
3) Любые изменения должны проверяться хотя бы `bash tests/quick-test.sh` и, по возможности, DEV smoke.
4) Не “улучшайте” UX без запроса: это MVP, главное — воспроизводимый E2E.
