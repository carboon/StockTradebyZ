"""
FastAPI Main Entry Point
~~~~~~~~~~~~~~~~~~~~~~~~
StockTrader 2.0 后端服务主入口
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 项目根目录
ROOT = Path(__file__).parent.parent.parent
BACKEND = Path(__file__).parent.parent

# 确保 PYTHONPATH 包含项目根目录，使用平台相关分隔符兼容 Windows。
pythonpath_entries = [
    entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry
]
for required_path in (str(ROOT), str(BACKEND)):
    if required_path not in pythonpath_entries:
        pythonpath_entries.append(required_path)
if pythonpath_entries:
    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

from app.config import settings
from sqlalchemy import text

from app.database import engine, Base
from app.api import config, stock, analysis, watchlist, tasks

# 创建数据库表
Base.metadata.create_all(bind=engine)


def hydrate_runtime_env_from_db() -> None:
    """启动时从数据库回填关键配置。

    仅在环境变量为空或仍为模板占位值时生效，避免覆盖外部显式传入的系统环境。
    """
    placeholder_values = {"", "your_tushare_token_here"}
    key_map = {
        "tushare_token": "TUSHARE_TOKEN",
        "zhipuai_api_key": "ZHIPUAI_API_KEY",
        "dashscope_api_key": "DASHSCOPE_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "default_reviewer": "DEFAULT_REVIEWER",
        "min_score_threshold": "MIN_SCORE_THRESHOLD",
        "backend_host": "BACKEND_HOST",
        "backend_port": "BACKEND_PORT",
        "backend_cors_origins": "BACKEND_CORS_ORIGINS",
        "vite_api_base_url": "VITE_API_BASE_URL",
    }

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT key, value FROM configs")).fetchall()

    config_map = {str(row[0]).lower(): str(row[1]) for row in rows if row[0]}
    for db_key, env_key in key_map.items():
        current = os.environ.get(env_key, "")
        if current not in placeholder_values:
            continue
        value = config_map.get(db_key, "")
        if value:
            os.environ[env_key] = value


hydrate_runtime_env_from_db()


def ensure_watchlist_schema() -> None:
    """兼容旧数据库：补齐 watchlist 新字段。"""
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(watchlist)")).fetchall()
        }
        if "entry_price" not in columns:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN entry_price FLOAT"))
        if "position_ratio" not in columns:
            conn.execute(text("ALTER TABLE watchlist ADD COLUMN position_ratio FLOAT"))

        analysis_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(watchlist_analysis)")).fetchall()
        }
        if "buy_action" not in analysis_columns:
            conn.execute(text("ALTER TABLE watchlist_analysis ADD COLUMN buy_action VARCHAR(30)"))
        if "hold_action" not in analysis_columns:
            conn.execute(text("ALTER TABLE watchlist_analysis ADD COLUMN hold_action VARCHAR(30)"))
        if "risk_level" not in analysis_columns:
            conn.execute(text("ALTER TABLE watchlist_analysis ADD COLUMN risk_level VARCHAR(20)"))
        if "buy_recommendation" not in analysis_columns:
            conn.execute(text("ALTER TABLE watchlist_analysis ADD COLUMN buy_recommendation TEXT"))
        if "hold_recommendation" not in analysis_columns:
            conn.execute(text("ALTER TABLE watchlist_analysis ADD COLUMN hold_recommendation TEXT"))
        if "risk_recommendation" not in analysis_columns:
            conn.execute(text("ALTER TABLE watchlist_analysis ADD COLUMN risk_recommendation TEXT"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_analysis_watchlist_date "
                "ON watchlist_analysis (watchlist_id, analysis_date)"
            )
        )


ensure_watchlist_schema()


def ensure_task_center_schema() -> None:
    """兼容旧数据库：补齐任务中心相关字段。"""
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        task_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(tasks)")).fetchall()
        }
        if "trigger_source" not in task_columns:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN trigger_source VARCHAR(20) DEFAULT 'manual'"))
        if "task_stage" not in task_columns:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN task_stage VARCHAR(50)"))
        if "summary" not in task_columns:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN summary TEXT"))


ensure_task_center_schema()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI startup/shutdown lifecycle without deprecated hooks."""
    print(f"🚀 StockTrader API v{app.version} 启动成功")
    print(f"📍 API 文档: http://{settings.host}:{settings.port}/docs")
    yield
    print("👋 StockTrader API 已关闭")

# 创建 FastAPI 应用
app = FastAPI(
    title="StockTrader API",
    description="A股量化选股系统 API",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS 配置
cors_origins = settings.cors_origins
if isinstance(cors_origins, str):
    cors_origins = [origin.strip() for origin in cors_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载数据目录 (用于访问 K线图等静态资源)
data_dir = ROOT / "data"
if data_dir.exists():
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")

# 注册路由
app.include_router(config.router, prefix="/api/v1/config", tags=["配置管理"])
app.include_router(stock.router, prefix="/api/v1/stock", tags=["股票数据"])
app.include_router(analysis.router, prefix="/api/v1/analysis", tags=["分析"])
app.include_router(watchlist.router, prefix="/api/v1/watchlist", tags=["重点观察"])
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["任务调度"])


# WebSocket 连接管理器
class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str) -> None:
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = []
        self.active_connections[task_id].append(websocket)

    def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        if task_id in self.active_connections:
            self.active_connections[task_id].remove(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]

    async def send_message(self, task_id: str | int, message: str) -> None:
        """向指定任务的所有连接发送消息"""
        task_id_str = str(task_id)
        if task_id_str in self.active_connections:
            for connection in self.active_connections[task_id_str]:
                try:
                    await connection.send_text(message)
                except Exception:
                    pass

    async def broadcast(self, message: str) -> None:
        for connections in self.active_connections.values():
            for connection in connections:
                try:
                    await connection.send_text(message)
                except:
                    pass


manager = ConnectionManager()


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "version": app.version}


@app.websocket("/ws/tasks/{task_id}")
async def task_websocket(websocket: WebSocket, task_id: str):
    """任务进度 WebSocket"""
    await manager.connect(websocket, task_id)
    try:
        while True:
            data = await websocket.receive_text()
            # 心跳包
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, task_id)


@app.websocket("/ws/ops")
async def ops_websocket(websocket: WebSocket):
    """任务中心统一事件 WebSocket"""
    await manager.connect(websocket, "ops")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, "ops")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
