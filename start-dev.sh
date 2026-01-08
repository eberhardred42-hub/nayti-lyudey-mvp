#!/bin/bash
# Скрипт для запуска dev окружения локально

echo "Запускаю backend (api)..."
cd /workspaces/nayti-lyudey-mvp/api
python3 main.py &
API_PID=$!
echo "Backend PID: $API_PID"

echo "Ожидание запуска backend..."
sleep 3

echo "Запускаю frontend..."
cd /workspaces/nayti-lyudey-mvp/front
# В локальном dev backend слушает localhost:8000 (см. выше),
# поэтому прокси-роуты Next.js должны ходить именно туда.
BACKEND_URL=http://localhost:8000 npm run dev &
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
echo "$API_PID $FRONT_PID" > /workspaces/nayti-lyudey-mvp/.dev-pids

wait
