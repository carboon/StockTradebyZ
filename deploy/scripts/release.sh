#!/bin/bash
# StockTrader 生产环境发布脚本
# 职责：
# - 生产环境构建与上线
# - 构建 backend 镜像
# - 构建 nginx 镜像（包含前端 dist）
# - 启动 postgres + backend + nginx
# - 健康检查

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_DIR="$PROJECT_ROOT/deploy"
DOCKER_CONFIG_DIR="$PROJECT_ROOT/.docker"
BENCH_STAMP="$(date +%Y%m%d-%H%M%S)"
BENCH_DIR=""
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

collect_release_snapshot() {
    if [ "$DRY_RUN" = "1" ]; then
        return
    fi
    BENCH_DIR="$("$SCRIPT_DIR/release-bench.sh" "$BENCH_STAMP")"
}

# 显示帮助信息
show_help() {
    cat << EOF
StockTrader 生产环境发布脚本

用法:
  $0 [options]

选项:
  --skip-pull       跳过 git pull
  --no-cache        构建时不使用缓存
  --dry-run         仅显示将要执行的命令，不实际执行
  -h, --help        显示帮助信息

示例:
  $0                # 完整发布流程
  $0 --skip-pull    # 跳过 git pull，直接构建部署
  $0 --no-cache     # 不使用缓存构建

访问地址:
  - 主入口: http://127.0.0.1 (nginx)
  - 后端 API: http://127.0.0.1:8000
  - API 文档: http://127.0.0.1:8000/docs
EOF
}

