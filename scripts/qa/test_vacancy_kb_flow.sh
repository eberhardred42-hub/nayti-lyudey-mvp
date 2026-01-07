#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
FRONT_URL="${FRONT_URL:-http://localhost:3000}"

echo "=== Vacancy KB flow (integration) ==="
echo "Backend: $BACKEND_URL"
echo ""

step() {
  echo "[vacancy_kb_flow] $1"
}

step "Create session"
response="$(curl -sS -X POST "$BACKEND_URL/sessions" -H "Content-Type: application/json" -d '{"profession_query":"Senior Engineer"}')"
session_id="$(echo "$response" | python3 -c 'import json,sys; d=json.load(sys.stdin); print((d.get("session_id") or "").strip())' 2>/dev/null || true)"

if [[ -z "$session_id" ]]; then
  echo "[error] Failed to create session"
  echo "$response"
  exit 1
fi

echo "session_id=$session_id"

step "Read initial vacancy KB"
curl -sS "$BACKEND_URL/vacancy?session_id=$session_id" | python3 -m json.tool | head -40

step "Start chat"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"start\"}" \
  | python3 -m json.tool >/dev/null

step "Select 'Есть текст вакансии'"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"message\",\"text\":\"Есть текст вакансии\"}" \
  | python3 -m json.tool >/dev/null

step "Send vacancy text"
vacancy_text='Ищем Senior Software Engineer с опытом 5+ лет в Python и Go.

Обязанности:
- Разработка микросервисов
- Code review и менторство
- Архитектурные решения

Требования:
- Python 3.10+
- Go 1.20+
- Опыт с Kubernetes

Локация: Москва или удалённо
Зарплата: 200-300 тыс руб
Занятость: Полная'

vacancy_json="$(printf '%s' "$vacancy_text" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')"

curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"message\",\"text\":$vacancy_json}" \
  | python3 -m json.tool >/dev/null

step "Send clarifications"
curl -sS -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$session_id\",\"type\":\"message\",\"text\":\"Москва, гибридно, 200-300к, фулл тайм\"}" \
  | python3 -m json.tool >/dev/null

step "Read final vacancy KB"
curl -sS "$BACKEND_URL/vacancy?session_id=$session_id" | python3 -m json.tool

step "Optional: front proxy check"
if curl -fsS "$FRONT_URL/api/vacancy?session_id=$session_id" >/dev/null 2>&1; then
  curl -sS "$FRONT_URL/api/vacancy?session_id=$session_id" | python3 -m json.tool >/dev/null
  echo "[ok] front proxy responded"
else
  echo "[skip] front proxy not available: $FRONT_URL"
fi

echo "OK"
