# Stage 6.2: Observability++

## What changed
- HTTP middleware now logs `request_received` and `request_finished` with request_id, method, path, content_length, status_code, and duration_ms.
- Database functions emit `db_query_start`, `db_query_ok`, and `db_query_error` with query_name, duration_ms, rowcount, request_id, and session_id.
- Chat flow logs now include `chat_state_before`/`chat_state_after` plus KB meta counters (filled_fields_count, missing_fields_count).
- LLM calls log provider/model, prompt/response sizes, duration, and `llm_invalid_output` when JSON is malformed.

## Why
- Faster pinpointing of slow or failing components in CI and production without changing business logic.
- Clear correlation across HTTP → DB → LLM using request_id/session_id.

## Notes
- No new dependencies; all logging stays as one-line JSON to stdout.
- Business logic untouched; only observability enriched.
