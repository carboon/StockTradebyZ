#!/usr/bin/env bash
set -euo pipefail

BACKEND_CONTAINER="${BACKEND_CONTAINER:-stocktrade-backend}"

docker exec "${BACKEND_CONTAINER}" python /app/backend/scripts/repair_incomplete_stock_daily.py "$@"
