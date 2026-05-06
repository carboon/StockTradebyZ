#!/bin/bash
# 重置本地生产模拟环境

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
START_SCRIPT="$SCRIPT_DIR/start.sh"

KEEP_LOGS="0"
KEEP_CACHE="0"

show_help() {
    cat << EOF
本地生产环境重置脚本

用法:
  $0 [options]

选项:
  --keep-logs     保留 data/logs
  --keep-cache    保留 data/tushare_cache
  -h, --help      显示帮助信息
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --keep-logs)
            KEEP_LOGS="1"
            shift
            ;;
        --keep-cache)
            KEEP_CACHE="1"
            shift
            ;;
        -h|--help|help)
            show_help
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

"$START_SCRIPT" down -v

# 兼容历史残留容器或混合模式场景，强制清理已知服务容器。
LEGACY_CONTAINERS=(
    stocktrade-nginx
    stocktrade-nginx-dev
    stocktrade-frontend-dev
    stocktrade-backend
    stocktrade-postgres
)

for container in "${LEGACY_CONTAINERS[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -qx "$container"; then
        docker rm -f "$container" >/dev/null 2>&1 || true
    fi
done

TARGETS=(
    "$PROJECT_ROOT/data/.disable_tomorrow_star_bootstrap"
    "$PROJECT_ROOT/data/raw"
    "$PROJECT_ROOT/data/candidates"
    "$PROJECT_ROOT/data/review"
    "$PROJECT_ROOT/data/kline"
    "$PROJECT_ROOT/data/run"
)

if [ "$KEEP_LOGS" != "1" ]; then
    TARGETS+=("$PROJECT_ROOT/data/logs")
fi

if [ "$KEEP_CACHE" != "1" ]; then
    TARGETS+=("$PROJECT_ROOT/data/tushare_cache")
fi

for target in "${TARGETS[@]}"; do
    rm -rf "$target"
done

mkdir -p \
    "$PROJECT_ROOT/data/raw" \
    "$PROJECT_ROOT/data/candidates" \
    "$PROJECT_ROOT/data/review" \
    "$PROJECT_ROOT/data/kline" \
    "$PROJECT_ROOT/data/run" \
    "$PROJECT_ROOT/data/logs" \
    "$PROJECT_ROOT/data/tushare_cache"

echo "本地生产模拟环境已重置。"
