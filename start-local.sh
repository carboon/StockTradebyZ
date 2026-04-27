#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

RUN_DIR="$PROJECT_ROOT/data/run"
LOG_DIR="$PROJECT_ROOT/data/logs"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ ! -d .venv ]]; then
  echo "未检测到 .venv，请先执行 ./install-local.sh" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "未检测到 .env，请先执行 ./install-local.sh 并配置 TUSHARE_TOKEN" >&2
  exit 1
fi

if [[ "${SKIP_PREFLIGHT:-0}" != "1" ]]; then
  ./preflight-local.sh
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}/api}"

cat > frontend/.env.local <<EOF
VITE_API_BASE_URL=${VITE_API_BASE_URL}
EOF

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

wait_backend_ready() {
  local health_url="http://127.0.0.1:${BACKEND_PORT}/docs"
  local attempts=15
  local i

  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --connect-timeout 2 "$health_url" >/dev/null 2>&1; then
      echo "后端健康检查通过: $health_url"
      return 0
    fi
    sleep 1
  done

  echo "警告: 后端在 ${attempts}s 内未返回健康响应，前端仍会继续启动" >&2
  return 0
}

start_backend() {
  if [[ -f "$BACKEND_PID_FILE" ]] && is_pid_running "$(cat "$BACKEND_PID_FILE")"; then
    echo "后端已在运行，PID=$(cat "$BACKEND_PID_FILE")"
  else
    # shellcheck disable=SC1091
    source .venv/bin/activate
    nohup uvicorn app.main:app \
      --app-dir backend \
      --host "$BACKEND_HOST" \
      --port "$BACKEND_PORT" \
      > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$BACKEND_PID_FILE"
    echo "后端已启动，PID=$(cat "$BACKEND_PID_FILE")，日志: $LOG_DIR/backend.log"
  fi
}

start_frontend() {
  if [[ -f "$FRONTEND_PID_FILE" ]] && is_pid_running "$(cat "$FRONTEND_PID_FILE")"; then
    echo "前端已在运行，PID=$(cat "$FRONTEND_PID_FILE")"
  else
    (
      cd frontend
      nohup npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" \
        > "$LOG_DIR/frontend.log" 2>&1 &
      echo $! > "$FRONTEND_PID_FILE"
    )
    echo "前端已启动，PID=$(cat "$FRONTEND_PID_FILE")，日志: $LOG_DIR/frontend.log"
  fi
}

main() {
  start_backend
  wait_backend_ready
  start_frontend

  cat <<EOF

服务已启动：
- 前端: http://127.0.0.1:${FRONTEND_PORT}
- 后端: http://127.0.0.1:${BACKEND_PORT}
- API 文档: http://127.0.0.1:${BACKEND_PORT}/docs

查看状态：
./status-local.sh

停止服务：
./stop-local.sh
EOF
}

main "$@"
