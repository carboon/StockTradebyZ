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

print_help() {
  cat <<'EOF'
usage: ./uninstall-local.sh

停止本地服务，并清理当前项目生成的配置、依赖、构建产物和数据。
EOF
}

remove_path() {
  local target="$1"
  if [[ -e "$target" ]]; then
    rm -rf "$target"
    log "已删除: $target"
  fi
}

cleanup_user_services() {
  case "$(uname -s)" in
    Linux)
      if command -v systemctl >/dev/null 2>&1; then
        systemctl --user disable --now "$BACKEND_SERVICE_NAME" "$FRONTEND_SERVICE_NAME" >/dev/null 2>&1 || true
        systemctl --user daemon-reload >/dev/null 2>&1 || true
      fi
      remove_path "$SYSTEMD_USER_DIR/$BACKEND_SERVICE_NAME"
      remove_path "$SYSTEMD_USER_DIR/$FRONTEND_SERVICE_NAME"
      ;;
    Darwin)
      if command -v launchctl >/dev/null 2>&1; then
        launchctl unload "$LAUNCHD_USER_DIR/$BACKEND_PLIST_NAME" >/dev/null 2>&1 || true
        launchctl unload "$LAUNCHD_USER_DIR/$FRONTEND_PLIST_NAME" >/dev/null 2>&1 || true
      fi
      remove_path "$LAUNCHD_USER_DIR/$BACKEND_PLIST_NAME"
      remove_path "$LAUNCHD_USER_DIR/$FRONTEND_PLIST_NAME"
      ;;
  esac
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  print_help
  exit 0
fi

log "开始卸载本地内容"
log "- 停止本地服务"
log "- 清理本目录生成的配置、依赖、构建产物和数据"

"$PROJECT_ROOT/stop-local.sh" || true
cleanup_user_services

for target in \
  "$PROJECT_ROOT/.env" \
  "$PROJECT_ROOT/.venv" \
  "$PROJECT_ROOT/.pytest_cache" \
  "$PROJECT_ROOT/frontend/.env.local" \
  "$PROJECT_ROOT/frontend/node_modules" \
  "$PROJECT_ROOT/frontend/dist" \
  "$PROJECT_ROOT/frontend/coverage" \
  "$PROJECT_ROOT/.coverage" \
  "$PROJECT_ROOT/htmlcov" \
  "$PROJECT_ROOT/data" \
  "$PROJECT_ROOT/deploy"
do
  remove_path "$target"
done

while IFS= read -r cache_dir; do
  [[ -n "$cache_dir" ]] || continue
  remove_path "$cache_dir"
done < <(find "$PROJECT_ROOT" -type d -name "__pycache__" -prune -print 2>/dev/null || true)

log "卸载完成"
