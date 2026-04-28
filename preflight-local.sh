#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

BACKEND_PORT_DEFAULT=8000
OS_NAME=""
PKG_MANAGER=""

ok() {
  printf '[OK] %s\n' "$1"
}

warn() {
  printf '[WARN] %s\n' "$1"
}

fail() {
  printf '[FAIL] %s\n' "$1" >&2
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

print_install_hint() {
  case "$PKG_MANAGER" in
    brew)
      printf '  安装命令: brew install python@3.11 node sqlite\n'
      ;;
    apt-get)
      printf '  安装命令: sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip nodejs npm lsof sqlite3 curl\n'
      ;;
    dnf)
      printf '  安装命令: sudo dnf install -y python3 python3-pip python3-virtualenv nodejs npm lsof sqlite curl\n'
      ;;
    yum)
      printf '  安装命令: sudo yum install -y python3 python3-pip nodejs npm lsof sqlite curl\n'
      ;;
  esac
}

check_python() {
  local python_bin=""
  for candidate in .venv/bin/python python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      python_bin="$candidate"
      break
    fi
  done

  if [[ -z "$python_bin" ]]; then
    warn "未检测到 Python 3.11+"
    print_install_hint
    fail "系统依赖未满足"
  fi

  "$python_bin" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit(1)
PY
  ok "Python 可用: $python_bin"

  if ! "$python_bin" -m venv --help >/dev/null 2>&1; then
    warn "当前 Python 缺少 venv 模块"
    print_install_hint
    fail "系统依赖未满足"
  fi

  if ! "$python_bin" -m pip --version >/dev/null 2>&1; then
    warn "当前 Python 缺少 pip 模块"
    print_install_hint
    fail "系统依赖未满足"
  fi
}

check_node() {
  if ! command -v node >/dev/null 2>&1; then
    warn "未检测到 Node.js"
    print_install_hint
    fail "系统依赖未满足"
  fi
  if ! command -v npm >/dev/null 2>&1; then
    warn "未检测到 npm"
    print_install_hint
    fail "系统依赖未满足"
  fi
  ok "Node.js / npm 可用"
}

load_env() {
  if [[ ! -f .env ]]; then
    fail "未检测到 .env，请先执行 ./install-local.sh"
  fi

  set -a
  # shellcheck disable=SC1091
  source .env
  set +a

  BACKEND_PORT="${BACKEND_PORT:-$BACKEND_PORT_DEFAULT}"
}

check_token() {
  if [[ -z "${TUSHARE_TOKEN:-}" || "${TUSHARE_TOKEN}" == "your_tushare_token_here" ]]; then
    warn "TUSHARE_TOKEN 未配置，系统可启动，但首次进入后需要在页面中完成配置"
    return
  fi
  ok "TUSHARE_TOKEN 已配置"
}

check_dirs() {
  mkdir -p data/db data/raw data/candidates data/review data/kline data/logs data/run
  ok "数据目录已就绪"
}

check_ports() {
  if command -v lsof >/dev/null 2>&1; then
    if lsof -i :"$BACKEND_PORT" >/dev/null 2>&1; then
      warn "后端端口 $BACKEND_PORT 已被占用"
    else
      ok "后端端口 $BACKEND_PORT 可用"
    fi
  else
    warn "未检测到 lsof，跳过端口检查"
    print_install_hint
  fi
  ok "本地部署模式将通过后端统一提供前端页面: http://127.0.0.1:${BACKEND_PORT}"
}

check_network() {
  if ! command -v curl >/dev/null 2>&1; then
    warn "未检测到 curl，跳过网络检查"
    return
  fi

  if curl -fsS --connect-timeout 5 https://tushare.pro >/dev/null 2>&1; then
    ok "Tushare 官网可访问"
  else
    warn "无法访问 https://tushare.pro，后续拉取数据可能失败"
  fi

  if curl -fsS --connect-timeout 5 https://pypi.tuna.tsinghua.edu.cn/simple >/dev/null 2>&1; then
    ok "pip 国内镜像可访问"
  else
    warn "pip 国内镜像不可访问"
  fi

  if curl -fsS --connect-timeout 5 https://registry.npmmirror.com >/dev/null 2>&1; then
    ok "npm 国内镜像可访问"
  else
    warn "npm 国内镜像不可访问"
  fi
}

main() {
  detect_platform
  check_python
  check_node
  load_env
  check_token
  check_dirs
  check_ports
  check_network
  ok "预检完成"
}

main "$@"
