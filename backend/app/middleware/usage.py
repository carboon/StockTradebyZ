"""
Usage Tracking Middleware
~~~~~~~~~~~~~~~~~~~~~~~~~~
记录 API 请求到 usage_logs 表，用于用量统计。

## 日志策略（阶段3优化）
为降低SQLite写压力，采用批量聚合策略：
1. 使用内存缓冲区收集请求日志
2. 每60秒或缓冲区达到100条记录时批量写入
3. 使用后台线程定期flush，避免阻塞请求
4. 应用关闭时确保缓冲区数据持久化

## 预期效果
- 写入频率降低约95%（从每请求一次变为每分钟批量）
- 对于100用户的QPS 10场景，每天从约86,400次写降低到约1,440次
"""
import asyncio
import logging
import threading
import time
from collections import defaultdict
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# 不需要记录的路径前缀
SKIP_PATHS = ("/health", "/docs", "/redoc", "/openapi.json", "/static", "/data")

# 聚合配置
FLUSH_INTERVAL = 60  # 秒，批量写入间隔
FLUSH_THRESHOLD = 100  # 条，达到此数量立即写入


class UsageBuffer:
    """用量日志缓冲区，支持批量聚合写入。"""

    def __init__(self):
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._flush_task: asyncio.Task | None = None
        self._running = False

    def add(self, log_data: dict[str, Any]) -> None:
        """添加日志到缓冲区，如果达到阈值则触发写入。"""
        with self._lock:
            self._buffer.append(log_data)
            if len(self._buffer) >= FLUSH_THRESHOLD:
                self._flush_now()

    def _flush_now(self) -> None:
        """立即刷新缓冲区到数据库。"""
        if not self._buffer:
            return

        from app.database import SessionLocal
        from app.models import UsageLog

        buffer_copy = self._buffer[:]
        self._buffer.clear()
        self._last_flush = time.time()

        db = SessionLocal()
        try:
            logs = [
                UsageLog(
                    user_id=item.get("user_id"),
                    api_key_id=item.get("api_key_id"),
                    endpoint=item["endpoint"],
                    method=item["method"],
                    ip_address=item.get("ip_address"),
                    status_code=item["status_code"],
                )
                for item in buffer_copy
            ]
            db.add_all(logs)
            db.commit()
            logger.debug("批量写入 usage_logs: %d 条", len(logs))
        except Exception as e:
            db.rollback()
            logger.warning("批量写入 usage_logs 失败: %s", e)
        finally:
            db.close()

    def start_background_flush(self) -> None:
        """启动后台定期刷新任务。"""
        if self._running:
            return
        self._running = True

        def flush_loop():
            while self._running:
                time.sleep(FLUSH_INTERVAL)
                if self._buffer:
                    self._flush_now()

        thread = threading.Thread(target=flush_loop, daemon=True)
        thread.start()

    def shutdown(self) -> None:
        """停止并刷新剩余数据。"""
        self._running = False
        self._flush_now()


# 全局缓冲区实例
_usage_buffer = UsageBuffer()


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    """记录每次 API 请求的用量信息（聚合写入模式）。"""

    def __init__(self, app):
        super().__init__(app)
        # 确保后台刷新任务只启动一次
        if not _usage_buffer._running:
            _usage_buffer.start_background_flush()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # 跳过不需要记录的路径
        path = request.url.path
        if any(path.startswith(skip) for skip in SKIP_PATHS):
            return response

        # 只记录 API 请求
        if not path.startswith("/api/") and not path.startswith("/ws/"):
            return response

        # 异步记录用量（不阻塞响应）
        try:
            self._log_usage(request, response.status_code)
        except Exception:
            # 用量记录失败不应影响请求
            logger.debug("用量记录失败", exc_info=True)

        return response

    def _log_usage(self, request: Request, status_code: int) -> None:
        """将用量信息添加到缓冲区。"""
        # 尝试从请求状态中获取已认证的用户信息（由 deps.py 设置）
        user_id = getattr(request.state, "user_id", None)
        api_key_id = getattr(request.state, "api_key_id", None)

        ip_address = request.client.host if request.client else None

        log_data = {
            "user_id": user_id,
            "api_key_id": api_key_id,
            "endpoint": request.url.path,
            "method": request.method,
            "ip_address": ip_address,
            "status_code": status_code,
        }

        _usage_buffer.add(log_data)


def flush_usage_buffer() -> None:
    """手动刷新缓冲区（用于测试或优雅关闭）。"""
    _usage_buffer._flush_now()
