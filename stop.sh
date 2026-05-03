#!/bin/bash
# StockTrader Docker 停止入口
# 默认安全停止，不删除 volume
# 使用 -v 或 --volumes 参数可删除 volume

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 显示帮助信息
show_help() {
    cat << EOF
StockTrader 停止脚本

用法:
  $0 [选项]

选项:
  -v, --volumes    同时删除 volumes (谨慎使用)
  -h, --help       显示帮助信息

示例:
  $0               # 安全停止服务 (保留数据)
  $0 -v            # 停止服务并删除 volumes (删除数据)

EOF
}

# 解析参数
ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help|help)
            show_help
            exit 0
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

# 调用统一运行脚本
exec "$SCRIPT_DIR/deploy/scripts/start.sh" down "${ARGS[@]}"
