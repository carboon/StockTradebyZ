"""
Simple Memory Cache
~~~~~~~~~~~~~~~~~~~~
轻量级内存缓存，用于减少数据库访问。
适合单实例部署，100 人规模。
"""
import time
from typing import Any, Callable, TypeVar
from functools import wraps

T = TypeVar('T')


class SimpleCache:
    """简单的 TTL 缓存"""

    def __init__(self, default_ttl: int = 60):
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        """获取缓存"""
        if key not in self._store:
            return None

        value, expires_at = self._store[key]
        if time.time() > expires_at:
            del self._store[key]
            return None

        return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """设置缓存"""
        expires_at = time.time() + (ttl or self._default_ttl)
        self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        """删除缓存"""
        self._store.pop(key, None)

    def clear(self) -> None:
        """清空所有缓存"""
        self._store.clear()

    def cleanup_expired(self) -> int:
        """清理过期缓存，返回清理数量"""
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if exp < now]
        for k in expired:
            del self._store[k]
        return len(expired)


# 全局缓存实例
cache = SimpleCache(default_ttl=60)


def cached(ttl: int = 60, key_prefix: str = ""):
    """缓存装饰器

    用法:
        @cached(ttl=30, key_prefix="user:")
        async def get_user(user_id: int):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # 生成缓存键
            cache_key = f"{key_prefix}{func.__name__}:{args}:{kwargs}"

            # 尝试从缓存获取
            result = cache.get(cache_key)
            if result is not None:
                return result

            # 执行函数并缓存结果
            result = await func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result

        return wrapper
    return decorator


# 导出
__all__ = ["cache", "cached", "SimpleCache"]
