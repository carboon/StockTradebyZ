#!/bin/bash
# StockTrader 统一运行脚本
# 只负责 Docker 起停与观察，不负责生产发布

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"
DOCKER_CONFIG_DIR="$PROJECT_ROOT/.docker"
cd "$DEPLOY_DIR"

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
StockTrader 统一运行脚本
只负责 Docker 起停与观察，不负责生产发布

用法:
  $0 <command> [options]

命令:
  dev           启动开发环境 (docker-compose.yml + dev/postgres profiles)
  prod          启动生产环境 (docker-compose.yml + prod/postgres profiles)
  down          停止服务
  logs          查看日志 [服务名]
  ps            查看服务状态
  restart       重启服务
  exec-backend  进入后端容器

选项:
  --build       启动前构建镜像 (dev 默认启用，prod 需显式指定)
  --no-cache    构建时不使用缓存
  -v, --volumes down 时同时删除 volumes
  -h, --help    显示帮助信息

示例:
  $0 dev                    # 启动开发环境 (默认 --build)
  $0 dev --build            # 启动开发环境并构建
  $0 prod                   # 启动生产环境
  $0 prod --build           # 启动生产环境并构建
  $0 down                   # 停止服务
  $0 down -v                # 停止服务并删除 volumes
  $0 logs backend           # 查看 backend 日志
  $0 ps                     # 查看服务状态
  $0 restart                # 重启服务
  $0 exec-backend           # 进入后端容器

访问地址:
  开发环境:
    - 前端直连: http://127.0.0.1:5173 (frontend-dev)
    - 后端: http://127.0.0.1:8000

  生产环境:
    - 主入口: 由 deploy/.env 中 NGINX_PORT 决定，未设置时为 http://127.0.0.1
    - 后端: http://127.0.0.1:8000
EOF
}

# 检查 Docker
check_docker() {
    mkdir -p "$DOCKER_CONFIG_DIR"
    export DOCKER_CONFIG="$DOCKER_CONFIG_DIR"
    export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}"
    export COMPOSE_DOCKER_CLI_BUILD="${COMPOSE_DOCKER_CLI_BUILD:-1}"

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

# 检查环境变量
check_env() {
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            log_warning "未找到 deploy/.env，从 .env.example 复制..."
            cp "$PROJECT_ROOT/.env.example" "$DEPLOY_DIR/.env"
            log_warning "请编辑 deploy/.env 配置必要的环境变量"
        else
            log_warning "未找到 .env 文件，请确保环境变量已正确配置"
        fi
    fi
}

read_env_value() {
    local key="$1"
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        return 0
    fi
    grep -E "^${key}=" "$DEPLOY_DIR/.env" | tail -n 1 | cut -d= -f2-
}

validate_prod_env() {
    local environment_value
    environment_value="$(read_env_value "ENVIRONMENT" | tr -d '[:space:]')"
    if [ "$environment_value" != "production" ]; then
        log_error "生产启动要求 deploy/.env 中设置 ENVIRONMENT=production，当前为: ${environment_value:-未设置}"
        exit 1
    fi

    local database_url secret_key admin_password postgres_password
    database_url="$(read_env_value "DATABASE_URL" | tr -d '[:space:]')"
    secret_key="$(read_env_value "SECRET_KEY")"
    admin_password="$(read_env_value "ADMIN_DEFAULT_PASSWORD")"
    postgres_password="$(read_env_value "POSTGRES_PASSWORD")"

    if [ -z "$database_url" ] || [ "$database_url" = "postgresql://stocktrade:stocktrade123@postgres:5432/stocktrade" ]; then
        log_warning "当前使用默认 DATABASE_URL，适合本地生产模拟，不适合真实生产环境"
    fi

    if [ -z "$secret_key" ] || [ "$secret_key" = "change-me-in-production" ] || [ "$secret_key" = "change-me-in-production-use-a-random-string" ]; then
        log_warning "当前使用示例 SECRET_KEY，适合本地生产模拟，不适合真实生产环境"
    fi

    if [ -z "$admin_password" ] || [ "$admin_password" = "admin123" ]; then
        log_warning "当前使用默认管理员密码，适合本地生产模拟，不适合真实生产环境"
    fi

    if [ -z "$postgres_password" ] || [ "$postgres_password" = "stocktrade123" ]; then
        log_warning "当前使用默认 PostgreSQL 密码，适合本地生产模拟，不适合真实生产环境"
    fi
}

