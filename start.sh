#!/bin/bash
# StockTrader 本地开发启动入口
# 默认启动 dev-like-prod 环境

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 颜色输出
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

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 显示帮助信息
show_help() {
    cat << EOF
StockTrader 本地开发启动脚本

默认启动 dev-like-prod 环境 (Docker)

用法:
  $0 [options] [args...]

选项:
  --no-build      跳过镜像构建
  --no-cache      构建时不使用缓存
  -h, --help      显示帮助信息

说明:
  此脚本是根目录的快捷启动入口，默认调用:
    ./deploy/scripts/start.sh dev --build

  如需更多控制 (如启动生产环境、查看日志等)，请直接使用:
    ./deploy/scripts/start.sh

示例:
  $0                  # 启动开发环境 (默认构建)
  $0 --no-build       # 启动开发环境 (不构建)

访问地址:
  - 主入口:   http://127.0.0.1:8080
  - 前端直连: http://127.0.0.1:5173
  - 后端 API: http://127.0.0.1:8000
  - API 文档: http://127.0.0.1:8000/docs
EOF
}

# 解析参数
BUILD_ARG="--build"
NO_CACHE_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-build)
            BUILD_ARG=""
            shift
            ;;
        --no-cache)
            NO_CACHE_ARG="--no-cache"
            shift
            ;;
        -h|--help|help)
            show_help
            exit 0
            ;;
        *)
            log_error "未知参数: $1"
            show_help
            exit 1
            ;;
    esac
done

# 检查 Docker
if ! command -v docker >/dev/null 2>&1; then
    log_error "未找到 Docker，请先安装 Docker"
    exit 1
fi

# 检查 compose 子命令
if docker compose version >/dev/null 2>&1; then
    : # OK
elif command -v docker-compose >/dev/null 2>&1; then
    : # OK
else
    log_error "未找到 docker compose / docker-compose"
    exit 1
fi

# 检查部署脚本
if [ ! -f "$SCRIPT_DIR/deploy/scripts/start.sh" ]; then
    log_error "未找到部署脚本: deploy/scripts/start.sh"
    exit 1
fi

log_info "启动 dev-like-prod 环境..."

# 调用部署脚本
exec "$SCRIPT_DIR/deploy/scripts/start.sh" dev $BUILD_ARG $NO_CACHE_ARG
