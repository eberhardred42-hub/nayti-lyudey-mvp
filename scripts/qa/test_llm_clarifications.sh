#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

BASE_URL="${BASE_URL:-http://localhost:8000}"

step() {
  echo "[llm_clarifications] $1"
}

step "Start services (docker compose if available)"
if command -v docker >/dev/null 2>&1; then
  docker compose -f infra/docker-compose.yml up -d --build
  sleep 3
else
  echo "docker not found, assuming services already running"
fi

step "Create session"
SESSION_JSON="$(curl -sS -X POST -H "Content-Type: application/json" -d '{"profession_query":"stage7 llm"}' "$BASE_URL/sessions")"
SESSION_ID="$(echo "$SESSION_JSON" | python3 - <<'PY'
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('session_id','') or '')
except Exception:
    print('')
PY
)"

if [[ -z "$SESSION_ID" ]]; then
  echo "[error] Session creation failed"
  echo "$SESSION_JSON"
  exit 1
fi

echo "session_id=$SESSION_ID"

step "Send start message"
curl -sS -X POST -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"start\"}" \
  "$BASE_URL/chat/message" >/dev/null

step "Move to vacancy text branch"
curl -sS -X POST -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":\"Есть текст вакансии\"}" \
  "$BASE_URL/chat/message" >/dev/null

step "Send long vacancy text to reach clarifications"
vacancy_text='Ищем разработчика. Нужны Python, PostgreSQL, умение работать с API, опыт 5 лет. Москва или другой город, возможен гибрид. Вакансия включает задачи по бэкенду, интеграции, поддержке. Важны коммуникации, ответственность, соблюдение сроков. Предлагаем проектную работу с возможностью полного дня. Бюджет обсуждается, готовы рассмотреть разные варианты.'
vacancy_json="$(printf '%s' "$vacancy_text" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')"

CLAR_RESPONSE="$(curl -sS -X POST -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":$vacancy_json}" \
  "$BASE_URL/chat/message")"

step "Validate clarifications contain questions and quick replies"
echo "$CLAR_RESPONSE" | python3 - <<'PY'
import json,sys
payload=json.load(sys.stdin)
qs=payload.get('clarifying_questions') or []
qr=payload.get('quick_replies') or []
if not qs:
    sys.exit('clarifying_questions missing')
if not qr:
    sys.exit('quick_replies missing')
keywords=['город','формат','бюджет','занятость']
if not any(any(k in (q or '').lower() for k in keywords) for q in qs):
    sys.exit('questions missing expected topics')
print('clarifications OK')
PY

echo "OK"
