#!/bin/bash
# StockTrader 本地部署停止入口

set -euo pipefail

cd "$(dirname "$0")"
exec python3 scripts/utils/localctl.py stop "$@"
