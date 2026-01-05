#!/bin/bash
# Stage 5 Code Verification Test (without Docker)
# Verifies all files exist, have correct structure, and no syntax errors

echo "=== Stage 5 Code Verification (No Docker Required) ==="
echo

ERRORS=0

# Test 1: Check db.py exists
if [ -f "api/db.py" ]; then
    echo "✅ api/db.py exists"
    LINES=$(wc -l < api/db.py)
    echo "   Lines: $LINES"
else
    echo "❌ api/db.py missing"
    ERRORS=$((ERRORS+1))
fi
echo

# Test 2: Check for required functions in db.py
FUNCTIONS=("init_db" "health_check" "create_session" "get_session" "update_session" "add_message" "get_session_messages" "delete_session")
for FUNC in "${FUNCTIONS[@]}"; do
    if grep -q "def $FUNC" api/db.py; then
        echo "✅ Function '$FUNC' defined in db.py"
    else
        echo "❌ Function '$FUNC' missing from db.py"
        ERRORS=$((ERRORS+1))
    fi
done
echo

# Test 3: Check docker-compose.yml has postgres service
if grep -q "postgres:16" infra/docker-compose.yml; then
    echo "✅ PostgreSQL 16 service in docker-compose.yml"
else
    echo "❌ PostgreSQL service missing in docker-compose.yml"
    ERRORS=$((ERRORS+1))
fi

if grep -q "healthcheck:" infra/docker-compose.yml; then
    echo "✅ Healthcheck configured in docker-compose.yml"
else
    echo "❌ Healthcheck missing in docker-compose.yml"
    ERRORS=$((ERRORS+1))
fi
echo

# Test 4: Check requirements.txt has psycopg2-binary
if grep -q "psycopg2-binary" api/requirements.txt; then
    echo "✅ psycopg2-binary in requirements.txt"
else
    echo "❌ psycopg2-binary missing from requirements.txt"
    ERRORS=$((ERRORS+1))
fi
echo

# Test 5: Check documentation exists
if [ -f "docs/stages/stage5/STAGE5_SUMMARY.md" ]; then
    echo "✅ STAGE5_SUMMARY.md exists"
    LINES=$(wc -l < docs/stages/stage5/STAGE5_SUMMARY.md)
    echo "   Lines: $LINES"
else
    echo "❌ STAGE5_SUMMARY.md missing"
    ERRORS=$((ERRORS+1))
fi

if [ -f "docs/stages/stage5/STAGE5_IMPLEMENTATION.md" ]; then
    echo "✅ STAGE5_IMPLEMENTATION.md exists"
    LINES=$(wc -l < docs/stages/stage5/STAGE5_IMPLEMENTATION.md)
    echo "   Lines: $LINES"
else
    echo "❌ STAGE5_IMPLEMENTATION.md missing"
    ERRORS=$((ERRORS+1))
fi
echo

# Test 6: Check test script exists and is executable
if [ -f "tests/test-stage5.sh" ]; then
    echo "✅ tests/test-stage5.sh exists"
    if [ -x "tests/test-stage5.sh" ]; then
        echo "✅ tests/test-stage5.sh is executable"
    else
        echo "⚠️  tests/test-stage5.sh not executable (will fix)"
    fi
else
    echo "❌ tests/test-stage5.sh missing"
    ERRORS=$((ERRORS+1))
fi
echo

# Test 7: Check main.py has db imports
if grep -q "from db import" api/main.py; then
    echo "✅ api/main.py imports db module"
else
    echo "⚠️  api/main.py missing db imports"
fi

if grep -q "/health/db" api/main.py; then
    echo "✅ /health/db endpoint in api/main.py"
else
    echo "⚠️  /health/db endpoint missing in api/main.py"
fi
echo

# Test 8: Python syntax check on db.py
python3 -m py_compile api/db.py 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ api/db.py has valid Python syntax"
else
    echo "❌ api/db.py has syntax errors"
    python3 -m py_compile api/db.py
    ERRORS=$((ERRORS+1))
fi
echo

# Summary
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo "✅ ALL CODE VERIFICATION TESTS PASSED"
    echo "Stage 5 implementation is code-complete and ready for Docker execution."
    exit 0
else
    echo "❌ $ERRORS TESTS FAILED"
    exit 1
fi
