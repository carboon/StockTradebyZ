#!/bin/bash
# SQLite 数据库恢复脚本
# 用法: ./restore.sh [备份文件路径]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="$PROJECT_ROOT/data/db/stocktrade.db"
BACKUP_DIR="$PROJECT_ROOT/data/backups"

# 确定要恢复的备份文件
if [ $# -eq 1 ]; then
    RESTORE_FILE="$1"
elif [ $# -eq 0 ]; then
    # 无参数时使用最新备份
    RESTORE_FILE=$(ls -1t "$BACKUP_DIR"/stocktrade_*.db 2>/dev/null | head -1)
    if [ -z "$RESTORE_FILE" ]; then
        echo "错误: 未找到备份文件"
        exit 1
    fi
else
    echo "用法: $0 [备份文件路径]"
    exit 1
fi

# 检查备份文件
if [ ! -f "$RESTORE_FILE" ]; then
    echo "错误: 备份文件不存在: $RESTORE_FILE"
    exit 1
fi

echo "即将恢复数据库:"
echo "  备份文件: $RESTORE_FILE"
echo "  目标数据库: $DB_PATH"
echo ""
read -p "确认恢复？(y/N) " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "已取消"
    exit 0
fi

# 备份当前数据库（如果存在）
if [ -f "$DB_PATH" ]; then
    PRE_RESTORE_BACKUP="$BACKUP_DIR/pre_restore_$(date +%Y%m%d_%H%M%S).db"
    mkdir -p "$BACKUP_DIR"
    cp "$DB_PATH" "$PRE_RESTORE_BACKUP"
    echo "已备份当前数据库到: $PRE_RESTORE_BACKUP"
fi

# 恢复
cp "$RESTORE_FILE" "$DB_PATH"
echo "恢复完成: $(du -h "$DB_PATH" | cut -f1)"
