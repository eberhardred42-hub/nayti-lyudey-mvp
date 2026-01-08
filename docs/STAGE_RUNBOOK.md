# Stage runbook

## Что где
- Front: https://naitilyudei.ru/
- API docs: https://naitilyudei.ru/api/docs
- API health: https://naitilyudei.ru/api/health (если есть) или /health (в зависимости от роутинга)

## Как деплоим (без SSH)
1) Merge в `main` (или workflow_dispatch)
2) GitHub Actions → `Stage Deploy` → зелёный статус
3) Проверка: `Stage Smoke Deep` (ручной) или smoke step в deploy

## Как смотреть статус/логи (без SSH)
- GitHub Actions:
  - `Stage Status` — покажет docker compose ps + короткие логи
  - `Stage Logs` — tail логов сервисов
  - `Stage Smoke Deep` — HTTP проверки /, /api/docs, /api/health

## Частые проблемы
### 404 на /api/*
Причина: Caddy проксирует всё на front.
Решение: проверить Caddyfile в репозитории и что он реально смонтирован в контейнер.

### Ошибка Caddy "heredoc … got 'EOF'"
Причина: в /etc/caddy/Caddyfile попала строка вида `<<'EOF'` (heredoc не выполнился).
Решение: не генерировать Caddyfile heredoc'ом в рантайме. Хранить Caddyfile в репе и монтировать как файл.

### Runner не выполняет job
Проверить:
- Repo Settings → Actions → Runners: runner online
- Labels: `self-hosted`, `stage`
- На VM запущен systemd service runner (если всё же нужен SSH — только для аварий)
