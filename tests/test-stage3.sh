#!/bin/bash
# Test script for Stage 3 Vacancy KB

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

BASE_URL="http://localhost:8000"
FRONT_URL="http://localhost:3000"

echo -e "${YELLOW}=== Stage 3 Vacancy KB Test ===${NC}"

# Test 1: Create session
echo -e "\n${YELLOW}1. Creating session...${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/sessions" \
  -H "Content-Type: application/json" \
  -d '{"profession_query": "Senior Engineer"}')
echo "$RESPONSE"
SESSION_ID=$(echo "$RESPONSE" | grep -o '"session_id":"[^"]*' | cut -d'"' -f4)
echo "Session ID: $SESSION_ID"

if [ -z "$SESSION_ID" ]; then
  echo -e "${RED}Failed to create session${NC}"
  exit 1
fi

# Test 2: Check initial vacancy KB
echo -e "\n${YELLOW}2. Checking initial vacancy KB...${NC}"
curl -s "$BASE_URL/vacancy?session_id=$SESSION_ID" | python3 -m json.tool | head -30

# Test 3: Start chat
echo -e "\n${YELLOW}3. Starting chat...${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"start\", \"text\": null}")
echo "$RESPONSE" | python3 -m json.tool

# Test 4: Choose vacancy text
echo -e "\n${YELLOW}4. Choosing 'Есть текст вакансии'...${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"reply\", \"text\": \"Есть текст вакансии\"}")
echo "$RESPONSE" | python3 -m json.tool

# Test 5: Send vacancy text
echo -e "\n${YELLOW}5. Sending vacancy text...${NC}"
VACANCY_TEXT="Ищем Senior Software Engineer с опытом 5+ лет в Python и Go.

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
Занятость: Полная"

RESPONSE=$(curl -s -X POST "$BASE_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"reply\", \"text\": $(printf '%s\n' "$VACANCY_TEXT" | python3 -c 'import sys, json; print(json.dumps(sys.stdin.read()))')}")
echo "$RESPONSE" | python3 -m json.tool

# Test 6: Send clarifications
echo -e "\n${YELLOW}6. Sending clarifications...${NC}"
RESPONSE=$(curl -s -X POST "$BASE_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"reply\", \"text\": \"Москва, гибридно, 200-300к, фулл тайм\"}")
echo "$RESPONSE" | python3 -m json.tool

# Test 7: Check final vacancy KB
echo -e "\n${YELLOW}7. Checking final vacancy KB...${NC}"
curl -s "$BASE_URL/vacancy?session_id=$SESSION_ID" | python3 -m json.tool

# Test 8: Test front proxy
echo -e "\n${YELLOW}8. Testing front proxy...${NC}"
curl -s "$FRONT_URL/api/vacancy?session_id=$SESSION_ID" | python3 -m json.tool 2>/dev/null || echo "(Front proxy test skipped if front not running)"

echo -e "\n${GREEN}=== Tests completed ===${NC}"
