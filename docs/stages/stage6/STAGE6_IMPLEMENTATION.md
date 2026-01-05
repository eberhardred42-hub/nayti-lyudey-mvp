# Stage 6: Observability Implementation

## Goals
- Propagate per-request IDs end-to-end (ingest or generate UUID v4) and return them in `X-Request-Id` response header.
- Emit structured JSON logs to stdout without new dependencies.
- Add read-only debug endpoints backed by Postgres.
- Keep business logic (chat/KB/report) unchanged.

## Architecture
- Middleware: attaches `request.state.request_id` (reuse inbound header if provided) and sets `X-Request-Id` on every response.
- Logging: `log_event(event, level="info", **fields)` builds a minimal JSON payload and prints to stdout.
- Timing: `compute_duration_ms(start)` helper for endpoint-level events.
- ISO conversion: `to_iso()` helper for datetime serialization in debug responses.

## Key code changes
- `api/main.py`
  - Added `log_event`, `request_id_middleware`, `to_iso`, `compute_duration_ms` helpers.
  - Instrumented endpoints with structured events:
    - `session_created`, `chat_message_received`, `chat_reply_sent`, `vacancy_kb_updated`, `free_report_cache_hit`, `free_report_generated`, `db_error`.
  - Replaced print warnings with `db_error` structured logs.
  - Added debug endpoints:
    - `GET /debug/session?session_id=...`
    - `GET /debug/messages?session_id=...&limit=50`
    - `GET /debug/report/free?session_id=...`
  - Preserved all chat/KB/report logic and responses.
- `api/db.py`
  - `get_session_messages` now accepts optional `limit` (default unlimited) to support debug pagination.

## Logging fields
Every log contains:
- `event`, `level`, `ts`
- `request_id`
- `session_id` (when available)
- `route`, `method`
- `duration_ms` for endpoint events
- Additional context per event (e.g., `message_type`, `cached`).

## Debug endpoints
- `/debug/session`: `{ session_id, profession_query, chat_state, kb_meta, has_free_report, updated_at }`
- `/debug/messages`: `{ session_id, messages: [{ role, text, created_at }...] }` with optional `limit` (default 50)
- `/debug/report/free`: `{ session_id, cached, headline, generated_at_iso }`
- All endpoints 404 when the session is absent in Postgres.

## Testing
Integration test `tests/test-stage6.sh`:
1. `docker compose -f infra/docker-compose.yml up -d --build`
2. POST `/sessions` to create a session.
3. POST `/chat/message` twice (start + clarifications), assert `X-Request-Id` header is present.
4. Call `/debug/session` and `/debug/messages` and grep for expected keys.
5. Call `/debug/report/free` and grep for `cached` key.

## Constraints honored
- No new dependencies added.
- Frontend and infra untouched.
- Chat/KB/report business logic unchanged.
- Observability changes are additive and read-only.
