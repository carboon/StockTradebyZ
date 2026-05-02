"""
Authentication Dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FastAPI 依赖注入：用户认证、权限检查

## 日志策略（阶段3优化）
ApiKey.last_used_at 更新策略：
1. 使用内存缓存记录已更新的API Key
2. 时间窗口60秒内同一key只更新一次
3. 使用LRU缓存自动清理过期记录

## 预期效果
- 对于高频API调用，last_used_at更新频率降低约98%
- 从每次请求更新变为每分钟最多一次
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import decode_access_token, hash_api_key
from app.database import get_db
from app.models import ApiKey, User

# Bearer token 提取器（auto_error=False 使得 token 可选）
bearer_scheme = HTTPBearer(auto_error=False)


# API Key最后使用时间缓存（用于降低写库频率）
# 结构: {api_key_id: last_update_timestamp}
_api_key_last_update_cache: dict[int, float] = {}
_API_KEY_UPDATE_INTERVAL = 60  # 秒，同一key的最小更新间隔


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """从 Bearer token 或 X-API-Key header 中提取并验证当前用户。

    优先检查 Bearer token，其次检查 X-API-Key header。
    """
    user = _try_bearer_token(credentials, db)
    if user:
        _stash_user_context(request, user)
        return user

    user = _try_api_key(request, db)
    if user:
        _stash_user_context(request, user, api_key_id=getattr(request.state, "api_key_id", None))
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未提供有效的认证凭据",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_active_user(
    user: User = Depends(get_current_user),
) -> User:
    """获取当前活跃用户，已禁用的用户将被拒绝。"""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户已被禁用",
        )
    return user


def get_admin_user(
    user: User = Depends(get_current_active_user),
) -> User:
    """获取管理员用户，非管理员将被拒绝。"""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


def get_optional_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    """尝试获取当前用户，失败时返回 None（不抛异常）。

    用于 usage tracking 等场景，允许匿名请求通过。
    """
    user = _try_bearer_token(credentials, db)
    if user:
        _stash_user_context(request, user)
        return user
    user = _try_api_key(request, db)
    if user:
        _stash_user_context(request, user, api_key_id=getattr(request.state, "api_key_id", None))
    return user


def require_user(
    user: User | None = Depends(get_optional_user),
) -> User:
    """确保有已认证的用户，否则返回 401。"""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# --- 内部辅助函数 ---


def _stash_user_context(request: Request, user: User, *, api_key_id: int | None = None) -> None:
    """将认证结果写入 request.state，供限流与用量统计复用。"""
    request.state.user_id = user.id
    request.state.user_role = user.role
    if api_key_id is not None:
        request.state.api_key_id = api_key_id


def _try_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
    db: Session,
) -> User | None:
    """尝试从 Bearer token 中解析用户。"""
    if not credentials:
        return None

    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError):
        return None

    return db.query(User).filter(User.id == user_id_int).first()


def _try_api_key(request: Request, db: Session) -> User | None:
    """尝试从 X-API-Key header 中查找用户。

    使用时间窗口缓存降低 last_used_at 更新频率：
    - 同一 API Key 在60秒内只更新一次 last_used_at
    - 使用内存缓存避免频繁写库
    """
    import time

    api_key_value = request.headers.get("X-API-Key")
    if not api_key_value:
        return None

    key_hash = hash_api_key(api_key_value)
    api_key_record = (
        db.query(ApiKey)
        .filter(ApiKey.key_hash == key_hash, ApiKey.is_active.is_(True))
        .first()
    )
    if not api_key_record:
        return None

    # 检查是否需要更新 last_used_at（使用时间窗口缓存）
    current_time = time.time()
    last_update = _api_key_last_update_cache.get(api_key_record.id, 0)

    if current_time - last_update >= _API_KEY_UPDATE_INTERVAL:
        from app.time_utils import utc_now
        api_key_record.last_used_at = utc_now()
        db.commit()
        _api_key_last_update_cache[api_key_record.id] = current_time

    # 返回关联的用户
    request.state.api_key_id = api_key_record.id
    return db.query(User).filter(User.id == api_key_record.user_id).first()
