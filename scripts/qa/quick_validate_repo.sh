#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

python3 -m py_compile api/main.py 2>&1 && echo "✅ api/main.py syntax OK" || exit 1

python3 tests/test-parsing.py 2>&1 | grep -c "✓" > /dev/null && echo "✅ Parsing tests passed" || exit 1

test -f front/src/app/api/vacancy/route.ts && echo "✅ Frontend proxy route exists" || exit 1

test -f docs/stages/stage3/STAGE3_IMPLEMENTATION.md && echo "✅ Stage 3 docs exist" || exit 1

git diff --quiet infra/ && echo "✅ infra/ unchanged" || exit 1

echo ""
echo "==============================================="
echo "Quick validation: ALL CHECKS PASSED ✅"
echo "==============================================="
echo ""

echo "Files changed:"
git status --short | grep -v "^??" || true

echo ""
echo "New files:"
git status --short | grep "^??" || true
