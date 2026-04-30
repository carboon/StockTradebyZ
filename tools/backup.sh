#!/bin/bash
# SQLite 数据库备份脚本
# 使用 sqlite3 .backup 命令进行一致性备份
# 保留最近 7 份备份

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="$PROJECT_ROOT/data/db/stocktrade.db"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
KEEP_COUNT=7

# 检查数据库文件
if [ ! -f "$DB_PATH" ]; then
    echo "错误: 数据库文件不存在: $DB_PATH"
    exit 1
fi

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 生成备份文件名
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/stocktrade_$TIMESTAMP.db"

# 执行一致性备份
echo "开始备份: $DB_PATH -> $BACKUP_FILE"
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

if [ $? -eq 0 ]; then
    BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "备份成功: $BACKUP_FILE ($BACKUP_SIZE)"
else
    echo "备份失败!"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 清理旧备份，保留最近 N 份
TOTAL=$(ls -1t "$BACKUP_DIR"/stocktrade_*.db 2>/dev/null | wc -l)
if [ "$TOTAL" -gt "$KEEP_COUNT" ]; then
    echo "清理旧备份 (保留最近 $KEEP_COUNT 份)..."
    ls -1t "$BACKUP_DIR"/stocktrade_*.db | tail -n +$((KEEP_COUNT + 1)) | xargs rm -f
fi

echo "备份完成。当前备份数: $(ls -1 "$BACKUP_DIR"/stocktrade_*.db 2>/dev/null | wc -l)"
