"""
Authentication Dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
FastAPI 依赖注入：用户认证、权限检查
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import decode_access_token, hash_api_key
from app.database import get_db
from app.models import ApiKey, User

# Bearer token 提取器（auto_error=False 使得 token 可选）
bearer_scheme = HTTPBearer(auto_error=False)


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
        return user

    user = _try_api_key(request, db)
    if user:
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
        return user
    return _try_api_key(request, db)


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
    """尝试从 X-API-Key header 中查找用户。"""
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

    # 更新最后使用时间
    from app.time_utils import utc_now
    api_key_record.last_used_at = utc_now()
    db.commit()

    # 返回关联的用户
    return db.query(User).filter(User.id == api_key_record.user_id).first()
