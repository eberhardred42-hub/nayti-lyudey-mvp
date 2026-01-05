# Stage 7: LLM Clarifications Implementation

## Goals
- Ask clarifying questions dynamically based on missing vacancy KB fields and the last user message.
- Keep dependency footprint zero (stdlib HTTP client + FastAPI only).
- Provide health visibility for the LLM provider and deterministic fallback behaviour.

## Flow changes in the chat handler
- Fallback templates for clarifying questions/quick replies live in [api/main.py](api/main.py#L191-L214) to cover missing fields when the LLM cannot respond.
- `build_clarification_prompt()` assembles context (session id, profession query, missing fields, last user message) and calls the LLM client; it sanitizes outputs, limits to 3 questions/6 quick replies, and falls back to templates on errors [api/main.py#L217-L259].
- The chat handler invokes the builder after receiving a long vacancy text or a tasks description, returning `clarifying_questions` alongside `quick_replies` in the API response [api/main.py#L506-L566].
- Clarification messages (`awaiting_clarifications` state) now update vacancy KB heuristics for work format, employment type, salary, and location before moving to the free report [api/main.py#L607-L643, api/main.py#L264-L333].

## LLM client
- Provider selection is env-driven: `LLM_PROVIDER` (`mock` by default) with optional `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` for `openai_compat` [api/llm_client.py#L5-L18].
- `generate_questions_and_quick_replies()` builds a compact prompt with missing fields and last user message, logs `llm_request`/`llm_response`/`llm_error`, and enforces list-shaped JSON output [api/llm_client.py#L110-L170].
- `openai_compat` uses stdlib `urllib` to POST to `/chat/completions` with `response_format=json_object`; content JSON is parsed and validated [api/llm_client.py#L60-L107].
- The `mock` provider returns deterministic questions/quick replies from missing fields for local/dry runs [api/llm_client.py#L38-L58].
- `health_llm()` reports provider readiness; `mock` is always ok, `openai_compat` checks env presence [api/llm_client.py#L172-L181].

## Health endpoints
- `/health/llm` exposes provider status for probes [api/main.py#L703-L705].
- Existing `/health` and `/health/db` remain unchanged.

## Testing and CI
- Integration test `tests/test-stage7.sh` spins up services (if Docker exists), drives the conversation to the clarifications stage, and asserts both `clarifying_questions` and `quick_replies` include expected topics [tests/test-stage7.sh#L1-L76].
- CI workflow `.github/workflows/ci.yml` starts docker-compose, waits on `/health`, `/health/db`, `/health/llm`, and runs stage5/6/7 scripts sequentially.

## Notes
- No new dependencies were added; only stdlib HTTP calls are used for LLM requests.
- User-facing text keeps emojis removed; clarifying outputs are bounded to avoid noisy replies.
