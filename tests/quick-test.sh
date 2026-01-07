#!/bin/bash
set -euo pipefail

echo "[DEPRECATED] Используйте: ./scripts/qa/quick_validate_repo.sh" >&2

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/scripts/qa/quick_validate_repo.sh" "$@"