# 获取 compose 命令参数
get_compose_args() {
    local mode="$1"
    local args=(-f docker-compose.yml --profile postgres)

    if [ "$mode" = "prod" ] && use_prod_nobind_override; then
        args=(-f docker-compose.yml -f docker-compose.prod-nobind.yml --profile postgres)
    fi

    case "$mode" in
        dev)
            args+=(--profile dev)
            ;;
        prod)
            args+=(--profile prod)
            ;;
        *)
            log_error "未知模式: $mode"
            exit 1
            ;;
    esac

    echo "${args[*]}"
}

use_prod_nobind_override() {
    if [ "${STOCKTRADE_PROD_NOBIND:-}" = "0" ]; then
        return 1
    fi
    if [ "${STOCKTRADE_PROD_NOBIND:-}" = "1" ]; then
        return 0
    fi

    case "$PROJECT_ROOT" in
        /Volumes/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

compose_run() {
    local mode="$1"
    shift
    "${DOCKER_COMPOSE[@]}" $(get_compose_args "$mode") "$@"
}

append_unique_service() {
    local service="$1"
    case " ${BUILD_TARGETS[*]} " in
        *" ${service} "*) ;;
        *) BUILD_TARGETS+=("$service") ;;
    esac
}

get_build_targets() {
    local mode="$1"
    BUILD_TARGETS=()

    if [ ${#TARGETS[@]} -eq 0 ]; then
        case "$mode" in
            dev)
                BUILD_TARGETS=(backend frontend-dev)
                ;;
            prod)
                BUILD_TARGETS=(backend nginx)
                ;;
        esac
        return 0
    fi

    local target
    for target in "${TARGETS[@]}"; do
        case "$mode:$target" in
            dev:backend|prod:backend)
                append_unique_service backend
                ;;
            dev:frontend-dev)
                append_unique_service frontend-dev
                ;;
            prod:nginx)
                # nginx 依赖 backend，顺序构建可规避当前 Docker/BuildKit 并行导出异常。
                append_unique_service backend
                append_unique_service nginx
                ;;
        esac
    done
}

