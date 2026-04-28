#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
PYTHON_BIN="${PYTHON_BIN:-}"
NODE_BIN="${NODE_BIN:-node}"
NPM_BIN="${NPM_BIN:-npm}"
AUTO_INSTALL_SYSTEM_DEPS="${AUTO_INSTALL_SYSTEM_DEPS:-0}"
OS_NAME=""
PKG_MANAGER=""
PIP_INDEX_CANDIDATES=(
  "${PIP_INDEX_URL}"
  "https://pypi.tuna.tsinghua.edu.cn/simple"
  "https://mirrors.aliyun.com/pypi/simple"
  "https://pypi.org/simple"
)
NPM_REGISTRY_CANDIDATES=(
  "${NPM_REGISTRY}"
  "https://registry.npmmirror.com"
  "https://registry.npmjs.org"
)

log() {
  printf '%s\n' "$1"
}

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

detect_platform() {
  OS_NAME="$(uname -s)"

  case "$OS_NAME" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        PKG_MANAGER="brew"
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        PKG_MANAGER="apt-get"
      elif command -v dnf >/dev/null 2>&1; then
        PKG_MANAGER="dnf"
      elif command -v yum >/dev/null 2>&1; then
        PKG_MANAGER="yum"
      fi
      ;;
  esac
}

print_system_dependency_help() {
  cat <<EOF
当前缺少系统依赖。可先手动安装后再执行 ./install-local.sh

EOF

  case "$PKG_MANAGER" in
    brew)
      cat <<'EOF'
macOS(Homebrew):
  brew install python@3.11 node sqlite
EOF
      ;;
    apt-get)
      cat <<'EOF'
Debian / Ubuntu:
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv python3-pip nodejs npm lsof sqlite3 curl
EOF
      ;;
    dnf)
      cat <<'EOF'
Fedora / Rocky / AlmaLinux:
  sudo dnf install -y python3 python3-pip python3-virtualenv nodejs npm lsof sqlite curl
EOF
      ;;
    yum)
      cat <<'EOF'
CentOS:
  sudo yum install -y python3 python3-pip nodejs npm lsof sqlite curl
EOF
      ;;
    *)
      cat <<'EOF'
请安装以下命令后重试：
  Python 3.11+
  python3-venv / venv
  pip
  node
  npm
  lsof
  curl
EOF
      ;;
  esac
}

install_system_packages() {
  case "$PKG_MANAGER" in
    brew)
      log "自动安装系统依赖: brew install python@3.11 node sqlite"
      brew install python@3.11 node sqlite
      ;;
    apt-get)
      log "自动安装系统依赖: sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip nodejs npm lsof sqlite3 curl"
      sudo apt-get update
      sudo apt-get install -y python3 python3-venv python3-pip nodejs npm lsof sqlite3 curl
      ;;
    dnf)
      log "自动安装系统依赖: sudo dnf install -y python3 python3-pip python3-virtualenv nodejs npm lsof sqlite curl"
      sudo dnf install -y python3 python3-pip python3-virtualenv nodejs npm lsof sqlite curl
      ;;
    yum)
      log "自动安装系统依赖: sudo yum install -y python3 python3-pip nodejs npm lsof sqlite curl"
      sudo yum install -y python3 python3-pip nodejs npm lsof sqlite curl
      ;;
    *)
      fail "未识别可用的包管理器，无法自动安装系统依赖"
      ;;
  esac
}

ensure_command() {
  local cmd="$1"
  local desc="$2"

  if command -v "$cmd" >/dev/null 2>&1; then
    return 0
  fi

  if [[ "$AUTO_INSTALL_SYSTEM_DEPS" == "1" ]]; then
    install_system_packages
    command -v "$cmd" >/dev/null 2>&1 && return 0
  fi

  print_system_dependency_help
  fail "缺少 ${desc}: ${cmd}"
}

