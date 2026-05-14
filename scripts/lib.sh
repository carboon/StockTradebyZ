#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"

ensure_pythonpath() {
  local pythonpath="${PYTHONPATH:-}"

  case ":$pythonpath:" in
    *":$PROJECT_ROOT:"*) ;;
    *) pythonpath="${pythonpath:+$pythonpath:}$PROJECT_ROOT" ;;
  esac

  case ":$pythonpath:" in
    *":$BACKEND_DIR:"*) ;;
    *) pythonpath="${pythonpath:+$pythonpath:}$BACKEND_DIR" ;;
  esac

  export PYTHONPATH="$pythonpath"
}

resolve_python() {
  if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    printf '%s\n' "$PROJECT_ROOT/.venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    printf '%s\n' "python3"
    return 0
  fi

  printf '%s\n' "python"
}

run_backend_script() {
  local script_name="$1"
  shift

  if [ ! -f "$BACKEND_DIR/scripts/$script_name" ]; then
    echo "未找到 backend 脚本: $BACKEND_DIR/scripts/$script_name" >&2
    exit 1
  fi

  ensure_pythonpath
  exec "$(resolve_python)" "$BACKEND_DIR/scripts/$script_name" "$@"
}
