#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"
LAUNCHD_USER_DIR="${HOME}/Library/LaunchAgents"
BACKEND_SERVICE_NAME="stocktrader-backend.service"
FRONTEND_SERVICE_NAME="stocktrader-frontend.service"
BACKEND_PLIST_NAME="com.stocktrader.backend.plist"
FRONTEND_PLIST_NAME="com.stocktrader.frontend.plist"

log() {
  printf '%s\n' "$1"
}

kill_pid() {
  local pid="$1"
  local label="$2"

  [[ -n "$pid" ]] || return 0

  if kill -0 "$pid" 2>/dev/null; then
    if ! kill "$pid" 2>/dev/null; then
      log "无法停止: ${label} (PID=${pid})，请在本机终端手动结束该进程"
      return 0
    fi
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      if ! kill -9 "$pid" 2>/dev/null; then
        log "无法强制停止: ${label} (PID=${pid})，请在本机终端手动执行 kill -9 ${pid}"
        return 0
      fi
    fi
    log "已停止: ${label} (PID=${pid})"
  fi
}

kill_by_port() {
  local port="$1"
  local label="$2"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | sort -u || true)"
  [[ -n "$pids" ]] || return 0

  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    kill_pid "$pid" "${label}:${port}"
  done <<< "$pids"
}

kill_project_processes_by_cwd() {
  local subdir="$1"
  local label="$2"
  local target_dir="${PROJECT_ROOT}/${subdir}"
  local pids

  pids="$(
    lsof -t +d "$target_dir" 2>/dev/null | sort -u || true
  )"
  [[ -n "$pids" ]] || return 0

  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    kill_pid "$pid" "${label}:${subdir}"
  done <<< "$pids"
}

remove_path() {
  local target="$1"
  if [[ -e "$target" ]]; then
    rm -rf "$target"
    log "已删除: $target"
  fi
}

stop_local_processes() {
  if [[ -x ./stop-local.sh ]]; then
    ./stop-local.sh || true
  fi

  # PID 文件不存在时，仍按默认端口做一次兜底清理。
  kill_by_port 8000 "backend"
  kill_by_port 5173 "frontend"

  # 再按项目工作目录清理残留进程，避免 dev server 已切换端口时漏删。
  kill_project_processes_by_cwd "backend" "backend"
  kill_project_processes_by_cwd "frontend" "frontend"
}

cleanup_systemd() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    return
  fi

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now "$BACKEND_SERVICE_NAME" "$FRONTEND_SERVICE_NAME" >/dev/null 2>&1 || true
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi

  remove_path "${SYSTEMD_USER_DIR}/${BACKEND_SERVICE_NAME}"
  remove_path "${SYSTEMD_USER_DIR}/${FRONTEND_SERVICE_NAME}"
}

cleanup_launchd() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return
  fi

  if command -v launchctl >/dev/null 2>&1; then
    launchctl unload "${LAUNCHD_USER_DIR}/${BACKEND_PLIST_NAME}" >/dev/null 2>&1 || true
    launchctl unload "${LAUNCHD_USER_DIR}/${FRONTEND_PLIST_NAME}" >/dev/null 2>&1 || true
  fi

  remove_path "${LAUNCHD_USER_DIR}/${BACKEND_PLIST_NAME}"
  remove_path "${LAUNCHD_USER_DIR}/${FRONTEND_PLIST_NAME}"
}

remove_local_artifacts() {
  remove_path "$PROJECT_ROOT/.env"
  remove_path "$PROJECT_ROOT/.venv"
  remove_path "$PROJECT_ROOT/.pytest_cache"
  remove_path "$PROJECT_ROOT/frontend/.env.local"
  remove_path "$PROJECT_ROOT/frontend/node_modules"
  remove_path "$PROJECT_ROOT/frontend/dist"
  remove_path "$PROJECT_ROOT/data"
  remove_path "$PROJECT_ROOT/deploy"
}

main() {
  cat <<EOF
开始卸载本地部署内容：
- 停止前后端本地进程
- 卸载本机守护服务（systemd/launchd，如存在）
- 删除数据库、配置文件、本地数据目录
- 删除虚拟环境、前端依赖与构建产物
EOF

  stop_local_processes
  cleanup_systemd
  cleanup_launchd
  remove_local_artifacts

  cat <<EOF

卸载完成。
已清理：
- 数据库与本地数据: data/
- 配置文件: .env, frontend/.env.local
- Python 环境: .venv
- 前端依赖与构建产物: frontend/node_modules, frontend/dist
- 守护服务文件: deploy/, 用户级 systemd/launchd 配置
EOF
}

main "$@"