ensure_system_dependencies() {
  detect_platform

  ensure_command curl "网络检测工具"
  ensure_command lsof "端口检测工具"
  ensure_command node "Node.js"
  ensure_command npm "npm"

  if [[ -n "$PYTHON_BIN" ]]; then
    ensure_command "$PYTHON_BIN" "指定的 Python"
  else
    local found_python=0
    for candidate in python3.12 python3.11 python3; do
      if command -v "$candidate" >/dev/null 2>&1; then
        found_python=1
        break
      fi
    done

    if [[ "$found_python" == "0" ]]; then
      if [[ "$AUTO_INSTALL_SYSTEM_DEPS" == "1" ]]; then
        install_system_packages
      fi
    fi
  fi
}

detect_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "未找到指定的 Python: $PYTHON_BIN"
    return
  fi

  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      return
    fi
  done

  fail "未找到可用的 Python 3.11+"
}

check_python_version() {
  "$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11 或更高版本")
PY
}

ensure_venv_and_pip() {
  if ! "$PYTHON_BIN" -m venv --help >/dev/null 2>&1; then
    print_system_dependency_help
    fail "当前 Python 未提供 venv 模块，请安装 python3-venv 或等效组件"
  fi

  if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    print_system_dependency_help
    fail "当前 Python 未提供 pip，请安装 python3-pip 或等效组件"
  fi
}

check_node() {
  command -v "$NODE_BIN" >/dev/null 2>&1 || fail "未找到 Node.js"
  command -v "$NPM_BIN" >/dev/null 2>&1 || fail "未找到 npm"
}

prepare_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    log "已从 .env.example 复制 .env，请至少填入 TUSHARE_TOKEN。"
  fi

  mkdir -p data/db data/raw data/candidates data/review data/kline data/logs data/run
}

install_backend() {
  if [[ ! -d .venv ]]; then
    log "创建虚拟环境..."
    "$PYTHON_BIN" -m venv .venv
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate

  log "升级 pip..."
  install_with_pip_fallback --upgrade pip

  log "安装后端依赖..."
  install_with_pip_fallback -r requirements.txt
  install_with_pip_fallback -r backend/requirements.txt
}

install_frontend() {
  log "安装前端依赖..."
  (
    cd frontend
    install_with_npm_fallback
  )
}

install_with_pip_fallback() {
  local args=("$@")
  local index
  for index in "${PIP_INDEX_CANDIDATES[@]}"; do
    log "尝试 pip 源: $index"
    if pip install "${args[@]}" -i "$index"; then
      PIP_INDEX_URL="$index"
      return 0
    fi
  done
  fail "pip 依赖安装失败，已尝试所有镜像源"
}

install_with_npm_fallback() {
  local registry
  for registry in "${NPM_REGISTRY_CANDIDATES[@]}"; do
    log "尝试 npm 源: $registry"
    if "$NPM_BIN" install --registry "$registry"; then
      NPM_REGISTRY="$registry"
      return 0
    fi
  done
  fail "npm 依赖安装失败，已尝试所有镜像源"
}

write_frontend_env() {
  local api_base_url
  api_base_url="$(grep -E '^VITE_API_BASE_URL=' .env | tail -n1 | cut -d'=' -f2- || true)"

  if [[ -z "$api_base_url" ]]; then
    api_base_url="/api"
  fi

  cat > frontend/.env.local <<EOF
VITE_API_BASE_URL=${api_base_url}
EOF
}

summary() {
  if [[ -f .env ]]; then
    if ./preflight-local.sh >/dev/null 2>&1; then
      preflight_status="通过"
    else
      preflight_status="未通过（通常是 TUSHARE_TOKEN 尚未配置）"
    fi
  else
    preflight_status="未执行"
  fi

  cat <<EOF

安装完成。

已使用国内加速源：
- pip: ${PIP_INDEX_URL}
- npm: ${NPM_REGISTRY}
- 预检状态: ${preflight_status}

下一步：
1. 直接启动系统：./bootstrap-local.sh
2. 首次进入后，如页面提示未配置 Tushare，请在配置页填写并验证 Token
3. Token 配置完成后，再执行首次数据初始化：./init-data.sh
EOF
}

main() {
  ensure_system_dependencies
  detect_python
  check_python_version
  ensure_venv_and_pip
  check_node
  prepare_env
  install_backend
  install_frontend
  write_frontend_env
  summary
}

main "$@"
