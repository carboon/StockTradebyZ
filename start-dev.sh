#!/bin/bash
# StockTrader 本地开发启动脚本

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "🚀 StockTrader 2.0 本地开发启动"
echo "================================"

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  未找到 .env 文件，从 .env.example 复制..."
    cp .env.example .env
    echo "❗ 请编辑 .env 文件，至少配置 TUSHARE_TOKEN"
    echo ""
    read -p "按 Enter 继续 (确保已配置 .env)..."
fi

# 检查虚拟环境
if [ ! -d .venv ]; then
    echo "📦 创建虚拟环境..."
    python3 -m venv .venv
fi

# 激活虚拟环境
source .venv/bin/activate

# 安装后端依赖
if [ "$1" != "--skip-deps" ]; then
    echo "📥 检查后端依赖..."
    pip install -r requirements.txt 2>/dev/null || pip install -r requirements.txt
    pip install -r backend/requirements.txt 2>/dev/null || pip install -r backend/requirements.txt
else
    echo "⏭️  跳过依赖安装"
fi

# 检查前端依赖
if [ ! -d frontend/node_modules ]; then
    echo "📥 安装前端依赖 (首次运行需要几分钟)..."
    cd frontend
    npm install
    cd ..
else
    echo "✅ 前端依赖已存在"
fi

# 创建数据目录
mkdir -p data/db data/raw data/candidates data/review data/kline data/logs

# 启动后端
echo ""
echo "🔧 启动后端服务 (端口 8000)..."
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
cd ..

# 等待后端启动
sleep 2

# 启动前端
echo "🎨 启动前端服务 (端口 5173)..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ 服务已启动!"
echo "================================"
echo "📱 前端: http://localhost:5173"
echo "🔌 后端: http://localhost:8000"
echo "📚 API文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 捕获退出信号
trap "echo ''; echo '🛑 停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM

# 等待进程
wait
