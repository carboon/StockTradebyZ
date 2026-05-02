#!/bin/bash
# PostgreSQL 数据一致性修复脚本
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
# 自动检测 PostgreSQL 连接方式并执行修复
#
# 使用方法：
#   ./scripts/fix_postgresql_sequences.sh

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 默认连接参数
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-stocktrade}"
POSTGRES_USER="${POSTGRES_USER:-stocktrade}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_FILE="$SCRIPT_DIR/fix_postgresql_sequences.sql"

echo -e "${YELLOW}======================================================${NC}"
echo -e "${YELLOW}PostgreSQL 数据一致性修复${NC}"
echo -e "${YELLOW}======================================================${NC}"
echo ""

# 检查 SQL 文件是否存在
if [ ! -f "$SQL_FILE" ]; then
    echo -e "${RED}错误: 找不到 SQL 文件: $SQL_FILE${NC}"
    exit 1
fi

# 检测是否在 Docker 环境中
if docker ps &>/dev/null; then
    # 尝试查找 PostgreSQL 容器
    PG_CONTAINER=$(docker ps --filter "name=postgres" --format "{{.Names}}" | head -n 1)

    if [ -n "$PG_CONTAINER" ]; then
        echo -e "${GREEN}检测到 PostgreSQL 容器: $PG_CONTAINER${NC}"
        echo ""
        echo "执行修复脚本..."
        echo ""

        # 将 SQL 文件复制到容器内并执行
        docker exec -i "$PG_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$SQL_FILE"

        echo ""
        echo -e "${GREEN}修复完成！${NC}"
        exit 0
    fi
fi

# 如果没有检测到 Docker 容器，尝试直接连接
echo -e "${YELLOW}未检测到 Docker PostgreSQL 容器，尝试直接连接...${NC}"
echo ""
echo "连接参数:"
echo "  Host: $POSTGRES_HOST"
echo "  Port: $POSTGRES_PORT"
echo "  Database: $POSTGRES_DB"
echo "  User: $POSTGRES_USER"
echo ""

# 执行 SQL
psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$SQL_FILE"

echo ""
echo -e "${GREEN}修复完成！${NC}"
