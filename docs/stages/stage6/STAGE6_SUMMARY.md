# Stage 6: Observability

## What changed
- Request ID middleware for all HTTP requests (X-Request-Id propagation and response header).
- Structured JSON logs via `log_event(event, level="info", **fields)` printed to stdout.
- Read-only debug endpoints backed by Postgres data:
  - `GET /debug/session?session_id=...`
  - `GET /debug/messages?session_id=...&limit=50`
  - `GET /debug/report/free?session_id=...`
- Integration test `tests/test-stage6.sh` to verify headers and debug endpoints.

## Logging events
- `session_created`
- `chat_message_received`
- `chat_reply_sent`
- `vacancy_kb_updated`
- `free_report_cache_hit` / `free_report_generated`
- `db_error`

Each log includes: `event`, `level`, `ts`, `request_id`, `session_id` (if available), `route`, `method`, and `duration_ms` for endpoint events.

## Debug endpoints
- `/debug/session`: session metadata (profession_query, chat_state, kb_meta, has_free_report, updated_at).
- `/debug/messages`: ordered messages (role, text, created_at) with optional `limit` (default 50).
- `/debug/report/free`: cache presence, headline, generated_at_iso.

## Testing
Run in a Docker-capable environment:
```bash
docker compose -f infra/docker-compose.yml up -d --build
bash tests/test-stage6.sh
```

## Constraints met
- No new dependencies added.
- Frontend and infra unchanged.
- Chat/KB/report business logic unchanged.
- Observability is additive and read-only.
