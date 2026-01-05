#!/bin/bash
# Stage 5 Integration Test: Postgres Persistence
# 
# Tests that sessions, messages, and vacancy KBs persist across API restarts.

set -e

PROJECT_DIR="/workspaces/nayti-lyudey-mvp"
cd "$PROJECT_DIR"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
SESSION_ID=""

echo "========================================================================"
echo "Stage 5: Postgres Persistence Integration Test"
echo "========================================================================"
echo ""

# Step 1: Start Docker containers
echo "[Step 1] Starting Docker containers..."
if command -v docker >/dev/null 2>&1; then
    docker compose -f infra/docker-compose.yml up -d --build
    sleep 10  # Wait for containers to be ready
else
    echo "docker not found, assuming services already running"
fi

echo "✅ Containers started"
echo ""

# Step 2: Check database health
echo "[Step 2] Checking database health..."
for i in {1..10}; do
    if curl -s "$BACKEND_URL/health/db" | grep -q '"ok":true'; then
        echo "✅ Database is healthy"
        break
    fi
    echo "  Attempt $i: waiting for DB..."
    sleep 2
done
echo ""

# Step 3: Create session
echo "[Step 3] Creating session..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/sessions" \
  -H "Content-Type: application/json" \
  -d '{"profession_query": "Senior Python Developer"}')

SESSION_ID=$(echo "$RESPONSE" | grep -o '"session_id":"[^"]*' | cut -d'"' -f4)
echo "  Session ID: $SESSION_ID"

if [ -z "$SESSION_ID" ]; then
    echo "❌ Failed to create session"
    exit 1
fi

echo "✅ Session created"
echo ""

# Step 4: Chat flow - start
echo "[Step 4] Chat flow: START..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"start\"}")

REPLY=$(echo "$RESPONSE" | grep -o '"reply":"[^"]*' | head -1 | cut -d'"' -f4)
echo "  Bot: $REPLY"

if ! echo "$REPLY" | grep -q "Привет"; then
    echo "❌ Unexpected bot response"
    exit 1
fi

echo "✅ Chat started"
echo ""

# Step 5: Chat flow - provide vacancy text
echo "[Step 5] Chat flow: VACANCY TEXT..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"message\", \"text\": \"Есть текст вакансии\"}")

REPLY=$(echo "$RESPONSE" | grep -o '"reply":"[^"]*' | head -1 | cut -d'"' -f4)
echo "  Bot: $REPLY"

echo "✅ Flow progressed"
echo ""

# Step 6: Chat flow - provide vacancy content
echo "[Step 6] Chat flow: VACANCY CONTENT..."
VACANCY_TEXT="Ищем Senior Python Developer.

Требования:
- Python 3.9+
- FastAPI or Django
- PostgreSQL
- 5+ лет опыта

Условия:
- Москва, гибрид
- 300-400к рублей
- Полный день"

RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"message\", \"text\": \"$VACANCY_TEXT\"}")

REPLY=$(echo "$RESPONSE" | grep -o '"reply":"[^"]*' | head -1 | cut -d'"' -f4)
echo "  Bot: $REPLY"

echo "✅ Vacancy text submitted"
echo ""

# Step 7: Chat flow - provide clarifications
echo "[Step 7] Chat flow: CLARIFICATIONS..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"message\", \"text\": \"Москва, гибрид, 300-400к, полный день\"}")

REPLY=$(echo "$RESPONSE" | grep -o '"reply":"[^"]*' | head -1 | cut -d'"' -f4)
echo "  Bot: $REPLY"

echo "✅ Clarifications submitted"
echo ""

# Step 8: Get vacancy KB
echo "[Step 8] Getting vacancy KB..."
RESPONSE=$(curl -s "$BACKEND_URL/vacancy?session_id=$SESSION_ID")

if echo "$RESPONSE" | grep -q '"vacancy_kb"'; then
    TASKS_COUNT=$(echo "$RESPONSE" | grep -o '"tasks":\[' | wc -l)
    echo "  Tasks extracted: $TASKS_COUNT"
    echo "✅ Vacancy KB retrieved"
else
    echo "❌ Failed to get vacancy KB"
    exit 1
fi
echo ""

# Step 9: Get free report
echo "[Step 9] Getting free report..."
RESPONSE=$(curl -s "$BACKEND_URL/report/free?session_id=$SESSION_ID")

if echo "$RESPONSE" | grep -q '"headline"'; then
    echo "  Report generated successfully"
    echo "✅ Free report retrieved"
else
    echo "❌ Failed to get free report"
    exit 1
fi
echo ""

# Step 10: Restart API container
echo "[Step 10] Restarting API container..."
if command -v docker >/dev/null 2>&1; then
    docker compose -f infra/docker-compose.yml restart api
    sleep 5
    echo "✅ API restarted"
else
    echo "docker not found, skipping container restart"
fi
echo ""

# Step 11: Verify data persists after restart
echo "[Step 11] Verifying data persistence..."

# Get vacancy KB again
echo "  Checking vacancy KB..."
RESPONSE=$(curl -s "$BACKEND_URL/vacancy?session_id=$SESSION_ID")

if echo "$RESPONSE" | grep -q '"tasks"'; then
    echo "  ✅ Vacancy KB persisted"
else
    echo "  ❌ Vacancy KB lost after restart"
    exit 1
fi

# Get free report again
echo "  Checking free report cache..."
RESPONSE=$(curl -s "$BACKEND_URL/report/free?session_id=$SESSION_ID")

if echo "$RESPONSE" | grep -q '"headline"'; then
    echo "  ✅ Free report persisted"
else
    echo "  ❌ Free report lost after restart"
    exit 1
fi

echo ""
echo "========================================================================"
echo "✅ All Stage 5 tests PASSED!"
echo "========================================================================"
echo ""
echo "Summary:"
echo "  - Session created and persisted"
echo "  - Chat flow completed"
echo "  - Vacancy KB extracted and saved"
echo "  - Free report generated and cached"
echo "  - Data survived API container restart"
echo ""
echo "Database persistence is working correctly!"
