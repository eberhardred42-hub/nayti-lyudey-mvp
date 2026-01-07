#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

bash tests/test-stage5.sh
