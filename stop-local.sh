#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

RUN_DIR="$PROJECT_ROOT/data/run"
BACKEND_PID_FILE="$RUN_DIR/backend.pid"
FRONTEND_PID_FILE="$RUN_DIR/frontend.pid"
DEFAULT_BACKEND_PORT=8000
DEFAULT_FRONTEND_PORT=5173

log() {
  printf '%s\n' "$1"
}

print_help() {
  cat <<'EOF'
usage: ./stop-local.sh

停止本地后端进程，并清理 pid 文件。
EOF
}

read_env_value() {
  local key="$1"
  local default_value="$2"
  local value=""

  if [[ -f "$PROJECT_ROOT/.env" ]]; then
    value="$(grep -E "^${key}=" "$PROJECT_ROOT/.env" | tail -n 1 | cut -d'=' -f2- || true)"
  fi

  if [[ -n "$value" ]]; then
    printf '%s\n' "$value"
  else
    printf '%s\n' "$default_value"
  fi
}

read_pid() {
  local pid_file="$1"
  if [[ -f "$pid_file" ]]; then
    tr -d '[:space:]' < "$pid_file"
  fi
}

process_exists() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

stop_pid() {
  local pid="$1"
  local label="$2"
  local waited=0

  process_exists "$pid" || return 0

  kill "$pid" 2>/dev/null || true
  while process_exists "$pid" && [[ "$waited" -lt 25 ]]; do
    sleep 0.2
    waited=$((waited + 1))
  done

  if process_exists "$pid"; then
    kill -9 "$pid" 2>/dev/null || true
  fi

  if process_exists "$pid"; then
    log "${label} 停止失败 (PID=${pid})"
    return 1
  fi

  log "${label} 已停止 (PID=${pid})"
}

kill_pids_on_port() {
  local port="$1"
  local label="$2"
  local pids=""

  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u || true)"
  [[ -n "$pids" ]] || return 0

  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    stop_pid "$pid" "${label}:${port}" || true
  done <<< "$pids"
}

stop_target() {
  local pid_file="$1"
  local label="$2"
  local port="$3"
  local pid=""

  pid="$(read_pid "$pid_file" || true)"
  if [[ -n "$pid" ]] && process_exists "$pid"; then
    stop_pid "$pid" "$label" || true
  else
    kill_pids_on_port "$port" "$label"
    if [[ "$label" == "后端" ]]; then
      if command -v lsof >/dev/null 2>&1 && ! lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
        log "${label} 未运行"
      fi
    fi
  fi

  rm -f "$pid_file"
}

BACKEND_PORT="$(read_env_value "BACKEND_PORT" "$DEFAULT_BACKEND_PORT")"
FRONTEND_PORT="$(read_env_value "FRONTEND_PORT" "$DEFAULT_FRONTEND_PORT")"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  print_help
  exit 0
fi

stop_target "$BACKEND_PID_FILE" "后端" "$BACKEND_PORT"
stop_target "$FRONTEND_PID_FILE" "旧前端 dev server" "$FRONTEND_PORT"
