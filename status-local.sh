#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"
RUN_DIR="$PROJECT_ROOT/data/run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

check_pid_file() {
  local pid_file="$1"
  local name="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "$name: 运行中 (PID=$pid)"
      return
    fi
  fi
  echo "$name: 未运行"
}

check_http() {
  local url="$1"
  local name="$2"
  if command -v curl >/dev/null 2>&1 && curl -fsS "$url" >/dev/null 2>&1; then
    echo "$name HTTP: 正常 ($url)"
  else
    echo "$name HTTP: 不可达 ($url)"
  fi
}

check_pid_file "$BACKEND_PID_FILE" "后端"
check_pid_file "$FRONTEND_PID_FILE" "前端"
check_http "http://127.0.0.1:${BACKEND_PORT}/health" "后端"
check_http "http://127.0.0.1:${FRONTEND_PORT}" "前端"
