#!/bin/bash
# StockTrader 数据备份脚本
# 负责 PostgreSQL 数据库和 data/ 目录的备份

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
StockTrader 数据备份脚本

用法:
  $0 [options]

选项:
  -d, --dir DIR       备份文件输出目录 (默认: ./backups)
  --no-db             跳过数据库备份
  --no-data           跳过 data/ 目录备份
  --keep-days N       保留最近 N 天的备份 (默认: 7)
  -h, --help          显示帮助信息

示例:
  $0                              # 备份数据库和 data/
  $0 -d /mnt/backup               # 备份到指定目录
  $0 --no-db                      # 仅备份 data/
  $0 --no-data                    # 仅备份数据库
  $0 --keep-days 30               # 备份并清理 30 天前的旧备份

备份目录结构:
  backups/
    YYYY-MM-DD/
      postgres.sql           # PostgreSQL 数据库备份
      data.tar.gz            # data/ 目录备份
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
}

# 加载环境变量
load_env() {
    if [ -f "$DEPLOY_DIR/.env" ]; then
        # 加载环境变量，只获取需要的变量
        eval "$(grep -E '^POSTGRES_(DB|USER|PASSWORD)=' "$DEPLOY_DIR/.env" | head -3)"
    fi

    # 设置默认值
    POSTGRES_DB="${POSTGRES_DB:-stocktrade}"
    POSTGRES_USER="${POSTGRES_USER:-stocktrade}"
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-stocktrade123}"
}

# 检查 PostgreSQL 容器是否运行
check_postgres() {
    if ! docker ps --format '{{.Names}}' | grep -q 'stocktrade-postgres'; then
        log_warning "PostgreSQL 容器未运行，跳过数据库备份"
        return 1
    fi
    return 0
}

# 备份 PostgreSQL
backup_postgres() {
    local backup_dir="$1"
    local backup_file="$backup_dir/postgres.sql"

    log_info "开始备份 PostgreSQL 数据库..."

    if ! check_postgres; then
        return 1
    fi

    # 使用 docker exec 执行 pg_dump
    if docker exec stocktrade-postgres pg_dump -U "$POSTGRES_USER" \
            --no-owner --no-acl --format=plain "$POSTGRES_DB" > "$backup_file" 2>/dev/null; then
        local size=$(du -h "$backup_file" | cut -f1)
        log_success "PostgreSQL 备份完成: $backup_file ($size)"
        return 0
    else
        log_error "PostgreSQL 备份失败"
        return 1
    fi
}

# 备份 data/ 目录
backup_data_dir() {
    local backup_dir="$1"
    local backup_file="$backup_dir/data.tar.gz"
    local data_dir="$PROJECT_ROOT/data"

    log_info "开始备份 data/ 目录..."

    if [ ! -d "$data_dir" ]; then
        log_warning "data/ 目录不存在，跳过"
        return 1
    fi

    # 检查目录是否为空
    if [ -z "$(ls -A "$data_dir" 2>/dev/null)" ]; then
        log_warning "data/ 目录为空，跳过备份"
        return 1
    fi

    # 打包 data/ 目录
    if tar -czf "$backup_file" -C "$PROJECT_ROOT" data 2>/dev/null; then
        local size=$(du -h "$backup_file" | cut -f1)
        log_success "data/ 备份完成: $backup_file ($size)"
        return 0
    else
        log_error "data/ 备份失败"
        return 1
    fi
}

# 清理旧备份
cleanup_old_backups() {
    local backup_dir="$1"
    local keep_days="$2"

    log_info "清理 $keep_days 天前的旧备份..."

    # 删除超过保留期的备份目录
    local old_backups=$(find "$backup_dir" -maxdepth 1 -type d -name "????-??-??" -mtime +$keep_days)
    if [ -n "$old_backups" ]; then
        echo "$old_backups" | while read -r old_dir; do
            log_info "删除旧备份: $old_dir"
            rm -rf "$old_dir"
        done
        log_success "旧备份清理完成"
    else
        log_info "没有需要清理的旧备份"
    fi
}

# 默认值
BACKUP_DIR="$DEPLOY_DIR/backups"
BACKUP_DB=1
BACKUP_DATA=1
KEEP_DAYS=7

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dir)
            BACKUP_DIR="$2"
            shift 2
            ;;
        --no-db)
            BACKUP_DB=0
            shift
            ;;
        --no-data)
            BACKUP_DATA=0
            shift
            ;;
        --keep-days)
            KEEP_DAYS="$2"
            shift 2
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

# 主流程
main() {
    echo ""
    log_info "=== StockTrader 数据备份 ==="
    echo ""

    check_docker
    load_env

    # 创建备份目录
    local today=$(date +%Y-%m-%d)
    local today_backup_dir="$BACKUP_DIR/$today"
    mkdir -p "$today_backup_dir"

    log_info "备份目录: $today_backup_dir"
    log_info "保留天数: $KEEP_DAYS 天"
    echo ""

    # 备份计数
    local success_count=0
    local total_count=0

    # 备份 PostgreSQL
    if [ "$BACKUP_DB" = "1" ]; then
        total_count=$((total_count + 1))
        if backup_postgres "$today_backup_dir"; then
            success_count=$((success_count + 1))
        fi
    else
        log_info "跳过数据库备份 (--no-db)"
    fi

    # 备份 data/ 目录
    if [ "$BACKUP_DATA" = "1" ]; then
        total_count=$((total_count + 1))
        if backup_data_dir "$today_backup_dir"; then
            success_count=$((success_count + 1))
        fi
    else
        log_info "跳过 data/ 备份 (--no-data)"
    fi

    echo ""

    # 清理旧备份
    if [ "$success_count" -gt 0 ]; then
        cleanup_old_backups "$BACKUP_DIR" "$KEEP_DAYS"
    fi

    # 总结
    if [ "$total_count" -eq 0 ]; then
        log_warning "没有执行任何备份"
        exit 0
    fi

    if [ "$success_count" -eq "$total_count" ]; then
        log_success "=== 所有备份完成 ($success_count/$total_count) ==="
        echo ""
        ls -lh "$today_backup_dir" 2>/dev/null || true
        exit 0
    else
        log_error "=== 部分备份失败 ($success_count/$total_count) ==="
        exit 1
    fi
}

main
