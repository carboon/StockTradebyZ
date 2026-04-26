#!/bin/bash
# StockTrader Docker 启动脚本

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "🐳 StockTrader 2.0 Docker 部署"
echo "================================"

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ 未找到 Docker，请先安装 Docker"
    exit 1
fi

if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ 未找到 docker-compose"
    exit 1
fi

# 使用 docker compose 或 docker-compose
DOCKER_COMPOSE="docker compose"
if ! docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker-compose"
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  未找到 .env 文件，从 .env.example 复制..."
    cp .env.example .env
    echo "❗ 请编辑 .env 文件，至少配置 TUSHARE_TOKEN"
    echo ""
    read -p "按 Enter 继续 (确保已配置 .env)..."
fi

# 解析命令
COMMAND=${1:-"up"}

case "$COMMAND" in
    up)
        echo "🔨 构建并启动服务..."
        $DOCKER_COMPOSE up -d --build
        ;;
    down)
        echo "🛑 停止服务..."
        $DOCKER_COMPOSE down
        echo "✅ 服务已停止"
        exit 0
        ;;
    restart)
        echo "🔄 重启服务..."
        $DOCKER_COMPOSE restart
        ;;
    logs)
        echo "📋 查看日志 (Ctrl+C 退出)..."
        $DOCKER_COMPOSE logs -f
        exit 0
        ;;
    backend)
        echo "📋 查看后端日志..."
        $DOCKER_COMPOSE logs -f backend
        exit 0
        ;;
    frontend)
        echo "📋 查看前端日志..."
        $DOCKER_COMPOSE logs -f frontend
        exit 0
        ;;
    shell)
        echo "🐚 进入后端容器..."
        $DOCKER_COMPOSE exec backend bash
        exit 0
        ;;
    rebuild)
        echo "🔨 重新构建镜像..."
        $DOCKER_COMPOSE build --no-cache
        $DOCKER_COMPOSE up -d
        ;;
    *)
        echo "用法: $0 {up|down|restart|logs|backend|frontend|shell|rebuild}"
        echo ""
        echo "命令说明:"
        echo "  up       - 构建并启动服务 (默认)"
        echo "  down     - 停止并删除容器"
        echo "  restart  - 重启服务"
        echo "  logs     - 查看所有日志"
        echo "  backend  - 查看后端日志"
        echo "  frontend - 查看前端日志"
        echo "  shell    - 进入后端容器"
        echo "  rebuild  - 重新构建镜像"
        exit 1
        ;;
esac

echo ""
echo "✅ 服务已启动!"
echo "================================"
echo "📱 前端: http://localhost:3000"
echo "🔌 后端: http://localhost:8000"
echo "📚 API文档: http://localhost:8000/docs"
echo ""
echo "查看状态: $DOCKER_COMPOSE ps"
echo "查看日志: $0 logs"
echo "停止服务: $0 down"
