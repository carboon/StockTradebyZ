#!/bin/bash
# 历史数据修复脚本 - 从主机运行
cd "$(dirname "$0")/.."

export DATABASE_URL="postgresql://stocktrade:stocktrade123@localhost:5432/stocktrade"
export PYTHONPATH="/Volumes/DATA/StockTradebyZ/backend"
export VIRTUAL_ENV="/Volumes/DATA/StockTradebyZ/.venv"

.venv/bin/python backend/scripts/repair_historical_scores.py "$@"
