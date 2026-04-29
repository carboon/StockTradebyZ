#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

log() {
  printf '%s\n' "$1"
}

python_supports_bootstrap() {
  local python_bin="$1"
  "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

resolve_bootstrap_python() {
  local candidate path
  for candidate in .venv/bin/python python3.12 python3.11 python3.10 python3 python; do
    if [[ "$candidate" == */* ]]; then
      path="$candidate"
      [[ -x "$path" ]] || continue
    else
      path="$(command -v "$candidate" 2>/dev/null || true)"
      [[ -n "$path" ]] || continue
    fi

    if python_supports_bootstrap "$path"; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return 0
  fi

  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
    return 0
  fi

  printf '%s\n' "缺少 sudo，无法自动安装系统 Python。" >&2
  exit 1
}

enable_brew() {
  local brew_bin
  for brew_bin in /opt/homebrew/bin/brew /usr/local/bin/brew /home/linuxbrew/.linuxbrew/bin/brew; do
    if [[ -x "$brew_bin" ]]; then
      eval "$("$brew_bin" shellenv)"
      return 0
    fi
  done
  return 1
}

ensure_homebrew() {
  if enable_brew; then
    return 0
  fi

  if ! command -v curl >/dev/null 2>&1; then
    printf '%s\n' "未检测到 curl，无法自动安装 Homebrew。" >&2
    exit 1
  fi

  log "未检测到 Homebrew，开始自动安装..."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  enable_brew || {
    printf '%s\n' "Homebrew 安装完成后仍未检测到 brew。" >&2
    exit 1
  }
}

install_bootstrap_python() {
  case "$(uname -s)" in
    Darwin)
      ensure_homebrew
      brew install python@3.11
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1; then
        run_privileged apt-get update
        run_privileged apt-get install -y python3.12 python3.12-venv python3-pip || \
          run_privileged apt-get install -y python3.11 python3.11-venv python3-pip || \
          run_privileged apt-get install -y python3 python3-venv python3-pip
      elif command -v dnf >/dev/null 2>&1; then
        run_privileged dnf install -y python3 python3-pip python3-virtualenv
      elif command -v yum >/dev/null 2>&1; then
        run_privileged yum install -y python3 python3-pip
      else
        ensure_homebrew
        brew install python@3.11
      fi
      ;;
    *)
      printf '%s\n' "当前平台不支持 start-local.sh 自动安装系统 Python。" >&2
      exit 1
      ;;
  esac
}

PYTHON_BIN="$(resolve_bootstrap_python || true)"
if [[ -z "$PYTHON_BIN" ]]; then
  log "未检测到可用于引导的 Python，开始自动安装系统 Python..."
  install_bootstrap_python
  PYTHON_BIN="$(resolve_bootstrap_python || true)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  printf '%s\n' "系统 Python 安装后仍未检测到可用解释器。" >&2
  exit 1
fi

exec "$PYTHON_BIN" tools/localctl.py start "$@"
