# Авторизация (stage)

Этот документ описывает упрощённую авторизацию для stage/локальной среды.

## Пользовательский вход (OTP)

- Введите любой номер телефона (RU).
- Нажмите «Получить код».
- Введите 6-значный код: `906090`.

Поведение включается через env:
- `SMS_PROVIDER=mock`
- `STAGE_STATIC_OTP_CODE=906090`

## Вход как админ (повышение после user-login)

После успешного user-login сервер возвращает `is_admin_candidate`.

Если ваш телефон в allowlist, UI предложит «Войти как админ?».

Stage-учётные данные:
- Телефон в allowlist: `+79062592834`
- PIN админа: `1573`

Эндпоинт:
- `POST /admin/login` (через фронтовый прокси `POST /api/admin/login`)
- Требует заголовок `Authorization: Bearer <user_token>`
- Тело: `{ "admin_password": "1573" }`

## docker-compose

В [infra/docker-compose.yml](infra/docker-compose.yml) уже прописаны дефолты для stage:
- `STAGE_STATIC_OTP_CODE=906090`
- `ADMIN_PHONE_ALLOWLIST=+79062592834`
- `ADMIN_PASSWORD_SALT=stage-salt`
- `ADMIN_PASSWORD_HASH=6b8b0756...fe13` (pbkdf2_sha256, 100_000 итераций)

При необходимости переопределяйте их через переменные окружения.
