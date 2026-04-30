"""
Authentication Utilities
~~~~~~~~~~~~~~~~~~~~~~~~
JWT 令牌管理、密码哈希、API Key 工具
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# JWT 配置
ALGORITHM = "HS256"

# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --- 密码工具 ---

def hash_password(password: str) -> str:
    """对明文密码进行哈希。"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配。"""
    return pwd_context.verify(plain_password, hashed_password)


# --- JWT 工具 ---

def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """创建 JWT access token。

    Args:
        data: 要编码的 payload，通常包含 {"sub": str(user_id), "role": str}
        expires_delta: 自定义过期时间，默认使用配置中的 access_token_expire_minutes
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码并验证 JWT token。

    Returns:
        解码后的 payload dict，验证失败返回 None
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# --- API Key 工具 ---

def generate_api_key() -> str:
    """生成 API Key，格式为 sk-<32字符hex>。"""
    return f"sk-{secrets.token_hex(32)}"


def hash_api_key(key: str) -> str:
    """对 API Key 进行 SHA-256 哈希，用于数据库存储。"""
    return hashlib.sha256(key.encode()).hexdigest()


def get_api_key_prefix(key: str) -> str:
    """提取 API Key 的前 8 个字符，用于界面展示。"""
    return key[:8]
