#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Stage 7: LLM-driven clarifications (mock/openai_compat) integration test

BASE_URL=${BASE_URL:-http://localhost:8000}
HEADERS_FILE="/tmp/stage7_headers.txt"

wait_url() {
  local url="$1"
  local name="$2"
  local deadline=$((SECONDS+60))
  while [ $SECONDS -lt $deadline ]; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)
    if [ "$code" = "200" ]; then
      return 0
    fi
    sleep 1
  done
  echo "$name not ready: $url"
  exit 1
}

step() {
  echo "[stage7] $1"
}

step "Starting services (docker compose if available)"
if command -v docker >/dev/null 2>&1; then
  docker compose -f infra/docker-compose.yml up -d --build
  sleep 3
else
  echo "docker not found, assuming services already running"
fi

step "Wait for API health"
wait_url "$BASE_URL/health" "api"

step "Create session"
SESSION_JSON=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"profession_query":"stage7 llm"}' \
  "$BASE_URL/sessions")
SESSION_ID=$(echo "$SESSION_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("session_id",""))' 2>/dev/null || true)
if [ -z "$SESSION_ID" ]; then
  echo "Session creation failed"
  exit 1
fi
step "Session: $SESSION_ID"

step "Send start message"
curl -s -D "$HEADERS_FILE" -o /tmp/stage7_chat1.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"start\"}" \
  "$BASE_URL/chat/message" >/dev/null

step "Move to vacancy text branch"
VAC_PROMPT="Есть текст вакансии"
curl -s -o /tmp/stage7_chat2.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":\"$VAC_PROMPT\"}" \
  "$BASE_URL/chat/message" >/dev/null

step "Send long vacancy text to reach clarifications"
VACANCY_TEXT="Ищем разработчика. Нужны Python, PostgreSQL, умение работать с API, опыт 5 лет. Москва или другой город, возможен гибрид. Вакансия включает задачи по бэкенду, интеграции, поддержке. Важны коммуникации, ответственность, соблюдение сроков. Предлагаем проектную работу с возможностью полного дня. Бюджет обсуждается, готовы рассмотреть разные варианты."
CLAR_RESPONSE=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":\"$VACANCY_TEXT\"}" \
  "$BASE_URL/chat/message")

step "Validate clarifications contain questions and quick replies"
echo "$CLAR_RESPONSE" | python3 -c 'import json,sys; payload=json.load(sys.stdin); \
qs=payload.get("clarifying_questions") or []; \
qr=payload.get("quick_replies") or []; \
\
(_ for _ in ()).throw(SystemExit("clarifying_questions missing")) if not qs else None; \
(_ for _ in ()).throw(SystemExit("quick_replies missing")) if not qr else None; \
keywords=["город","формат","бюджет","занятость"]; \
\
(_ for _ in ()).throw(SystemExit("questions missing expected topics")) if not any(any(k in q.lower() for k in keywords) for q in qs) else None; \
print("clarifications OK")'

step "Stage 7 test PASSED"
