#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
DEPLOY_DIR="$PROJECT_ROOT/deploy"
DOCKER_CONFIG_DIR="$PROJECT_ROOT/.docker"

show_help() {
  cat << 'EOF'
数据脚本统一入口

只保留四类操作:
  1. repair    修补数据
  2. generate  生成新数据（基于已有日线重建结果）
  3. daily     更新每日数据
  4. intraday  更新盘中数据（11:30 后执行，默认只取 09:30~11:30）

用法:
  ./update-data.sh daily
  ./update-data.sh daily --target-date 2026-05-14
  ./update-data.sh generate --dry-run
  ./update-data.sh intraday
  ./update-data.sh intraday --target-date 2026-05-14
  ./update-data.sh repair daily --min-days 250 --limit 20 --dry-run
  ./update-data.sh repair scores --scope both

说明:
  daily
    拉取最新交易日或指定交易日的日线，并重建当日明日之星/当前热盘

  generate
    不拉新日线，只基于现有数据库重建近120日窗口的明日之星/当前热盘

  intraday
    生成中盘快照；默认截止到 11:30:00

  repair daily
    修复 stock_daily 历史缺失/样本不足

  repair scores
    修复明日之星/当前热盘历史评分和结果

环境变量默认值:
  WINDOW_SIZE=120
  WARMUP_TRADE_DAYS=140
  REVIEWER=quant
  DIAGNOSIS_SCOPE=none
  WORKERS=auto
EOF
}

shell_join() {
  local quoted=()
  local part
  for part in "$@"; do
    printf -v escaped '%q' "$part"
    quoted+=("$escaped")
  done
  printf '%s ' "${quoted[@]}"
}

run_backend_command() {
  local mode="$1"
  shift

  local command
  command="$(shell_join "$@")"

  if ! command -v docker >/dev/null 2>&1; then
    echo "未找到 Docker，请先启动 Docker 环境" >&2
    exit 1
  fi

  mkdir -p "$DOCKER_CONFIG_DIR"
  export DOCKER_CONFIG="${DOCKER_CONFIG:-$DOCKER_CONFIG_DIR}"

  if docker ps --format '{{.Names}}' | grep -q '^stocktrade-backend$'; then
    echo "[update-data] mode=$mode use running container: stocktrade-backend"
    exec docker exec -i stocktrade-backend sh -lc "cd /app && $command"
  fi

  cd "$DEPLOY_DIR"

  local compose=()
  if docker compose version >/dev/null 2>&1; then
    compose=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    compose=(docker-compose)
  else
    echo "未找到 docker compose / docker-compose" >&2
    exit 1
  fi

  echo "[update-data] mode=$mode backend container not running, use disposable compose backend"
  exec "${compose[@]}" -f docker-compose.yml --profile postgres --profile prod run --rm backend sh -lc "cd /app && $command"
}

if [[ $# -eq 0 ]]; then
  set -- daily
fi

case "${1:-}" in
  -h|--help|help)
    show_help
    exit 0
    ;;
esac

COMMAND="$1"
shift || true

case "$COMMAND" in
  daily)
    PY_ARGS=(
      python
      backend/scripts/run_background_latest_trade_day_update.py
      --window-size "${WINDOW_SIZE:-120}"
      --reviewer "${REVIEWER:-quant}"
      --force
    )
    PY_ARGS+=("$@")
    run_backend_command "daily" "${PY_ARGS[@]}"
    ;;
  generate)
    PY_ARGS=(
      python
      backend/scripts/rebuild_recent_120_data.py
      --yes
      --skip-data-fetch
      --window-size "${WINDOW_SIZE:-120}"
      --warmup-trade-days "${WARMUP_TRADE_DAYS:-140}"
      --reviewer "${REVIEWER:-quant}"
      --diagnosis-scope "${DIAGNOSIS_SCOPE:-none}"
      --workers "${WORKERS:-auto}"
    )
    PY_ARGS+=("$@")
    run_backend_command "generate" "${PY_ARGS[@]}"
    ;;
  intraday)
    PY_ARGS=(
      python
      backend/scripts/generate_intraday_snapshots.py
      --cutoff-time "11:30:00"
    )
    PY_ARGS+=("$@")
    run_backend_command "intraday" "${PY_ARGS[@]}"
    ;;
  repair)
    REPAIR_KIND="${1:-}"
    if [[ -z "$REPAIR_KIND" ]]; then
      echo "repair 需要二级命令: daily 或 scores" >&2
      exit 1
    fi
    shift || true
    case "$REPAIR_KIND" in
      daily)
        PY_ARGS=(
          python
          backend/scripts/repair_incomplete_stock_daily.py
        )
        PY_ARGS+=("$@")
        run_backend_command "repair-daily" "${PY_ARGS[@]}"
        ;;
      scores)
        PY_ARGS=(
          python
          backend/scripts/repair_historical_scores.py
          --reviewer "${REVIEWER:-quant}"
        )
        PY_ARGS+=("$@")
        run_backend_command "repair-scores" "${PY_ARGS[@]}"
        ;;
      *)
        echo "未知 repair 子命令: $REPAIR_KIND" >&2
        echo "可用 repair 子命令: daily, scores" >&2
        exit 1
        ;;
    esac
    ;;
  *)
    echo "未知命令: $COMMAND" >&2
    echo "可用命令: repair, generate, daily, intraday" >&2
    exit 1
    ;;
esac
