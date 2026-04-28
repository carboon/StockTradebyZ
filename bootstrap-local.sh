#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

log() {
  printf '%s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

ensure_executable() {
  chmod +x install-local.sh preflight-local.sh init-data.sh start-local.sh status-local.sh stop-local.sh generate-service.sh uninstall-local.sh
}

check_token_configured() {
  [[ -f .env ]] || return 1
  local token
  token="$(grep -E '^TUSHARE_TOKEN=' .env | tail -n1 | cut -d'=' -f2- || true)"
  [[ -n "$token" && "$token" != "your_tushare_token_here" ]]
}

main() {
  ensure_executable
  ./install-local.sh

  if ! check_token_configured; then
    cat <<EOF

安装已完成，当前未配置有效的 TUSHARE_TOKEN。
系统将先启动前后端，请在浏览器进入配置页完成 Token 配置后再执行数据初始化。
EOF
    ./start-local.sh
    exit 0
  fi

  ./preflight-local.sh

  ./start-local.sh

  if [[ "${SKIP_INIT_DATA:-0}" != "1" ]]; then
    log "通过应用 API 执行首次数据初始化..."
    ./init-data.sh
  fi
}

main "$@"