build_mode_images() {
    local mode="$1"
    get_build_targets "$mode"

    if [ ${#BUILD_TARGETS[@]} -eq 0 ]; then
        return 0
    fi

    log_info "顺序构建镜像，规避当前 Docker/BuildKit 并行导出异常..."

    local service
    for service in "${BUILD_TARGETS[@]}"; do
        log_info "构建镜像: $service"
        local build_args=("${DOCKER_COMPOSE[@]}" $(get_compose_args "$mode") build)
        if [ "$NO_CACHE" = "1" ]; then
            build_args+=(--no-cache)
        fi
        build_args+=("$service")
        "${build_args[@]}"
    done
}

# 检测当前运行模式
detect_mode() {
    if docker ps --format '{{.Names}}' | grep -q '^stocktrade-nginx$'; then
        echo "prod"
    else
        echo "dev"  # 默认
    fi
}

# 启动开发环境
cmd_dev() {
    log_info "启动开发环境..."

    if [ "$NO_CACHE" = "1" ] || [ "$BUILD" = "1" ]; then
        build_mode_images dev
    fi

    local up_args=("${DOCKER_COMPOSE[@]}" $(get_compose_args dev) up -d)
    if [ ${#TARGETS[@]} -gt 0 ]; then
        up_args+=("${TARGETS[@]}")
    fi

    "${up_args[@]}"

    echo ""
    log_success "开发环境已启动"
    echo ""
    echo -e "  ${GREEN}前端直连 (frontend-dev):${NC}  http://127.0.0.1:5173"
    echo -e "  ${GREEN}后端 API:${NC}                http://127.0.0.1:8000"
    echo -e "  ${GREEN}API 文档:${NC}                http://127.0.0.1:8000/docs"
    echo ""

    compose_run dev ps
}

# 启动生产环境
cmd_prod() {
    log_info "启动生产环境..."
    if use_prod_nobind_override; then
        log_warning "检测到外部磁盘路径，启用生产无 bind mount 覆盖，运行数据将保存在 Docker volume: deploy_stocktrade_data"
    fi

    if [ "$NO_CACHE" = "1" ] || [ "$BUILD" = "1" ]; then
        build_mode_images prod
    fi

    local up_args=("${DOCKER_COMPOSE[@]}" $(get_compose_args prod) up -d)
    if [ ${#TARGETS[@]} -gt 0 ]; then
        up_args+=("${TARGETS[@]}")
    fi

    "${up_args[@]}"

    echo ""
    log_success "生产环境已启动"
    echo ""
    echo -e "  ${GREEN}主入口 (nginx):${NC}  由 deploy/.env 中 NGINX_PORT 决定，未设置时为 http://127.0.0.1"
    echo -e "  ${GREEN}后端 API:${NC}       http://127.0.0.1:8000"
    echo -e "  ${GREEN}API 文档:${NC}       http://127.0.0.1:8000/docs"
    echo ""

    compose_run prod ps
}

# 停止服务
cmd_down() {
    local mode=$(detect_mode)
    log_info "停止服务 (模式: $mode)..."

    local down_args=("${DOCKER_COMPOSE[@]}" $(get_compose_args $mode) down)
    if [ "$REMOVE_VOLUMES" = "1" ]; then
        down_args+=(-v)
    fi

    "${down_args[@]}"
    log_success "服务已停止"
}

# 查看日志
cmd_logs() {
    local mode=$(detect_mode)
    if [ ${#TARGETS[@]} -gt 0 ]; then
        compose_run "$mode" logs -f "${TARGETS[@]}"
    else
        compose_run "$mode" logs -f
    fi
}

# 查看服务状态
cmd_ps() {
    local mode=$(detect_mode)
    compose_run "$mode" ps
}

# 重启服务
cmd_restart() {
    local mode=$(detect_mode)
    log_info "重启服务 (模式: $mode)..."

    local restart_args=("${DOCKER_COMPOSE[@]}" $(get_compose_args $mode) restart)
    if [ ${#TARGETS[@]} -gt 0 ]; then
        restart_args+=("${TARGETS[@]}")
    fi

    "${restart_args[@]}"
    log_success "服务已重启"
    compose_run "$mode" ps
}

# 进入后端容器
cmd_exec_backend() {
    local mode=$(detect_mode)
    log_info "进入后端容器 (模式: $mode)..."
    exec "${DOCKER_COMPOSE[@]}" $(get_compose_args "$mode") exec backend bash
}

# 默认值
COMMAND=""
BUILD="0"
NO_CACHE="0"
REMOVE_VOLUMES="0"
TARGETS=()

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        dev|prod|down|logs|ps|restart|exec-backend)
            COMMAND="$1"
            shift
            ;;
        --)
            shift
            while [[ $# -gt 0 ]]; do
                TARGETS+=("$1")
                shift
            done
            ;;
        --build)
            BUILD="1"
            shift
            ;;
        --no-cache)
            NO_CACHE="1"
            shift
            ;;
        -v|--volumes)
            REMOVE_VOLUMES="1"
            shift
            ;;
        -h|--help|help)
            show_help
            exit 0
            ;;
        -*)
            log_error "未知选项: $1"
            show_help
            exit 1
            ;;
        *)
            TARGETS+=("$1")
            shift
            ;;
    esac
done

# 如果没有指定命令，显示帮助
if [ -z "$COMMAND" ]; then
    show_help
    exit 0
fi

# 执行命令
check_docker

case "$COMMAND" in
    dev)
        check_env
        # dev 默认 --build
        if [ "$BUILD" = "0" ] && [ "$NO_CACHE" = "0" ]; then
            BUILD="1"
        fi
        cmd_dev
        ;;
    prod)
        check_env
        validate_prod_env
        cmd_prod
        ;;
    down)
        cmd_down
        ;;
    logs)
        cmd_logs
        ;;
    ps)
        cmd_ps
        ;;
    restart)
        cmd_restart
        ;;
    exec-backend)
        cmd_exec_backend
        ;;
    *)
        log_error "未知命令: $COMMAND"
        show_help
        exit 1
        ;;
esac
