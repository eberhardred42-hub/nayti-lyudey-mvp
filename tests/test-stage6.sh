#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE="docker compose -f infra/docker-compose.yml"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONT_URL="${FRONT_URL:-http://localhost:3000}"
ML_URL="${ML_URL:-http://localhost:8001}"
TMPDIR="${RUNNER_TEMP:-/tmp}"
HEADERS_FILE_1="$TMPDIR/stage6_headers_1.txt"
HEADERS_FILE_2="$TMPDIR/stage6_headers_2.txt"

# Stage 6 observability integration test
# Requires running docker compose or already running services.

step() {
  echo "[stage6] $1"
}

wait_url() {
  local url="$1"
  local name="$2"
  for i in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[ok] $name ready: $url"
      return 0
    fi
    sleep 1
  done
  echo "[error] $name not ready: $url"
  return 1
}

step "Starting services (docker compose)"
if command -v docker >/dev/null 2>&1; then
  $COMPOSE up -d --build
else
  echo "docker not found, assuming services already running"
fi

wait_url "$BACKEND_URL/health" "api"
wait_url "$ML_URL/health" "ml"

echo "[stage6] Create session"

TMPDIR="${RUNNER_TEMP:-/tmp}"
HDR="$(mktemp -p "$TMPDIR" stage6-hdr.XXXXXX)"
BODY="$(mktemp -p "$TMPDIR" stage6-body.XXXXXX)"
chmod 644 "$HDR" "$BODY" || true
CODE="$(curl -sS -D "$HDR" -o "$BODY" -w '%{http_code}' \
  -X POST "$BACKEND_URL/sessions" \
  -H "Content-Type: application/json" \
  -d '{"profession_query":"Маркетолог"}')"

SESSION_ID="$(python3 - "$BODY" <<'PY'
import json,sys
try:
    data=json.load(open(sys.argv[1], 'r', encoding='utf-8'))
    print(data.get("session_id", "") or "")
except Exception:
    print("")
PY
)"

echo "[stage6] /sessions HTTP_CODE=$CODE"
echo "--- headers ---"
cat "$HDR" || true
echo "--- body ---"
cat "$BODY" || true

if [[ "$CODE" != "200" || -z "$SESSION_ID" ]]; then
  echo "[stage6][error] Session creation failed"
  exit 1
fi

if ! grep -qi '^x-request-id:' "$HDR"; then
  echo "[stage6][error] Missing X-Request-Id header on /sessions"
  echo "--- headers ---"
  cat "$HDR" || true
  exit 1
fi

echo "[ok] session_id=$SESSION_ID"

step "Send start chat message and capture X-Request-Id"
curl -s -D "$HEADERS_FILE_1" -o /tmp/stage6_chat1.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"start\"}" \
  "$BACKEND_URL/chat/message" >/dev/null
if ! grep -qi "X-Request-Id" "$HEADERS_FILE_1"; then
  echo "X-Request-Id header missing in chat start response"
  exit 1
fi

step "Send clarification message and capture X-Request-Id"
curl -s -D "$HEADERS_FILE_2" -o /tmp/stage6_chat2.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"clarifications\",\"text\":\"офис москва бюджет 200к полный день\"}" \
  "$BACKEND_URL/chat/message" >/dev/null
if ! grep -qi "X-Request-Id" "$HEADERS_FILE_2"; then
  echo "X-Request-Id header missing in chat clarification response"
  exit 1
fi

step "Debug session endpoint"
SESSION_DEBUG=$(curl -s "$BACKEND_URL/debug/session?session_id=$SESSION_ID")
echo "$SESSION_DEBUG" | grep -q "session_id" || { echo "session debug missing session_id"; exit 1; }
echo "$SESSION_DEBUG" | grep -q "profession_query" || { echo "session debug missing profession_query"; exit 1; }

declare -i LIMIT=10
step "Debug messages endpoint"
MESSAGES_DEBUG=$(curl -s "$BACKEND_URL/debug/messages?session_id=$SESSION_ID&limit=$LIMIT")
echo "$MESSAGES_DEBUG" | grep -q "messages" || { echo "messages debug missing messages key"; exit 1; }

declare -i LIMIT_REPORT=1
step "Debug free report endpoint"
REPORT_DEBUG=$(curl -s "$BACKEND_URL/debug/report/free?session_id=$SESSION_ID")
echo "$REPORT_DEBUG" | grep -q "cached" || { echo "report debug missing cached key"; exit 1; }

step "Stage 6 observability test PASSED"
