"""
Rate Limit Dependency
~~~~~~~~~~~~~~~~~~~~~
基于依赖注入的速率限制，在认证之后执行，支持用户级别限流。

使用方式：
```python
@router.get("/api-endpoint")
async def my_endpoint(
    _rate_limit: None = Depends(rate_limit_dep("authenticated", 100, 60)),
    user: User = Depends(get_current_active_user),
):
    ...
```
"""
import os
import time
from collections import defaultdict
from typing import Callable

from fastapi import Depends, HTTPException, Request
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

# 限流存储：{key: [timestamp1, timestamp2, ...]}
_rate_windows: dict[str, list[float]] = defaultdict(list)

# 限流配置
RATE_LIMITS = {
    "anonymous": (60, 60),        # 60 requests per 60 seconds
    "authenticated": (300, 60),   # 300 requests per 60 seconds
    "admin": (1000, 60),          # 1000 requests per 60 seconds
    "status_api": (10, 60),       # 状态 API: 10 requests per 60 seconds
}


def _check_rate_limit(key: str, limit: int, window: int) -> None:
    """检查是否超过限流，超过则抛出异常。"""
    now = time.time()
    timestamps = _rate_windows[key]

    # 清理过期记录
    cutoff = now - window
    _rate_windows[key] = [t for t in timestamps if t > cutoff]
    timestamps = _rate_windows[key]

    if len(timestamps) >= limit:
        retry_after = int(timestamps[0] + window - now) + 1
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
            headers={"Retry-After": str(max(1, retry_after))},
        )

    # 记录本次请求
    timestamps.append(now)


def skip_rate_limit() -> bool:
    """判断是否跳过限流（开发/测试环境）。"""
    return os.getenv("ENVIRONMENT") == "dev" or "PYTEST_CURRENT_TEST" in os.environ


def rate_limit_dep(
    tier: str = "authenticated",
    limit: int | None = None,
    window: int | None = None,
) -> Callable[[], None]:
    """
    创建速率限制依赖。

    Args:
        tier: 限流等级 (anonymous/authenticated/admin)
        limit: 自定义限制次数
        window: 自定义时间窗口（秒）
    """
    def _rate_limit(request: Request) -> None:
        if skip_rate_limit():
            return

        if limit is not None and window is not None:
            _limit, _window = limit, window
        else:
            _limit, _window = RATE_LIMITS.get(tier, (60, 60))

        # 从 request.state 获取用户信息（由认证中间件设置）
        user_id = getattr(request.state, "user_id", None)
        user_role = getattr(request.state, "user_role", None)

        if user_id is not None:
            key = f"user:{user_id}"
        else:
            key = f"ip:{request.client.host if request.client else 'unknown'}"

        _check_rate_limit(key, _limit, _window)

    return _rate_limit


def status_api_rate_limit(request: Request) -> None:
    """状态 API 的专用限流（10/min），避免频繁轮询。"""
    if skip_rate_limit():
        return

    user_id = getattr(request.state, "user_id", None)
    key = f"status:{user_id or request.client.host}"
    _check_rate_limit(key, 10, 60)


# 导出常用的依赖函数
__all__ = [
    "rate_limit_dep",
    "status_api_rate_limit",
    "skip_rate_limit",
]
