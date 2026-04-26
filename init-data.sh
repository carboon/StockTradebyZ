#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

if [[ ! -d .venv ]]; then
  echo "未检测到 .venv，请先执行 ./install-local.sh" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "未检测到 .env，请先执行 ./install-local.sh 并配置 TUSHARE_TOKEN" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${TUSHARE_TOKEN:-}" || "${TUSHARE_TOKEN}" == "your_tushare_token_here" ]]; then
  echo "请先在 .env 中配置有效的 TUSHARE_TOKEN" >&2
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python run_all.py --reviewer "${DEFAULT_REVIEWER:-quant}" --start-from 1
