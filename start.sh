#!/bin/bash
# StockTrader 本地启动入口

set -euo pipefail

cd "$(dirname "$0")"
exec python3 scripts/utils/localctl.py start "$@"
