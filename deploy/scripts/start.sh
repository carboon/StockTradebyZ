#!/bin/bash
# StockTrader 统一 Docker 启动脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"
cd "$DEPLOY_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

show_help() {
    cat << EOF
StockTrader 统一 Docker 启动脚本

用法:
  $0 [dev|prod] [选项] [服务...]
  $0 build [选项] [服务...]
  $0 down [选项]
  $0 logs [服务]
  $0 shell
  $0 test
  $0 status

命令:
  dev         启动开发环境 (默认)
  prod        启动生产环境 (Nginx + 静态文件)
  build       构建镜像，可指定服务
  down        停止并删除容器
  logs        查看日志
  shell       进入后端容器
  test        在后端容器运行 pytest
  status      查看容器状态

选项:
  --build           启动前先构建镜像
  --no-cache        构建时不使用缓存
  --postgres        同时启用 PostgreSQL profile
  --volumes         down 时删除 volumes
  --remove-orphans  down 时删除孤儿容器
  -h, --help        显示帮助

示例:
  $0 dev
  $0 dev --build
  $0 dev --build --postgres backend
  $0 prod --build --no-cache
  $0 build --postgres backend frontend-dev
  $0 down --volumes --remove-orphans
EOF
}

check_docker() {
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

check_env() {
    if [ -f "$DEPLOY_DIR/.env" ]; then
        return
    fi

    if [ -f "$PROJECT_ROOT/.env" ]; then
        log_warning "未找到 deploy/.env，当前 compose 将依赖项目根目录中的环境变量"
        return
    fi

    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        log_warning "未找到 .env 文件，从 .env.example 复制到 deploy/.env ..."
        cp "$PROJECT_ROOT/.env.example" "$DEPLOY_DIR/.env"
        log_warning "请编辑 deploy/.env，至少配置 TUSHARE_TOKEN"
        echo ""
        read -r -p "按 Enter 继续 (确保已配置 deploy/.env)..."
        return
    fi

    log_warning "未找到 deploy/.env，请确认运行环境变量已正确配置"
}

compose_profiles() {
    local mode="$1"

    COMPOSE_PROFILES=()
    if [ "$mode" = "dev" ]; then
        COMPOSE_PROFILES+=(--profile dev)
    elif [ "$mode" = "prod" ]; then
        COMPOSE_PROFILES+=(--profile prod)
    fi

    if [ "$USE_POSTGRES_PROFILE" = "1" ]; then
        COMPOSE_PROFILES+=(--profile postgres)
    fi
}

run_compose() {
    local mode="$1"
    shift

    compose_profiles "$mode"

    if [ "$mode" = "prod" ]; then
        MODE=prod MOUNT_DISABLED=-disabled "${DOCKER_COMPOSE[@]}" "${COMPOSE_PROFILES[@]}" "$@"
    elif [ "$mode" = "dev" ]; then
        MODE=dev "${DOCKER_COMPOSE[@]}" "${COMPOSE_PROFILES[@]}" "$@"
    else
        "${DOCKER_COMPOSE[@]}" "${COMPOSE_PROFILES[@]}" "$@"
    fi
}

cmd_dev() {
    log_info "启动开发环境..."
    local up_args=(up -d)
    if [ "$BUILD_IMAGES" = "1" ]; then
        up_args+=(--build)
    fi
    if [ "$NO_CACHE" = "1" ]; then
        up_args+=(--no-cache)
    fi
    up_args+=("${TARGETS[@]}")

    run_compose dev "${up_args[@]}"
    echo ""
    log_success "开发环境已启动"
    echo -e "  ${GREEN}后端:${NC} http://localhost:8000"
    echo -e "  ${GREEN}前端:${NC} http://localhost:5173"
    echo -e "  ${GREEN}API 文档:${NC} http://localhost:8000/docs"
    echo ""
    run_compose dev ps
}

cmd_prod() {
    log_info "启动生产环境..."
    local up_args=(up -d)
    if [ "$BUILD_IMAGES" = "1" ]; then
        up_args+=(--build)
    fi
    if [ "$NO_CACHE" = "1" ]; then
        up_args+=(--no-cache)
    fi
    up_args+=("${TARGETS[@]}")

    run_compose prod "${up_args[@]}"
    echo ""
    log_success "生产环境已启动"
    echo -e "  ${GREEN}应用:${NC} http://localhost:80"
    echo -e "  ${GREEN}API 文档:${NC} http://localhost:80/api/docs"
    echo ""
    run_compose prod ps
}

cmd_build() {
    log_info "构建镜像..."
    local build_args=(build)
    if [ "$NO_CACHE" = "1" ]; then
        build_args+=(--no-cache)
    fi
    build_args+=("${TARGETS[@]}")

    run_compose "$BUILD_MODE" "${build_args[@]}"
    log_success "镜像构建完成"
}

cmd_down() {
    log_info "停止服务..."
    local down_args=(down)
    if [ "$REMOVE_VOLUMES" = "1" ]; then
        down_args+=(-v)
    fi
    if [ "$REMOVE_ORPHANS" = "1" ]; then
        down_args+=(--remove-orphans)
    fi

    run_compose "$RUN_MODE" "${down_args[@]}"
    log_success "服务已停止"
}

cmd_logs() {
    run_compose "$RUN_MODE" logs -f "${TARGETS[@]}"
}

cmd_shell() {
    log_info "进入后端容器..."
    run_compose "$RUN_MODE" exec backend bash
}

cmd_test() {
    log_info "运行测试..."
    run_compose "$RUN_MODE" exec backend pytest backend/tests/ -v
}

cmd_status() {
    run_compose "$RUN_MODE" ps
}

COMMAND=""
RUN_MODE="dev"
BUILD_MODE="dev"
BUILD_IMAGES="0"
NO_CACHE="0"
USE_POSTGRES_PROFILE="0"
REMOVE_VOLUMES="0"
REMOVE_ORPHANS="0"
TARGETS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        dev|prod|build|down|logs|shell|test|status|help|--help|-h)
            COMMAND="$1"
            if [ "$1" = "prod" ]; then
                RUN_MODE="prod"
                BUILD_MODE="prod"
            fi
            shift
            ;;
        --build)
            BUILD_IMAGES="1"
            shift
            ;;
        --no-cache)
            NO_CACHE="1"
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
        *)
            TARGETS+=("$1")
            shift
            ;;
    esac
done

check_docker

case "$COMMAND" in
    dev|"")
        check_env
        cmd_dev
        ;;
    prod)
        check_env
        cmd_prod
        ;;
    build)
        if [ "$RUN_MODE" = "dev" ] && [ "$USE_POSTGRES_PROFILE" = "0" ]; then
            BUILD_MODE="dev"
        fi
        cmd_build
        ;;
    down)
        cmd_down
        ;;
    logs)
        cmd_logs
        ;;
    shell)
        cmd_shell
        ;;
    test)
        cmd_test
        ;;
    status)
        cmd_status
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        log_error "未知命令: $COMMAND"
        show_help
        exit 1
        ;;
esac
