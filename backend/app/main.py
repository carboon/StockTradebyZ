"""
FastAPI Main Entry Point
~~~~~~~~~~~~~~~~~~~~~~~~
StockTrader 2.0 后端服务主入口
"""
from __future__ import annotations

import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

# 项目根目录
ROOT = Path(__file__).parent.parent.parent
BACKEND = Path(__file__).parent.parent
DISABLE_TOMORROW_STAR_BOOTSTRAP_FILE = ROOT / "data" / ".disable_tomorrow_star_bootstrap"

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

from app.database import engine, Base, get_db, SessionLocal
from app.api import auth, config, stock, analysis, watchlist, tasks
from app.services.tomorrow_star_window_service import get_tomorrow_star_window_service

# 测试环境检测：当 pytest 正在运行时，跳过数据库初始化
# pytest 会自动设置 PYTEST_CURRENT_TEST 环境变量
_TEST_MODE = "PYTEST_CURRENT_TEST" in os.environ

# 创建数据库表（仅在非测试环境）
if not _TEST_MODE:
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


if not _TEST_MODE:
    hydrate_runtime_env_from_db()


def ensure_admin_user() -> None:
    """首次启动时创建默认管理员账户。"""
    from datetime import datetime, timezone

    from app.auth import hash_password
    from app.models import User
    from app.time_utils import utc_now

    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar()
        if count == 0:
            now = utc_now()
            conn.execute(
                text(
                    "INSERT INTO users (username, hashed_password, role, is_active, daily_quota, created_at, updated_at) "
                    "VALUES (:username, :password, 'admin', true, 10000, :now, :now)"
                ),
                {
                    "username": settings.admin_default_username,
                    "password": hash_password(settings.admin_default_password),
                    "now": now,
                },
            )
            print(f"已创建默认管理员账户: {settings.admin_default_username}")


if not _TEST_MODE:
    ensure_admin_user()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI startup/shutdown lifecycle without deprecated hooks."""
    print(f"🚀 StockTrader API v{app.version} 启动成功")
    print(f"📍 API 文档: http://{settings.host}:{settings.port}/docs")

    async def bootstrap_tomorrow_star_window() -> None:
        try:
            await asyncio.to_thread(
                get_tomorrow_star_window_service().ensure_window,
                180,
            )
        except Exception as exc:
            print(f"⚠️ 明日之星 180 日窗口补齐启动失败: {exc}")

    if not _TEST_MODE and not DISABLE_TOMORROW_STAR_BOOTSTRAP_FILE.exists():
        asyncio.create_task(bootstrap_tomorrow_star_window())

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
    cors_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]

# 生产环境严格 CORS：仅允许配置的域名
# 开发环境：自动补充 localhost 来源
if settings.environment == "development":
    dev_origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    for origin in dev_origins:
        if origin not in cors_origins:
            cors_origins.append(origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 用量追踪中间件
from app.middleware.usage import UsageTrackingMiddleware
app.add_middleware(UsageTrackingMiddleware)


@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """为每个 HTTP 请求提供并回收独立数据库会话。"""
    request.state.db_session = SessionLocal()
    try:
        response = await call_next(request)
        return response
    finally:
        app_db = getattr(request.state, "db_session", None)
        if app_db is not None:
            try:
                app_db.rollback()
            except Exception:
                pass
            try:
                app_db.close()
            except Exception:
                pass

# 注意：速率限制已改为依赖注入方式（在各个路由中使用），
# 这样可以在认证之后执行，正确获取用户身份

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
app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])


class SPAStaticFiles(StaticFiles):
    """为 Vue Router history 模式提供 index.html 回退。"""

    async def get_response(self, path: str, scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            request = Request(scope)
            if request.method != "GET":
                raise
            return await super().get_response("index.html", scope)


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
@app.get("/api/health")
async def health_check(db: DBSession = Depends(get_db)):
    """健康检查，包含数据库连通性验证。"""
    db_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": app.version,
        "environment": settings.environment,
        "database": db_status,
    }


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


frontend_dist_dir = ROOT / "frontend" / "dist"
if frontend_dist_dir.exists():
    app.mount(
        "/",
        SPAStaticFiles(directory=str(frontend_dist_dir), html=True),
        name="frontend",
    )

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
