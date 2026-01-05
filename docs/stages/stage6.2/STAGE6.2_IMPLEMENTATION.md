# Stage 6.2: Observability++ Implementation

## Middleware
- `request_id_middleware` now logs `request_received` on entry (method, path, content_length, request_id) and `request_finished` on exit (status_code, duration_ms) while still setting `X-Request-Id`.

## Database logging
- Added `_log_event` and timing in `api/db.py` without new deps.
- Each DB function (`create_session`, `get_session`, `update_session`, `add_message`, `get_session_messages`, `delete_session`, `health_check`) logs `db_query_start` → `db_query_ok`/`db_query_error` with query_name, duration_ms, rowcount, request_id, session_id.
- Functions now accept optional `request_id` and use `psycopg2.extras.Json(...)` to avoid NULL JSON writes.

## Chat logging
- `/chat/message` logs `chat_state_before` and `chat_state_after` plus KB meta counters (`filled_fields_count`, `missing_fields_count`) on receive/reply.
- KB counters sourced from `kb_meta_counts()` helper (no full KB dumping).

## LLM logging
- `llm_request`/`llm_response` now include provider, model, prompt_chars, llm_response_chars, llm_duration_ms.
- `llm_invalid_output` is emitted when OpenAI-compatible responses are not valid JSON/dict.

## Docs and index
- Added Stage 6.2 summary/implementation docs under `docs/stages/stage6.2/` and linked them in `docs/DOCUMENTATION_INDEX.md`.

## Scope
- No business logic changes; observability only.
- Logs remain single-line JSON printed to stdout.
