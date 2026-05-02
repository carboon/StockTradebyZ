#!/bin/bash
# StockTrader 开发模式入口：本机后端 + Vite dev server

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$ROOT_DIR/data/run"
LOG_DIR="$ROOT_DIR/data/logs"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
ENV_FILE="$ROOT_DIR/.env"

mkdir -p "$RUN_DIR" "$LOG_DIR"

cd "$ROOT_DIR"

python3 scripts/utils/localctl.py start --skip-init-data "$@"

if [ -f "$ENV_FILE" ]; then
  BACKEND_PORT="$(grep -E '^BACKEND_PORT=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)"
  FRONTEND_PORT="$(grep -E '^FRONTEND_PORT=' "$ENV_FILE" | tail -n 1 | cut -d= -f2-)"
fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if [ -f "$FRONTEND_PID_FILE" ]; then
  FRONTEND_PID="$(cat "$FRONTEND_PID_FILE" 2>/dev/null || true)"
  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo "前端 dev server 已在运行，PID=$FRONTEND_PID"
    echo "Vite: http://127.0.0.1:$FRONTEND_PORT"
    exit 0
  fi
  rm -f "$FRONTEND_PID_FILE"
fi

(
  cd "$ROOT_DIR/frontend"
  VITE_API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT" nohup npm run dev -- --host 0.0.0.0 >"$LOG_DIR/frontend-dev.log" 2>&1 &
  echo $! >"$FRONTEND_PID_FILE"
)

echo "开发模式已启动"
echo "后端: http://127.0.0.1:$BACKEND_PORT"
echo "前端: http://127.0.0.1:$FRONTEND_PORT"
echo "日志: $LOG_DIR/frontend-dev.log"
