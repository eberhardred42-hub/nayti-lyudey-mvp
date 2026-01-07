#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE="docker compose -f infra/docker-compose.yml"
BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
ML_URL="${ML_URL:-http://localhost:8001}"
TMPDIR="${RUNNER_TEMP:-/tmp}"
HEADERS_FILE_1="$TMPDIR/obs_headers_1.txt"
HEADERS_FILE_2="$TMPDIR/obs_headers_2.txt"

step() {
  echo "[observability] $1"
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

step "Start services (docker compose if available)"
if command -v docker >/dev/null 2>&1; then
  $COMPOSE up -d --build
else
  echo "docker not found, assuming services already running"
fi

wait_url "$BACKEND_URL/health" "api"
wait_url "$ML_URL/health" "ml"

step "Create session and assert X-Request-Id"
HDR="$(mktemp -p "$TMPDIR" obs-hdr.XXXXXX)"
BODY="$(mktemp -p "$TMPDIR" obs-body.XXXXXX)"
chmod 644 "$HDR" "$BODY" || true

CODE="$(curl -sS -D "$HDR" -o "$BODY" -w '%{http_code}' \
  -X POST "$BACKEND_URL/sessions" \
  -H "Content-Type: application/json" \
  -d '{"profession_query":"Маркетолог"}')"

SESSION_ID="$(python3 - "$BODY" <<'PY'
import json,sys
try:
    data=json.load(open(sys.argv[1], 'r', encoding='utf-8'))
    print(data.get('session_id','') or '')
except Exception:
    print('')
PY
)"

if [[ "$CODE" != "200" || -z "$SESSION_ID" ]]; then
  echo "[error] Session creation failed HTTP_CODE=$CODE"
  echo "--- headers ---"; cat "$HDR" || true
  echo "--- body ---"; cat "$BODY" || true
  exit 1
fi

if ! grep -qi '^x-request-id:' "$HDR"; then
  echo "[error] Missing X-Request-Id header on /sessions"
  cat "$HDR" || true
  exit 1
fi

echo "session_id=$SESSION_ID"

step "Chat start should include X-Request-Id"
curl -sS -D "$HEADERS_FILE_1" -o /tmp/obs_chat1.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"start\"}" \
  "$BACKEND_URL/chat/message" >/dev/null

if ! grep -qi 'x-request-id:' "$HEADERS_FILE_1"; then
  echo "[error] X-Request-Id header missing in chat start response"
  exit 1
fi

step "Clarifications message should include X-Request-Id"
curl -sS -D "$HEADERS_FILE_2" -o /tmp/obs_chat2.json -X POST \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"clarifications\",\"text\":\"офис москва бюджет 200к полный день\"}" \
  "$BACKEND_URL/chat/message" >/dev/null

if ! grep -qi 'x-request-id:' "$HEADERS_FILE_2"; then
  echo "[error] X-Request-Id header missing in chat clarification response"
  exit 1
fi

step "Debug endpoints"
SESSION_DEBUG="$(curl -sS "$BACKEND_URL/debug/session?session_id=$SESSION_ID")"
echo "$SESSION_DEBUG" | grep -q 'session_id' || { echo "session debug missing session_id"; exit 1; }

declare -i LIMIT=10
MESSAGES_DEBUG="$(curl -sS "$BACKEND_URL/debug/messages?session_id=$SESSION_ID&limit=$LIMIT")"
echo "$MESSAGES_DEBUG" | grep -q 'messages' || { echo "messages debug missing messages key"; exit 1; }

REPORT_DEBUG="$(curl -sS "$BACKEND_URL/debug/report/free?session_id=$SESSION_ID")"
echo "$REPORT_DEBUG" | grep -q 'cached' || { echo "report debug missing cached key"; exit 1; }

echo "OK"
