#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Stage 6 observability integration test
# Requires running docker compose or already running services.

BASE_URL=${BASE_URL:-http://localhost:8000}
ML_URL=${ML_URL:-http://localhost:8001}
HEADERS_FILE_1="/tmp/stage6_headers_1.txt"
HEADERS_FILE_2="/tmp/stage6_headers_2.txt"

step() {
  echo "[stage6] $1"
}

step "Starting services (docker compose)"
if command -v docker >/dev/null 2>&1; then
  docker compose -f infra/docker-compose.yml up -d --build
  sleep 3
else
  echo "docker not found, assuming services already running"
fi

step "Wait for API readiness"
READY=0
for i in $(seq 1 60); do
  if curl -fsS "$BASE_URL/health" >/dev/null 2>&1; then
    READY=1
    break
  fi
  echo "waiting for API... ($i/60)"
  sleep 1
done
if [ "$READY" -ne 1 ]; then
  echo "API did not become ready in time"
  if command -v docker >/dev/null 2>&1; then
    docker compose -f infra/docker-compose.yml logs --no-color --tail=200 api || true
  fi
  exit 1
fi

step "Create session"
SESSION_RAW=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/json" \
  -d '{"profession_query":"stage6 observability"}' \
  "$BASE_URL/sessions")
SESSION_JSON=$(echo "$SESSION_RAW" | head -n1)
SESSION_CODE=$(echo "$SESSION_RAW" | tail -n1)
echo "Session create response code: $SESSION_CODE"
echo "Session create body: $SESSION_JSON"
SESSION_ID=$(echo "$SESSION_JSON" | python3 - <<'PY'
import json,sys
try:
    data=json.load(sys.stdin)
    print(data.get("session_id",""))
except Exception:
    print("")
PY
)
if [ -z "$SESSION_ID" ]; then
  echo "Session creation failed"
  if command -v docker >/dev/null 2>&1; then
    docker compose -f infra/docker-compose.yml logs --no-color --tail=200 api || true
  fi
  exit 1
fi
step "Session created: $SESSION_ID"

step "Send start chat message and capture X-Request-Id"
curl -s -D "$HEADERS_FILE_1" -o /tmp/stage6_chat1.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"start\"}" \
  "$BASE_URL/chat/message" >/dev/null
if ! grep -qi "X-Request-Id" "$HEADERS_FILE_1"; then
  echo "X-Request-Id header missing in chat start response"
  exit 1
fi

step "Send clarification message and capture X-Request-Id"
curl -s -D "$HEADERS_FILE_2" -o /tmp/stage6_chat2.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"clarifications\",\"text\":\"офис москва бюджет 200к полный день\"}" \
  "$BASE_URL/chat/message" >/dev/null
if ! grep -qi "X-Request-Id" "$HEADERS_FILE_2"; then
  echo "X-Request-Id header missing in chat clarification response"
  exit 1
fi

step "Debug session endpoint"
SESSION_DEBUG=$(curl -s "$BASE_URL/debug/session?session_id=$SESSION_ID")
echo "$SESSION_DEBUG" | grep -q "session_id" || { echo "session debug missing session_id"; exit 1; }
echo "$SESSION_DEBUG" | grep -q "profession_query" || { echo "session debug missing profession_query"; exit 1; }

declare -i LIMIT=10
step "Debug messages endpoint"
MESSAGES_DEBUG=$(curl -s "$BASE_URL/debug/messages?session_id=$SESSION_ID&limit=$LIMIT")
echo "$MESSAGES_DEBUG" | grep -q "messages" || { echo "messages debug missing messages key"; exit 1; }

declare -i LIMIT_REPORT=1
step "Debug free report endpoint"
REPORT_DEBUG=$(curl -s "$BASE_URL/debug/report/free?session_id=$SESSION_ID")
echo "$REPORT_DEBUG" | grep -q "cached" || { echo "report debug missing cached key"; exit 1; }

step "Stage 6 observability test PASSED"
