#!/usr/bin/env bash
set -euo pipefail

# Скрипт для запуска dev окружения локально

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "Запускаю backend (api)..."
cd "$REPO_ROOT/api"
python3 main.py &
API_PID=$!
echo "Backend PID: $API_PID"

echo "Ожидание запуска backend..."
sleep 3

echo "Запускаю frontend..."
cd "$REPO_ROOT/front"
npm run dev &
FRONT_PID=$!
echo "Frontend PID: $FRONT_PID"

echo ""
echo "Сервисы запущены:"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo ""
echo "Для остановки: kill $API_PID $FRONT_PID"
echo ""
echo "PIDs сохранены в .dev-pids"
echo "$API_PID $FRONT_PID" > "$REPO_ROOT/.dev-pids"

wait