# 检查 Docker
check_docker() {
    mkdir -p "$DOCKER_CONFIG_DIR"
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

# 检查环境变量
check_env() {
    if [ ! -f "$DEPLOY_DIR/.env" ]; then
        if [ -f "$PROJECT_ROOT/.env.example" ]; then
            log_warning "未找到 deploy/.env，从 .env.example 复制..."
            cp "$PROJECT_ROOT/.env.example" "$DEPLOY_DIR/.env"
            log_error "请先编辑 deploy/.env 配置必要的环境变量（特别是 TUSHARE_TOKEN）"
            exit 1
        else
            log_error "未找到 .env 文件，请确保环境变量已正确配置"
            exit 1
        fi
    fi

    # 检查关键配置
    if grep -q "^TUSHARE_TOKEN=.*$" "$DEPLOY_DIR/.env" && grep -q "^TUSHARE_TOKEN=$" "$DEPLOY_DIR/.env"; then
        log_error "TUSHARE_TOKEN 未设置，请在 deploy/.env 中配置"
        exit 1
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
        log_error "生产发布要求 deploy/.env 中设置 ENVIRONMENT=production，当前为: ${environment_value:-未设置}"
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

# Git pull 更新代码
git_pull() {
    if [ "$SKIP_PULL" = "1" ]; then
        log_warning "跳过 git pull"
        return
    fi

    log_info "更新代码..."
    cd "$PROJECT_ROOT"
    git pull
    cd "$DEPLOY_DIR"
    log_success "代码已更新"
}

# 构建镜像
build_images() {
    log_info "构建生产环境镜像..."
    local build_started_at
    build_started_at=$(date +%s)

    local services=(backend nginx)
    local service
    for service in "${services[@]}"; do
        local build_cmd=("${DOCKER_COMPOSE[@]}" -f docker-compose.yml --profile postgres --profile prod build)
        if [ "$NO_CACHE" = "1" ]; then
            build_cmd+=(--no-cache)
        fi
        build_cmd+=("$service")

        if [ "$DRY_RUN" = "1" ]; then
            echo -e "${YELLOW}[DRY RUN]${NC} ${build_cmd[*]}"
            continue
        fi

        log_info "构建镜像: $service"
        "${build_cmd[@]}"
    done

    if [ "$DRY_RUN" = "0" ]; then
        echo "build_seconds=$(( $(date +%s) - build_started_at ))" >> "$BENCH_DIR/summary.env"
        log_success "镜像构建完成"
    fi
}

# 启动服务
start_services() {
    log_info "启动生产环境服务..."
    local started_at
    started_at=$(date +%s)

    local up_cmd=("${DOCKER_COMPOSE[@]}" -f docker-compose.yml --profile postgres --profile prod up -d)

    if [ "$DRY_RUN" = "1" ]; then
        echo -e "${YELLOW}[DRY RUN]${NC} ${up_cmd[*]}"
    else
        "${up_cmd[@]}"
        echo "startup_seconds=$(( $(date +%s) - started_at ))" >> "$BENCH_DIR/summary.env"
        log_success "服务已启动"
    fi
}

# 查看服务状态
show_status() {
    log_info "服务状态:"
    "${DOCKER_COMPOSE[@]}" -f docker-compose.yml --profile postgres --profile prod ps
}

# 健康检查
health_check() {
    if [ "$DRY_RUN" = "1" ]; then
        log_warning "DRY RUN 模式，跳过健康检查"
        return
    fi

    log_info "执行健康检查..."
    local health_started_at
    health_started_at=$(date +%s)

    # 等待服务启动
    local max_wait=60
    local waited=0
    local backend_healthy=false
    local nginx_healthy=false

    while [ $waited -lt $max_wait ]; do
        # 检查后端
        if [ "$backend_healthy" = false ]; then
            if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
                backend_healthy=true
                log_success "后端健康检查通过"
            fi
        fi

        # 检查 nginx
        if [ "$nginx_healthy" = false ]; then
            if curl -sf http://127.0.0.1/health >/dev/null 2>&1; then
                nginx_healthy=true
                log_success "Nginx 健康检查通过"
            fi
        fi

        if [ "$backend_healthy" = true ] && [ "$nginx_healthy" = true ]; then
            break
        fi

        sleep 2
        waited=$((waited + 2))
        echo -n "."
    done
    echo ""
    echo "healthcheck_seconds=$(( $(date +%s) - health_started_at ))" >> "$BENCH_DIR/summary.env"

    # 最终检查
    if [ "$backend_healthy" = false ]; then
        log_error "后端健康检查失败"
        log_info "查看日志: $0 logs backend"
        exit 1
    fi

    if [ "$nginx_healthy" = false ]; then
        log_error "Nginx 健康检查失败"
        log_info "查看日志: $0 logs nginx"
        exit 1
    fi

    echo ""
    log_success "所有服务健康检查通过"
    echo ""
    echo -e "  ${GREEN}主入口 (nginx):${NC}    http://127.0.0.1"
    echo -e "  ${GREEN}后端 API:${NC}         http://127.0.0.1:8000"
    echo -e "  ${GREEN}API 文档:${NC}         http://127.0.0.1:8000/docs"
    echo ""
}

# 显示发布后提示
show_post_release_info() {
    cat << EOF

${GREEN}========================================${NC}
${GREEN}  生产环境发布成功！${NC}
${GREEN}========================================${NC}

常用命令:
  查看日志:   $SCRIPT_DIR/start.sh logs [服务名]
  查看状态:   $SCRIPT_DIR/start.sh ps
  停止服务:   $SCRIPT_DIR/start.sh down
  重启服务:   $SCRIPT_DIR/start.sh restart

重要提示:
  - 生产环境数据持久化在 ./data 目录
  - PostgreSQL 数据在 postgres_data volume 中
  - 建议定期备份: $SCRIPT_DIR/backup.sh
  - 发布资源快照: ${BENCH_DIR:-未采集}

EOF
}

# 默认值
SKIP_PULL="0"
NO_CACHE="0"
DRY_RUN="0"

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-pull)
            SKIP_PULL="1"
            shift
            ;;
        --no-cache)
            NO_CACHE="1"
            shift
            ;;
        --dry-run)
            DRY_RUN="1"
            shift
            ;;
        -h|--help|help)
            show_help
            exit 0
            ;;
        *)
            log_error "未知选项: $1"
            show_help
            exit 1
            ;;
    esac
done

# 执行发布流程
log_info "开始生产环境发布..."
echo ""

check_docker
check_env
validate_prod_env
collect_release_snapshot
git_pull
build_images
start_services
show_status
health_check
show_post_release_info

log_success "发布完成！"
