"""
Redis Cache Layer
~~~~~~~~~~~~~~~~~~
Redis 缓存层，支持多实例共享缓存。
降级机制：Redis 不可用时自动使用内存缓存。
"""
import json
import logging
import time
from typing import Any, Callable, TypeVar, Optional
from functools import wraps

from fastapi.encoders import jsonable_encoder

try:
    import redis
    from redis import Redis, ConnectionPool
except ModuleNotFoundError:  # pragma: no cover - optional dependency in test/dev envs
    redis = None
    Redis = Any  # type: ignore[assignment]
    ConnectionPool = None  # type: ignore[assignment]

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar('T')


class RedisCache:
    """Redis 缓存实现，支持序列化和降级"""

    def __init__(
        self,
        redis_url: str | None = None,
        default_ttl: int = 300,
        key_prefix: str = "stocktrade:",
        fallback_to_memory: bool = True,
    ):
        """
        Args:
            redis_url: Redis 连接 URL，默认从环境变量读取
            default_ttl: 默认过期时间（秒）
            key_prefix: 键前缀
            fallback_to_memory: Redis 不可用时是否降级到内存缓存
        """
        self._default_ttl = default_ttl
        self._key_prefix = key_prefix
        self._fallback_to_memory = fallback_to_memory
        self._memory_store: dict[str, tuple[Any, float]] = {}
        self._redis_available: bool | None = None  # None=未检测, True=可用, False=不可用

        # 尝试连接 Redis
        self._redis: Optional[Redis] = self._connect_redis(redis_url)

    def _connect_redis(self, redis_url: str | None) -> Optional[Redis]:
        """连接 Redis"""
        url = redis_url or settings.redis_url_resolved

        # 从环境变量读取
        if not url:
            import os
            url = os.environ.get("REDIS_URL", os.environ.get("REDIST_URL", ""))

        if not url:
            # 尝试默认配置
            redis_host = os.environ.get("REDIS_HOST", "localhost")
            redis_port = int(os.environ.get("REDIS_PORT", 6379))
            redis_db = int(os.environ.get("REDIS_DB", 0))
            redis_password = os.environ.get("REDIS_PASSWORD", None)
            if redis_password:
                url = f"redis://:{redis_password}@{redis_host}:{redis_port}/{redis_db}"
            else:
                url = f"redis://{redis_host}:{redis_port}/{redis_db}"

        if not url or url.startswith("memory://"):
            logger.info("Cache: 使用内存缓存模式")
            self._redis_available = False
            return None

        if redis is None or ConnectionPool is None:
            logger.info("Cache: redis 依赖未安装，降级到内存缓存")
            self._redis_available = False
            return None

        try:
            pool = ConnectionPool.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)
            client = Redis(connection_pool=pool)
            # 测试连接
            client.ping()
            logger.info(f"Cache: Redis 连接成功 - {url.split('@')[-1] if '@' in url else url}")
            self._redis_available = True
            return client
        except Exception as e:
            logger.warning(f"Cache: Redis 连接失败，降级到内存缓存 - {e}")
            self._redis_available = False
            return None

    @property
    def is_redis_available(self) -> bool:
        """Redis 是否可用"""
        if self._redis_available is None:
            self._redis_available = self._redis is not None
            if self._redis_available:
                try:
                    self._redis.ping()
                except Exception:
                    self._redis_available = False
        return self._redis_available

    def _make_key(self, key: str) -> str:
        """生成带前缀的键"""
        return f"{self._key_prefix}{key}"

    def _serialize(self, value: Any) -> str:
        """序列化值"""
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        return json.dumps(jsonable_encoder(value), ensure_ascii=False)

    def _deserialize(self, value: str) -> Any:
        """反序列化值"""
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value

    def get(self, key: str) -> Any | None:
        """获取缓存"""
        cache_key = self._make_key(key)

        # 尝试从 Redis 获取
        if self.is_redis_available and self._redis:
            try:
                value = self._redis.get(cache_key)
                if value is not None:
                    return self._deserialize(value)
            except Exception as e:
                logger.warning(f"Redis GET 失败: {e}")
                self._redis_available = False

        # 降级到内存缓存
        if self._fallback_to_memory:
            if cache_key in self._memory_store:
                value, expires_at = self._memory_store[cache_key]
                if time.time() < expires_at:
                    return value
                del self._memory_store[cache_key]

        return None

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """设置缓存"""
        cache_key = self._make_key(key)
        expires_at = time.time() + (ttl or self._default_ttl)
        serialized = self._serialize(value)

        # 尝试写入 Redis
        if self.is_redis_available and self._redis:
            try:
                self._redis.setex(cache_key, ttl or self._default_ttl, serialized)
                return
            except Exception as e:
                logger.warning(f"Redis SET 失败: {e}")
                self._redis_available = False

        # 降级到内存缓存
        if self._fallback_to_memory:
            self._memory_store[cache_key] = (value, expires_at)

    def delete(self, key: str) -> None:
        """删除缓存"""
        cache_key = self._make_key(key)

        if self.is_redis_available and self._redis:
            try:
                self._redis.delete(cache_key)
            except Exception as e:
                logger.warning(f"Redis DELETE 失败: {e}")

        if self._fallback_to_memory:
            self._memory_store.pop(cache_key, None)

    def clear(self) -> None:
        """清空所有缓存（只清空带当前前缀的）"""
        if self.is_redis_available and self._redis:
            try:
                keys = self._redis.keys(f"{self._key_prefix}*")
                if keys:
                    self._redis.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis CLEAR 失败: {e}")

        if self._fallback_to_memory:
            prefix_to_clear = self._key_prefix
            keys_to_delete = [k for k in self._memory_store.keys() if k.startswith(prefix_to_clear)]
            for k in keys_to_delete:
                del self._memory_store[k]

    def cleanup_expired(self) -> int:
        """清理过期的内存缓存"""
        now = time.time()
        expired = [k for k, (_, exp) in self._memory_store.items() if exp < now]
        for k in expired:
            del self._memory_store[k]
        return len(expired)

    def mget(self, keys: list[str]) -> dict[str, Any]:
        """批量获取"""
        if not keys:
            return {}

        result = {}
        if self.is_redis_available and self._redis:
            try:
                cache_keys = [self._make_key(k) for k in keys]
                values = self._redis.mget(cache_keys)
                for k, v in zip(keys, values):
                    if v is not None:
                        result[k] = self._deserialize(v)
                # 如果全部命中，直接返回
                if len(result) == len(keys):
                    return result
            except Exception as e:
                logger.warning(f"Redis MGET 失败: {e}")
                self._redis_available = False

        # 处理未命中的键
        missing_keys = [k for k in keys if k not in result]
        for k in missing_keys:
            value = self.get(k)
            if value is not None:
                result[k] = value

        return result

    def mset(self, mapping: dict[str, Any], ttl: int | None = None) -> None:
        """批量设置"""
        if not mapping:
            return

        if self.is_redis_available and self._redis:
            try:
                pipe = self._redis.pipeline()
                for k, v in mapping.items():
                    cache_key = self._make_key(k)
                    serialized = self._serialize(v)
                    pipe.setex(cache_key, ttl or self._default_ttl, serialized)
                pipe.execute()
                return
            except Exception as e:
                logger.warning(f"Redis MSET 失败: {e}")
                self._redis_available = False

        # 降级到内存
        for k, v in mapping.items():
            self.set(k, v, ttl)


def cached(
    ttl: int = 300,
    key_prefix: str = "",
    key_builder: Callable[..., str] | None = None,
):
    """缓存装饰器

    Args:
        ttl: 过期时间（秒）
        key_prefix: 键前缀
        key_builder: 自定义键生成函数，签名为 f(*args, **kwargs) -> str

    用法:
        @cached(ttl=30, key_prefix="user:")
        async def get_user(user_id: int):
            ...

        @cached(ttl=60, key_builder=lambda code, days: f"kline:{code}:{days}")
        async def get_kline_data(code: str, days: int):
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # 生成缓存键
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                # 默认键生成策略
                parts = [key_prefix, func.__name__]
                if args:
                    parts.extend(str(a) for a in args)
                if kwargs:
                    parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(parts)

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


# 创建全局缓存实例
cache = RedisCache(
    default_ttl=300,
    key_prefix="stocktrade:",
    fallback_to_memory=True,
)


# 导出
__all__ = ["cache", "cached", "RedisCache"]
