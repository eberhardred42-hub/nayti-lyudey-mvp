#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# Stage 7: LLM-driven clarifications (mock/openai_compat) integration test

COMPOSE="docker compose -f infra/docker-compose.yml"
BASE_URL=${BASE_URL:-http://localhost:8000}
ML_URL=${ML_URL:-http://localhost:8001}
TMPDIR="${RUNNER_TEMP:-/tmp}"
HEADERS_FILE="$TMPDIR/stage7_headers.txt"

step() {
  echo "[stage7] $1"
}

wait_url() {
  local url="$1"
  local name="$2"
  for i in $(seq 1 90); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[ok] $name ready: $url"
      return 0
    fi
    sleep 1
  done
  echo "[error] $name not ready: $url"
  return 1
}

step "Starting services (docker compose if available)"
if command -v docker >/dev/null 2>&1; then
  if [[ "${CI:-}" == "true" ]]; then
    echo "[stage7] CI=true: assuming services already started by workflow"
  else
    $COMPOSE up -d --build
  fi
else
  echo "docker not found, assuming services already running"
fi

wait_url "$BASE_URL/health" "api"
wait_url "$BASE_URL/health/db" "db"
wait_url "$ML_URL/health" "ml"
wait_url "$BASE_URL/health/llm" "llm"

step "Create session"
STATIC_ADMIN_PHONE=${STATIC_ADMIN_PHONE:-89062592834}
STATIC_ADMIN_CODE=${STATIC_ADMIN_CODE:-1573}
HDR="$(mktemp -p "$TMPDIR" stage7-hdr.XXXXXX)"
BODY="$(mktemp -p "$TMPDIR" stage7-body.XXXXXX)"
chmod 644 "$HDR" "$BODY" || true
CODE="$(curl -sS -D "$HDR" -o "$BODY" -w '%{http_code}' \
  -X POST "$BASE_URL/sessions" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$STATIC_ADMIN_PHONE\",\"code\":\"$STATIC_ADMIN_CODE\"}")"

SESSION_ID=$(python3 - "$BODY" <<'PY'
import json,sys
try:
    data=json.load(open(sys.argv[1], 'r', encoding='utf-8'))
    print(data.get("session_id",""))
except Exception:
    print("")
PY
)

TOKEN=$(python3 - "$BODY" <<'PY'
import json,sys
try:
    data=json.load(open(sys.argv[1], 'r', encoding='utf-8'))
    print(data.get("token",""))
except Exception:
    print("")
PY
)

echo "[stage7] /sessions HTTP_CODE=$CODE"
if [[ "$CODE" != "200" || -z "$SESSION_ID" ]]; then
  echo "[stage7][error] Session creation failed"
  echo "--- headers ---"
  cat "$HDR" || true
  echo "--- body ---"
  cat "$BODY" || true
  exit 1
fi
step "Session: $SESSION_ID"
AUTH_HEADER=()
if [[ -n "$TOKEN" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer $TOKEN")
fi

step "Send start message"
curl -s -D "$HEADERS_FILE" -o /tmp/stage7_chat1.json -X POST \
  "${AUTH_HEADER[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"start\"}" \
  "$BASE_URL/chat/message" >/dev/null

step "Move to vacancy text branch"
VAC_PROMPT="Есть текст вакансии"
curl -s -o /tmp/stage7_chat2.json -X POST \
  "${AUTH_HEADER[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":\"$VAC_PROMPT\"}" \
  "$BASE_URL/chat/message" >/dev/null

step "Send long vacancy text to reach clarifications"
VACANCY_TEXT="Ищем разработчика. Нужны Python, PostgreSQL, умение работать с API, опыт 5 лет. Москва или другой город, возможен гибрид. Вакансия включает задачи по бэкенду, интеграции, поддержке. Важны коммуникации, ответственность, соблюдение сроков. Предлагаем проектную работу с возможностью полного дня. Бюджет обсуждается, готовы рассмотреть разные варианты."
CLAR_BODY="$(mktemp -p "$TMPDIR" stage7-clar-body.XXXXXX)"
CLAR_CODE=$(curl -sS -o "$CLAR_BODY" -w '%{http_code}' -X POST \
  "${AUTH_HEADER[@]}" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":\"$VACANCY_TEXT\"}" \
  "$BASE_URL/chat/message")

if [[ "$CLAR_CODE" != "200" ]]; then
  echo "[stage7][error] /chat/message HTTP_CODE=$CLAR_CODE"
  echo "--- body ---"
  cat "$CLAR_BODY" || true
  exit 1
fi

step "Validate clarifications contain questions and quick replies"
python3 - "$CLAR_BODY" <<'PY'
import json,sys
payload=json.load(open(sys.argv[1], 'r', encoding='utf-8'))
qs=payload.get("clarifying_questions") or []
qr=payload.get("quick_replies") or []
if not qs:
    sys.exit("clarifying_questions missing")
if not qr:
    sys.exit("quick_replies missing")
keywords=["город","формат","бюджет","занятость"]
if not any(any(k in q.lower() for k in keywords) for q in qs):
    sys.exit("questions missing expected topics")
print("clarifications OK")
PY

step "Stage 7 test PASSED"
