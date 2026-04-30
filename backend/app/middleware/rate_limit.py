"""
Rate Limiting Middleware
~~~~~~~~~~~~~~~~~~~~~~~~
基于内存的滑动窗口 API 限流器。
匿名 60/min，已认证 300/min，管理员 1000/min。
"""
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# 限流配置
RATE_LIMITS = {
    "anonymous": (60, 60),     # 60 requests per 60 seconds
    "authenticated": (300, 60), # 300 requests per 60 seconds
    "admin": (1000, 60),       # 1000 requests per 60 seconds
}

# 不限流的路径
SKIP_PATHS = ("/health", "/docs", "/redoc", "/openapi.json", "/static", "/data")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于滑动窗口的 API 限流中间件。"""

    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        # {key: [timestamp1, timestamp2, ...]}
        self._windows: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # 跳过非 API 路径
        if not path.startswith("/api/") and not path.startswith("/ws/"):
            return await call_next(request)

        # 跳过公开路径
        if any(path.startswith(skip) for skip in SKIP_PATHS):
            return await call_next(request)

        # 确定限流等级和 key
        user_role = getattr(request.state, "user_role", None)
        user_id = getattr(request.state, "user_id", None)

        if user_role == "admin":
            limit, window = RATE_LIMITS["admin"]
        elif user_id is not None:
            limit, window = RATE_LIMITS["authenticated"]
        else:
            limit, window = RATE_LIMITS["anonymous"]

        # 使用 user_id 或 IP 作为 key
        if user_id is not None:
            key = f"user:{user_id}"
        else:
            key = f"ip:{request.client.host if request.client else 'unknown'}"

        # 滑动窗口检查
        now = time.time()
        timestamps = self._windows[key]

        # 清理过期记录
        cutoff = now - window
        self._windows[key] = [t for t in timestamps if t > cutoff]
        timestamps = self._windows[key]

        if len(timestamps) >= limit:
            retry_after = int(timestamps[0] + window - now) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后再试"},
                headers={"Retry-After": str(max(1, retry_after))},
            )

        # 记录本次请求
        self._windows[key].append(now)

        return await call_next(request)
