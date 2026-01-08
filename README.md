Проект: Nayti-Lyudey MVP

Версия: см. файл VERSION

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
