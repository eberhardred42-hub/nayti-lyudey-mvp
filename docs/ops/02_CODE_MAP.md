# Code map (quick)

## Карта входов
- API: api/main.py (роуты, бизнес-флоу), api/db.py (DB helpers), infra/docker-compose.yml (env/stack).
- LLM: api/llm_client.py (provider switch, ping, generate_json_*).
- Auth: guest cookie/Bearer resolve в api/main.py (поиск по resolve_user_or_guest).
- Docs pipeline: api/main.py (documents/*), api/worker.py (фоновые задачи), render/ (рендер сервиса).
- Storage: storage/s3_client.py (MinIO/S3), переменные S3_*.
- Payments: api/db.py (wallet/ledger/orders helpers), api/main.py (checkout/webhook endpoints).
- Admin logs/trace: api/trace.py + /admin/logs в api/main.py.

## Как найти (rg)
- Роут: `rg "@app\\.(get|post)\(\"/" api/main.py`
- Бриф: `rg "brief" api/main.py`
- LLM ping: `rg "health/llm/ping|llm_ping" -n api`
- Auth: `rg "resolve_user_or_guest|__Host-nly_auth|Authorization: Bearer" -n api/main.py`
- Docs: `rg "documents/generate|generate_pack|render" -n api/main.py api/worker.py`
- Payments: `rg "wallet|ledger|checkout|yookassa" -n api`
- Trace: `rg "log_event\(|trace" -n api`
