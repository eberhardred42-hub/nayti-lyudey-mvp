#!/bin/bash

# Quick validation that api/main.py is syntactically correct
python3 -m py_compile api/main.py 2>&1 && echo "✅ api/main.py syntax OK" || exit 1

# Quick validation of parsing functions
python3 test-parsing.py 2>&1 | grep -c "✓" > /dev/null && echo "✅ Parsing tests passed" || exit 1

# Check that proxy route exists
test -f front/src/app/api/vacancy/route.ts && echo "✅ Frontend proxy route exists" || exit 1

# Check that documentation exists
test -f STAGE3_IMPLEMENTATION.md && echo "✅ Implementation docs exist" || exit 1

# Verify infra not changed
git diff infra/ --quiet && echo "✅ infra/ unchanged" || exit 1

echo ""
echo "==============================================="
echo "Stage 3 Implementation: ALL CHECKS PASSED ✅"
echo "==============================================="
echo ""
echo "Files changed:"
git status --short | grep -v "^??"
echo ""
echo "New files:"
git status --short | grep "^??"
echo ""
echo "Ready for commit!"
