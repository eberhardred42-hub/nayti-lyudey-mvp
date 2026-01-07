#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

echo "================================"
echo "Free report flow (integration)"
echo "================================"
echo "Backend: $BACKEND_URL"
echo ""

step() {
  echo "[free_report_flow] $1"
}

step "Create session"
response="$(curl -sS -X POST "$BACKEND_URL/sessions" -H "Content-Type: application/json" -d '{"profession_query":"Senior Python Developer"}')"
session_id="$(echo "$response" | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("session_id") or "").strip())' 2>/dev/null || true)"

if [[ -z "$session_id" ]]; then
  echo "[error] Failed to create session"
  echo "$response"
  exit 1
fi

echo "session_id=$session_id"

step "Start chat"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"start\"}" >/dev/null

step "Select vacancy text branch"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"message\",\"text\":\"Есть текст вакансии\"}" >/dev/null

step "Send vacancy text"
vacancy_text='Ищем Senior Python Developer. Требования: 5+ лет опыта с Python, Django, PostgreSQL. Зарплата 250k-350k. Офис в Москве, гибрид возможен.'
vacancy_json="$(printf '%s' "$vacancy_text" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')"

curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"message\",\"text\":$vacancy_json}" >/dev/null

step "Send clarifications"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"message\",\"text\":\"Москва, гибрид, 250-350k, полный день\"}" >/dev/null

step "Fetch free report"
report_json="$(curl -sS -X GET "$BACKEND_URL/report/free?session_id=$session_id")"

echo "$report_json" | python3 -m json.tool >/dev/null

if ! echo "$report_json" | grep -q '"free_report"'; then
  echo "[error] Missing free_report in response"
  echo "$report_json" | head -c 800
  echo ""
  exit 1
fi

sections=(headline where_to_search what_to_screen budget_reality_check next_steps)
for s in "${sections[@]}"; do
  if echo "$report_json" | grep -q "\"$s\""; then
    echo "[ok] section: $s"
  else
    echo "[error] Missing section: $s"
    exit 1
  fi
done

echo "OK"
