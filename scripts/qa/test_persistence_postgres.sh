#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
SESSION_ID=""

echo "========================================================================"
echo "Postgres persistence (integration)"
echo "========================================================================"
echo ""

step() {
  echo "[persistence] $1"
}

step "Start docker compose (if available)"
if command -v docker >/dev/null 2>&1; then
  docker compose -f infra/docker-compose.yml up -d --build
  sleep 10
else
  echo "docker not found, assuming services already running"
fi

step "Wait for DB health"
for i in {1..10}; do
  if curl -sS "$BACKEND_URL/health/db" | grep -q '"ok":true'; then
    echo "[ok] db healthy"
    break
  fi
  echo "waiting for db... ($i/10)"
  sleep 2
done

step "Create session"
resp="$(curl -sS -X POST "$BACKEND_URL/sessions" -H "Content-Type: application/json" -d '{"profession_query":"Senior Python Developer"}')"
SESSION_ID="$(echo "$resp" | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("session_id") or "").strip())' 2>/dev/null || true)"
if [[ -z "$SESSION_ID" ]]; then
  echo "[error] Failed to create session"
  echo "$resp"
  exit 1
fi

echo "session_id=$SESSION_ID"

step "Chat start"
resp="$(curl -sS -X POST "$BACKEND_URL/chat/message" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"start\"}")"
if ! echo "$resp" | grep -q '"reply"'; then
  echo "[error] Unexpected response"
  echo "$resp"
  exit 1
fi

step "Move to vacancy text flow"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":\"Есть текст вакансии\"}" >/dev/null

step "Submit vacancy content"
vacancy_text='Ищем Senior Python Developer.

Требования:
- Python 3.9+
- FastAPI or Django
- PostgreSQL
- 5+ лет опыта

Условия:
- Москва, гибрид
- 300-400к рублей
- Полный день'

vacancy_json="$(printf '%s' "$vacancy_text" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')"

curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":$vacancy_json}" >/dev/null

step "Submit clarifications"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\",\"type\":\"message\",\"text\":\"Москва, гибрид, 300-400к, полный день\"}" >/dev/null

step "Fetch vacancy KB"
kb_json="$(curl -sS "$BACKEND_URL/vacancy?session_id=$SESSION_ID")"
if ! echo "$kb_json" | grep -q '"vacancy_kb"'; then
  echo "[error] Missing vacancy_kb"
  echo "$kb_json" | head -c 800
  echo ""
  exit 1
fi

step "Fetch free report"
report_json="$(curl -sS "$BACKEND_URL/report/free?session_id=$SESSION_ID")"
if ! echo "$report_json" | grep -q '"free_report"'; then
  echo "[error] Missing free_report"
  echo "$report_json" | head -c 800
  echo ""
  exit 1
fi

step "Restart api container (if available)"
if command -v docker >/dev/null 2>&1; then
  docker compose -f infra/docker-compose.yml restart api
  sleep 5
else
  echo "docker not found, skipping restart"
fi

step "Verify vacancy KB persisted"
kb_json2="$(curl -sS "$BACKEND_URL/vacancy?session_id=$SESSION_ID")"
if ! echo "$kb_json2" | grep -q '"tasks"'; then
  echo "[error] Vacancy KB lost after restart"
  exit 1
fi

step "Verify free report persisted"
report_json2="$(curl -sS "$BACKEND_URL/report/free?session_id=$SESSION_ID")"
if ! echo "$report_json2" | grep -q '"free_report"'; then
  echo "[error] Free report lost after restart"
  exit 1
fi

echo "OK"
