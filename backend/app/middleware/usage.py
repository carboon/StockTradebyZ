"""
Usage Tracking Middleware
~~~~~~~~~~~~~~~~~~~~~~~~~~
记录 API 请求到 usage_logs 表，用于用量统计。
使用 fire-and-forget 模式避免阻塞请求。
"""
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.database import engine
from app.models import UsageLog

logger = logging.getLogger(__name__)

# 不需要记录的路径前缀
SKIP_PATHS = ("/health", "/docs", "/redoc", "/openapi.json", "/static", "/data")


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    """记录每次 API 请求的用量信息。"""

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
        """同步写入用量日志到数据库。"""
        # 尝试从请求状态中获取已认证的用户信息（由 deps.py 设置）
        user_id = getattr(request.state, "user_id", None)
        api_key_id = getattr(request.state, "api_key_id", None)

        ip_address = request.client.host if request.client else None

        log = UsageLog(
            user_id=user_id,
            api_key_id=api_key_id,
            endpoint=request.url.path,
            method=request.method,
            ip_address=ip_address,
            status_code=status_code,
        )

        from app.database import SessionLocal
        db = SessionLocal()
        try:
            db.add(log)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
