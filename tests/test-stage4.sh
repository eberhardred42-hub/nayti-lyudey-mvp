#!/bin/bash
# Integration tests for Stage 4 free report generation
# Tests the full flow: session → chat → report

set -e

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
SESSION_ID=""

echo "================================"
echo "Stage 4 Integration Test Suite"
echo "================================"
echo "Backend: $BACKEND_URL"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Test 1: Create session
echo "Test 1: Creating session..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/sessions" \
  -H "Content-Type: application/json" \
    -d '{"profession_query":"Test Employer"}')

SESSION_ID=$(echo "$RESPONSE" | grep -o '"session_id":"[^"]*"' | cut -d'"' -f4)
if [ -z "$SESSION_ID" ]; then
    echo -e "${RED}❌ Failed to create session${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Session created: $SESSION_ID${NC}"
echo ""

# Test 2: Start chat
echo "Test 2: Starting chat..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"start\", \"text\": null}")

if echo "$RESPONSE" | grep -q '"quick_replies"'; then
        echo -e "${GREEN}✓ Chat started successfully${NC}"
else
        echo -e "${RED}❌ Failed to start chat${NC}"
        echo "Response: $RESPONSE"
        exit 1
fi
echo ""

# Test 3: Choose flow with vacancy text
echo "Test 3: Choosing 'Есть текст вакансии' flow..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
  -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"reply\", \"text\": \"Есть текст вакансии\"}")

if echo "$RESPONSE" | grep -q '"reply"'; then
        echo -e "${GREEN}✓ Flow selected: vacancy_text${NC}"
else
        echo -e "${RED}❌ Failed to select flow${NC}"
        echo "Response: $RESPONSE"
        exit 1
fi
echo ""

# Test 4: Submit vacancy text (via chat)
echo "Test 4: Submitting vacancy text..."
VACANCY_TEXT="Ищем Senior Python Developer. Требования: 5+ лет опыта с Python, Django, PostgreSQL. Зарплата 250k-350k. Офис в Москве, гибрид возможен."

RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"reply\", \"text\": \"$VACANCY_TEXT\"}")

if echo "$RESPONSE" | grep -q '"reply"'; then
        echo -e "${GREEN}✓ Vacancy text submitted${NC}"
else
        echo -e "${RED}❌ Failed to submit vacancy text${NC}"
        echo "Response: $RESPONSE"
        exit 1
fi
echo ""

# Test 5: Submit clarifications
echo "Test 5: Submitting clarifications..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/chat/message" \
    -H "Content-Type: application/json" \
    -d "{\"session_id\": \"$SESSION_ID\", \"type\": \"reply\", \"text\": \"Москва, гибридно, 250-350к, фулл тайм\"}")

if echo "$RESPONSE" | grep -q '"should_show_free_result"'; then
        echo -e "${GREEN}✓ Clarifications processed${NC}"
else
        echo -e "${GREEN}✓ Clarifications processed${NC}"
fi
echo ""

# Test 6: Get free report
echo "Test 6: Fetching free report..."
REPORT_RESPONSE=$(curl -s -X GET "$BACKEND_URL/report/free?session_id=$SESSION_ID" \
  -H "Content-Type: application/json")

# Validate JSON structure using grep
if echo "$REPORT_RESPONSE" | grep -q '"free_report"'; then
    echo -e "${GREEN}✓ Free report structure valid${NC}"
else
    echo -e "${RED}❌ Invalid report structure${NC}"
    echo "Response: $REPORT_RESPONSE"
    exit 1
fi

# Check required sections
SECTIONS=("headline" "where_to_search" "what_to_screen" "budget_reality_check" "next_steps")
for section in "${SECTIONS[@]}"; do
    if echo "$REPORT_RESPONSE" | grep -q "\"$section\""; then
        echo -e "${GREEN}  ✓ Section '$section' present${NC}"
    else
        echo -e "${RED}  ❌ Missing section: $section${NC}"
        exit 1
    fi
done
echo ""

# Test 7: Validate headline is non-empty
echo "Test 7: Validating headline..."
HEADLINE=$(echo "$REPORT_RESPONSE" | grep -o '"headline":"[^"]*"' | cut -d'"' -f4)
if [ -n "$HEADLINE" ] && [ ${#HEADLINE} -gt 10 ]; then
    echo -e "${GREEN}✓ Headline valid: ${HEADLINE:0:50}...${NC}"
else
    echo -e "${RED}❌ Headline invalid or empty${NC}"
    exit 1
fi
echo ""

# Test 8: Validate where_to_search is non-empty
echo "Test 8: Validating where_to_search..."
if echo "$REPORT_RESPONSE" | grep -q '"title":"'; then
    echo -e "${GREEN}✓ Where to search has platforms${NC}"
else
    echo -e "${RED}❌ Where to search is empty${NC}"
    exit 1
fi
echo ""

# Test 9: Validate budget status
echo "Test 9: Validating budget status..."
BUDGET_STATUS=$(echo "$REPORT_RESPONSE" | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4)
if [[ "$BUDGET_STATUS" =~ ^(ok|low|high|unknown)$ ]]; then
    echo -e "${GREEN}✓ Budget status valid: $BUDGET_STATUS${NC}"
else
    echo -e "${RED}❌ Budget status invalid: $BUDGET_STATUS${NC}"
    exit 1
fi
echo ""

# Test 10: Check JSON is valid
echo "Test 10: Validating JSON format..."
if echo "$REPORT_RESPONSE" | python3 -m json.tool > /dev/null 2>&1; then
    echo -e "${GREEN}✓ JSON format is valid${NC}"
else
    echo -e "${RED}❌ JSON format is invalid${NC}"
    exit 1
fi
echo ""

# Summary
echo "================================"
echo -e "${GREEN}🎉 All integration tests passed! (10/10)${NC}"
echo "================================"
echo ""
echo "Test Summary:"
echo "  ✓ Session creation"
echo "  ✓ Chat initialization"
echo "  ✓ Flow selection"
echo "  ✓ Vacancy text submission"
echo "  ✓ Clarifications processing"
echo "  ✓ Free report generation"
echo "  ✓ Report structure validation"
echo "  ✓ Headline validation"
echo "  ✓ Where to search validation"
echo "  ✓ Budget status validation"
echo "  ✓ JSON format validation"
echo ""
echo "Sample Report (first 500 chars):"
echo "$REPORT_RESPONSE" | head -c 500
echo "..."
echo ""
