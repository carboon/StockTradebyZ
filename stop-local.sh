#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
RUN_DIR="$PROJECT_ROOT/data/run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"

stop_by_pid_file() {
  local pid_file="$1"
  local name="$2"

  if [[ ! -f "$pid_file" ]]; then
    echo "$name 未运行"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "$name 已停止 (PID=$pid)"
  else
    echo "$name 进程不存在，清理 PID 文件"
  fi
  rm -f "$pid_file"
}

stop_by_pid_file "$BACKEND_PID_FILE" "后端"
stop_by_pid_file "$FRONTEND_PID_FILE" "前端"
