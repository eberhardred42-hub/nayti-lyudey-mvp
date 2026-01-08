# Proto UI (static)

Файлы в `front/public/proto/` раздаются Next как **статик из public**.

## Как открыть
- `/proto/index.html`
- `/proto/chat.html`
- `/proto/docs.html`
- `/proto/account.html`
- `/proto/admin.html`

## Зачем это
Быстро двигать UI без React/Next компонентов и без влияния роутинга.

## Важно
- Это **прототип**, не прод-страницы Next.
- Логин дергает API: `POST /api/sessions` и хранит токен/роль в localStorage.
- Если API не готов — UI не падает, показывает toast.
