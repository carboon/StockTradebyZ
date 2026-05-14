"""
API Cache Decorators
~~~~~~~~~~~~~~~~~~~~
专门为 API 接口优化的缓存装饰器
"""
import json
from functools import wraps
from typing import Any, Callable, TypeVar

from app.cache import cache

T = TypeVar('T')


def build_kline_cache_key(code: str, days: int, include_weekly: bool, compact: bool = False) -> str:
    """构建 K线数据缓存键"""
    return f"kline:{code}:{days}:{include_weekly}:{compact}"


def build_candidates_cache_key(date: str | None, limit: int) -> str:
    """构建候选列表缓存键"""
    return f"candidates:{date or 'latest'}:{limit}"


def build_analysis_result_cache_key(date: str | None) -> str:
    """构建分析结果缓存键"""
    return f"analysis_results:{date or 'latest'}"


def build_watchlist_cache_key(user_id: int, trade_date: str | None) -> str:
    """构建自选股缓存键"""
    return f"watchlist:{user_id}:{trade_date or 'latest'}"


def build_watchlist_analysis_cache_key(item_id: int) -> str:
    """构建自选股分析缓存键"""
    return f"watchlist_analysis:{item_id}"


def build_stock_search_cache_key(query: str, limit: int) -> str:
    """构建股票搜索缓存键"""
    return f"stock_search:{query}:{limit}"


def build_freshness_cache_key() -> str:
    """构建明日之星新鲜度缓存键"""
    return "freshness:global"


def cached_kline(ttl: int = 300):
    """K线数据缓存装饰器

    Args:
        ttl: 缓存时间（秒），默认 5 分钟
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(code: str, days: int, include_weekly: bool = False, *args, **kwargs) -> T:
            compact = bool(kwargs.get("compact", False))
            cache_key = build_kline_cache_key(code, days, include_weekly, compact)
            result = cache.get(cache_key)
            if result is not None:
                return result
            result = await func(code, days, include_weekly, *args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


def cached_candidates(ttl: int = 180):
    """候选列表缓存装饰器

    Args:
        ttl: 缓存时间（秒），默认 3 分钟
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(date: str | None = None, limit: int = 100, *args, **kwargs) -> T:
            cache_key = build_candidates_cache_key(date, limit)
            result = cache.get(cache_key)
            if result is not None:
                return result
            result = await func(date, limit, *args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


def cached_analysis_results(ttl: int = 300):
    """分析结果缓存装饰器

    Args:
        ttl: 缓存时间（秒），默认 5 分钟
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(date: str | None = None, *args, **kwargs) -> T:
            cache_key = build_analysis_result_cache_key(date)
            result = cache.get(cache_key)
            if result is not None:
                return result
            result = await func(date, *args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


def cached_watchlist(ttl: int = 120):
    """自选股列表缓存装饰器

    Args:
        ttl: 缓存时间（秒），默认 2 分钟
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(user_id: int, trade_date: str | None = None, *args, **kwargs) -> T:
            cache_key = build_watchlist_cache_key(user_id, trade_date)
            result = cache.get(cache_key)
            if result is not None:
                return result
            result = await func(user_id, trade_date, *args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


def cached_stock_search(ttl: int = 600):
    """股票搜索缓存装饰器

    Args:
        ttl: 缓存时间（秒），默认 10 分钟
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(q: str, limit: int = 10, *args, **kwargs) -> T:
            if not q or len(q) < 2:
                return await func(q, limit, *args, **kwargs)
            cache_key = build_stock_search_cache_key(q, limit)
            result = cache.get(cache_key)
            if result is not None:
                return result
            result = await func(q, limit, *args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator


def invalidate_stock_cache(code: str) -> None:
    """清除某只股票的相关缓存"""
    # 清除该股票所有 K线缓存，避免新增区间或返回模式后漏删
    cache.delete_prefix(f"kline:{code}:")

    # 清除搜索缓存（需要扫描，实际生产中可以用 set 存储）
    # 这里简化处理，依赖 TTL 自动过期


def invalidate_watchlist_cache(user_id: int) -> None:
    """清除用户自选股缓存"""
    cache.delete_prefix(f"watchlist:{user_id}:")


def invalidate_candidates_cache() -> None:
    """清除候选列表缓存"""
    # 清除各种日期的缓存
    for date in [None, "latest"]:
        for limit in [50, 100, 200]:
            cache.delete(build_candidates_cache_key(date, limit))


def invalidate_analysis_cache() -> None:
    """清除分析结果缓存"""
    for date in [None, "latest"]:
        cache.delete(build_analysis_result_cache_key(date))


# 导出
__all__ = [
    "cache",
    "cached_kline",
    "cached_candidates",
    "cached_analysis_results",
    "cached_watchlist",
    "cached_stock_search",
    "invalidate_stock_cache",
    "invalidate_watchlist_cache",
    "invalidate_candidates_cache",
    "invalidate_analysis_cache",
]
