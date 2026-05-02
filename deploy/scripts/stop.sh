#!/bin/bash
# StockTrader 停止脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"
cd "$DEPLOY_DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

show_help() {
    cat << EOF
StockTrader 停止脚本

用法:
  $0 [选项]

选项:
  --prod            按生产模式关闭
  --postgres        同时作用于 PostgreSQL profile
  --volumes         删除 volumes
  --remove-orphans  删除孤儿容器
  -h, --help        显示帮助

示例:
  $0
  $0 --postgres
  $0 --volumes --remove-orphans
EOF
}

if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker-compose)
else
    echo -e "${RED}✗ 未找到 docker compose / docker-compose${NC}"
    exit 1
fi

RUN_MODE="dev"
USE_POSTGRES_PROFILE="0"
REMOVE_VOLUMES="0"
REMOVE_ORPHANS="0"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --prod)
            RUN_MODE="prod"
            shift
            ;;
        --postgres)
            USE_POSTGRES_PROFILE="1"
            shift
            ;;
        --volumes)
            REMOVE_VOLUMES="1"
            shift
            ;;
        --remove-orphans)
            REMOVE_ORPHANS="1"
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}✗ 未知参数: $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

PROFILES=()
if [ "$RUN_MODE" = "dev" ]; then
    PROFILES+=(--profile dev)
else
    PROFILES+=(--profile prod)
fi
if [ "$USE_POSTGRES_PROFILE" = "1" ]; then
    PROFILES+=(--profile postgres)
fi

DOWN_ARGS=(down)
if [ "$REMOVE_VOLUMES" = "1" ]; then
    DOWN_ARGS+=(-v)
fi
if [ "$REMOVE_ORPHANS" = "1" ]; then
    DOWN_ARGS+=(--remove-orphans)
fi

echo -e "${GREEN}🛑 停止服务...${NC}"
if [ "$RUN_MODE" = "prod" ]; then
    MODE=prod MOUNT_DISABLED=-disabled "${DOCKER_COMPOSE[@]}" "${PROFILES[@]}" "${DOWN_ARGS[@]}"
else
    MODE=dev "${DOCKER_COMPOSE[@]}" "${PROFILES[@]}" "${DOWN_ARGS[@]}"
fi
echo -e "${GREEN}✓ 服务已停止${NC}"
