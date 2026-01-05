# Stage 7: LLM Clarifications

## What changed
- Added LLM-driven clarifying questions and quick replies after receiving vacancy text or tasks, with safe template fallbacks when the LLM is unavailable or misbehaves.
- Introduced provider-agnostic LLM client supporting `mock` (default) and `openai_compat` providers with structured logging for `llm_request`, `llm_response`, and `llm_error` events.
- Chat responses now return `clarifying_questions` alongside `quick_replies` to guide users toward missing KB fields.
- New LLM health check endpoint `/health/llm` for readiness probes.
- New integration test `tests/test-stage7.sh` to validate clarifications flow; CI runs stage5/6/7 scripts.

## LLM configuration
- `LLM_PROVIDER`: `mock` (default) or `openai_compat`.
- `LLM_BASE_URL`, `LLM_API_KEY`: required when `LLM_PROVIDER=openai_compat`.
- `LLM_MODEL`: model name for the compatible endpoint (default `gpt-4o-mini`).

## Running tests
Run in a Docker-capable environment:
```bash
docker compose -f infra/docker-compose.yml up -d --build
bash tests/test-stage7.sh
```
CI will also execute stage5 and stage6 scripts via `.github/workflows/ci.yml`.

## Constraints met
- No new Python dependencies added.
- Frontend and infra unchanged (aside from CI workflow addition at root).
- Existing chat/report logic preserved; clarifications are additive with fallbacks.
