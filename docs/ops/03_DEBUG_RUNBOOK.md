# Debug runbook (DEV)

## Если DEV 502
Быстрый чеклист (по цепочке):
1) Caddy: жив ли контейнер, нет ли 502 на /api/docs.
2) Front: жив ли front контейнер, открывается ли /.
3) API: отвечает ли /api/health и /api/health/db.
4) Compose: нет ли падающих сервисов (`docker compose ps`).
5) Логи: caddy → front → api (короткий tail).

Acceptance (минимум):
- `curl -fsS https://dev.naitilyudei.ru/api/docs -I | head -n 5`

## Если LLM “не зовётся”
1) Проверить конфиг:
- `GET /api/health/llm` (provider_effective/base_url/model/key_present/reason)
2) Проверить реальный ping:
- `POST /api/health/llm/ping` (ok=true, latency_ms)
3) Посмотреть /admin/logs по префиксам llm.*
4) Проверить runtime env в workflow (секреты/vars DEV_LLM_*).

## Если документы “не рендерятся”
1) Убедиться, что render/worker живы (compose ps).
2) Проверить MinIO/S3 доступность.
3) В /admin/logs найти doc.* события: render_request/render_response/s3_put.
4) Если есть очередь/worker — проверить, что задачи не застряли.

## “Ровно 1 артефакт” от продукта
Просим один из вариантов:
- link на конкретный GitHub Actions run (job log) ИЛИ
- один скрин Network (DevTools) ИЛИ
- один tail логов сервиса через workflow Stage Logs.

## Если gh workflow run/dispatch даёт 422 (НОВОЕ)
1) Проверить, что workflow в main содержит workflow_dispatch:
- `gh workflow view <id|name> --yaml | find "workflow_dispatch"`
2) Если YAML показывает workflow_dispatch, а API 422:
- GitHub видит старую версию workflow (не main/не тот ref/не запушено)
- проверь ref/branch и повтори запуск на main.
