# docs/ops — START HERE

## Роли
- Product owner (ты): формулирует цель/ограничения, принимает acceptance.
- GitHub AI agent (dev): делает изменения в репозитории и оформляет PR.
- ChatGPT (project/tech lead): ведёт процесс, держит правила, режет задачи до «одна задача за раз».

## Режим работы
- Одна задача за раз.
- Каждая задача заканчивается 2–3 короткими проверками (curl/Actions/logs).
- GitHub Actions first; SSH — крайний случай.

## Где правда (Source of truth)
- Продукт/флоу: README → “Product Vision & User Journey (MVP)”.
- Правила: docs/ops/01_RULES.md.
- Факт работы: DEV стенд + /admin/logs + /api/health/llm + /api/health/llm/ping.

## Ежедневный ритуал
1) Новый чат начинается с чтения:
   - /HANDOVER_PROMPT.md
   - docs/ops/01_RULES.md
2) Формулируем «эпик дня» и 2–3 продуктовых чекпоинта.
3) Делаем один вертикальный кусок за раз (1 PR = 1 кусок).
4) Для продуктовых задач: bump VERSION (+1) и запись в README changelog.
5) Evidence хранится как:
   - ссылка на GitHub Actions run
   - и/или вывод curl
   - и/или один скрин Network/логов (ровно один артефакт на проблему)

См. также: docs/ops/DAILY_PLAN_TEMPLATE.md
