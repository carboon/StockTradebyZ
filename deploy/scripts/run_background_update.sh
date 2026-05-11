#!/bin/bash
# 在 backend 容器内执行最新交易日后台更新

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"
DOCKER_CONFIG_DIR="$PROJECT_ROOT/.docker"
LOG_DIR="$PROJECT_ROOT/data/logs"
RUN_DIR="$PROJECT_ROOT/data/run"

cd "$DEPLOY_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

prepare_runtime_dirs() {
    mkdir -p "$DOCKER_CONFIG_DIR" "$LOG_DIR" "$RUN_DIR"
}

require_legacy_opt_in() {
    if [ "${STOCKTRADE_ENABLE_LEGACY_ONLINE_UPDATE:-0}" = "1" ]; then
        return 0
    fi
    log_error "在线 update-latest 入口默认已禁用，避免服务对外期间执行重负载更新导致机器卡死。"
    log_error "请改用仓库根目录 maintenance.sh 执行停服维护更新。"
    log_error "仅在明确接受风险时，才可临时设置 STOCKTRADE_ENABLE_LEGACY_ONLINE_UPDATE=1 后继续使用本脚本。"
    exit 1
}

check_docker() {
    export DOCKER_CONFIG="$DOCKER_CONFIG_DIR"

    if ! command -v docker >/dev/null 2>&1; then
        log_error "未找到 Docker，请先安装 Docker"
        exit 1
    fi

    if docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        DOCKER_COMPOSE=(docker-compose)
    else
        log_error "未找到 docker compose / docker-compose"
        exit 1
    fi
}

detect_mode() {
    if docker ps --format '{{.Names}}' | grep -q '^stocktrade-nginx$'; then
        echo "prod"
    elif docker ps --format '{{.Names}}' | grep -q '^stocktrade-nginx-dev$'; then
        echo "dev"
    else
        echo ""
    fi
}

get_compose_args() {
    local mode="$1"
    local args=(-f docker-compose.yml --profile postgres)
    case "$mode" in
        dev)
            args+=(--profile dev)
            ;;
        prod)
            args+=(--profile prod)
            ;;
        *)
            log_error "无法识别当前运行模式，请先用 ./start.sh 或 ./deploy/scripts/start.sh 启动服务"
            exit 1
            ;;
    esac
    echo "${args[*]}"
}

check_backend_running() {
    if ! docker ps --format '{{.Names}}' | grep -q '^stocktrade-backend$'; then
        log_error "backend 容器未运行，请先启动 Docker 服务"
        exit 1
    fi
}

main() {
    prepare_runtime_dirs
    require_legacy_opt_in
    check_docker
    check_backend_running

    local mode
    mode="$(detect_mode)"
    if [ -z "$mode" ]; then
        log_error "未检测到运行中的 dev/prod 环境，请先启动服务"
        exit 1
    fi

    log_info "在 backend 容器内执行最新交易日后台更新 (模式: $mode)"
    "${DOCKER_COMPOSE[@]}" $(get_compose_args "$mode") exec -T backend \
        python backend/scripts/run_background_latest_trade_day_update.py "$@"
    log_success "后台更新脚本执行完成"
}

main "$@"
