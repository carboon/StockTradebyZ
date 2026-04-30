"""
Pytest Configuration and Fixtures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
测试基础设施配置，为所有测试提供公共支持
"""
from datetime import date, datetime
from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker, scoped_session

from app.auth import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models import User


# ============================================
# Database Fixtures
# ============================================

# 使用命名内存数据库以支持跨连接共享
TEST_DATABASE_URL = "sqlite:///file:test_db?mode=memory&cache=shared"


@pytest.fixture(scope="function")
def test_db() -> Generator[Session, None, None]:
    """
    创建内存 SQLite 测试数据库

    每个测试函数都会获得一个全新的数据库，测试结束后自动清理。
    使用事务回滚来确保测试之间的隔离。
    """
    # 创建测试数据库引擎
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

    # 创建所有表
    Base.metadata.create_all(bind=engine)

    # 创建会话
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()
        # 清理所有表
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_db: Session) -> Generator[Session, None, None]:
    """
    数据库会话 fixture

    这是 test_db 的别名，提供更语义化的名称。
    在测试中使用 db_session 来访问数据库会话。
    """
    yield test_db


# ============================================
# FastAPI Test Client Fixtures
# ============================================

class ____TestClientWithDb:
    """
    测试客户端包装器，同时提供客户端和数据库访问

    这个类允许测试同时访问 test_client 和底层的数据库会话。
    """
    def __init__(self, client: TestClient, db: Session):
        self.client = client
        self.db = db

    def __getattr__(self, name):
        """代理所有其他属性到 test_client"""
        return getattr(self.client, name)


@pytest.fixture(scope="function")
def test_client() -> Generator[TestClient, None, None]:
    """
    FastAPI 测试客户端（独立版本）

    自动创建和管理测试数据库。
    此 fixture 创建独立的数据库实例，适合不需要直接访问数据库的测试。

    注意：此客户端会自动绕过身份验证要求，方便测试。
    """
    # 创建测试数据库引擎
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

    # 创建所有表
    Base.metadata.create_all(bind=engine)

    # 创建会话
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    # 创建测试用户
    test_user = User(
        username="testuser",
        hashed_password=hash_password("testpass123"),
        display_name="Test User",
        role="user",
        is_active=True,
        daily_quota=1000,
    )
    db.add(test_user)
    db.commit()
    db.refresh(test_user)

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    # 绕过身份验证依赖 - 返回测试用户
    from app.api import deps
    original_get_current_user = deps.get_current_user
    original_require_user = deps.require_user

    def mock_get_current_user():
        return test_user

    def mock_require_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = mock_get_current_user
    app.dependency_overrides[deps.require_user] = mock_require_user

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        # 恢复原始函数
        deps.get_current_user = original_get_current_user
        deps.require_user = original_require_user
        db.close()
        # 清理所有表
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(scope="function")
def test_client_with_db() -> Generator[Any, None, None]:
    """
    FastAPI 测试客户端（带数据库访问）

    同时提供 test_client 和数据库会话访问。

    使用方式:
        def test_something(test_client_with_db):
            # 使用客户端发送请求
            response = test_client_with_db.get("/api/v1/config/")

            # 直接访问数据库验证
            configs = test_client_with_db.db.query(Config).all()

    注意：此客户端会自动绕过身份验证要求，方便测试。
    """
    # 创建测试数据库引擎
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

    # 创建所有表
    Base.metadata.create_all(bind=engine)

    # 创建会话
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()

    # 创建测试用户
    test_user = User(
        username="testuser",
        hashed_password=hash_password("testpass123"),
        display_name="Test User",
        role="user",
        is_active=True,
        daily_quota=1000,
    )
    db.add(test_user)
    db.commit()
    db.refresh(test_user)

    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db
        finally:
            pass

    # 绕过身份验证依赖 - 返回测试用户
    from app.api import deps
    original_get_current_user = deps.get_current_user
    original_require_user = deps.require_user

    def mock_get_current_user():
        return test_user

    def mock_require_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user
    app.dependency_overrides[deps.get_current_active_user] = mock_get_current_user
    app.dependency_overrides[deps.require_user] = mock_require_user

    try:
        with TestClient(app) as client:
            yield ____TestClientWithDb(client, db)
    finally:
        app.dependency_overrides.clear()
        # 恢复原始函数
        deps.get_current_user = original_get_current_user
        deps.require_user = original_require_user
        db.close()
        # 清理所有表
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ============================================
# Sample Data Fixtures
# ============================================

@pytest.fixture(scope="function")
def sample_stock_data() -> list[dict]:
    """
    示例股票数据 fixture

    提供一组测试用的股票数据，包含上交所和深交所的股票。
    """
    return [
        {
            "code": "600000",
            "name": "浦发银行",
            "market": "SH",
            "industry": "银行",
        },
        {
            "code": "000001",
            "name": "平安银行",
            "market": "SZ",
            "industry": "银行",
        },
        {
            "code": "600036",
            "name": "招商银行",
            "market": "SH",
            "industry": "银行",
        },
        {
            "code": "000858",
            "name": "五粮液",
            "market": "SZ",
            "industry": "白酒",
        },
        {
            "code": "600519",
            "name": "贵州茅台",
            "market": "SH",
            "industry": "白酒",
        },
    ]


@pytest.fixture(scope="function")
def mock_tushare_api() -> MagicMock:
    """
    Mock Tushare API fixture

    提供 Tushare API 的 mock 对象，用于测试与 Tushare API 交互的功能。
    可以在测试中覆盖返回值。

    示例用法:
        mock_tushare_api.pro_bar.return_value = mock_dataframe
        mock_tushare_api.daily.return_value = mock_dataframe
    """
    mock_api = MagicMock()

    # Mock 常用的 API 方法
    mock_api.pro_bar = MagicMock(return_value=None)
    mock_api.daily = MagicMock(return_value=None)
    mock_api.pro_daily = MagicMock(return_value=None)
    mock_api.stock_basic = MagicMock(return_value=None)
    mock_api.trade_cal = MagicMock(return_value=None)

    return mock_api


@pytest.fixture(scope="function")
def mock_llm_client() -> MagicMock:
    """
    Mock LLM Client fixture

    提供 LLM 客户端的 mock 对象，用于测试 AI 分析功能。
    支持 OpenAI、Anthropic、Qwen 等多种 LLM 提供商。
    """
    mock_client = MagicMock()

    # Mock 常用的 LLM 方法
    mock_chat_completion = MagicMock()
    mock_chat_completion.choices = [MagicMock()]
    mock_chat_completion.choices[0].message.content = "PASS: 分析通过"
    mock_client.chat.completions.create = MagicMock(return_value=mock_chat_completion)

    return mock_client


@pytest.fixture(scope="function")
def sample_pick_date() -> date:
    """
    示例选股日期 fixture

    提供一个固定的测试日期，方便在测试中使用。
    """
    return date(2024, 1, 15)


# ============================================
# Authentication Fixtures
# ============================================


@pytest.fixture(scope="function")
def test_user(test_db: Session) -> User:
    """
    创建测试用户

    为需要认证的测试提供一个已注册的测试用户。
    """
    user = User(
        username="testuser",
        hashed_password=hash_password("testpass123"),
        display_name="Test User",
        role="user",
        is_active=True,
        daily_quota=1000,
    )
    test_db.add(user)
    test_db.commit()
    test_db.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_admin(test_db: Session) -> User:
    """
    创建测试管理员

    为需要管理员权限的测试提供一个管理员用户。
    """
    admin = User(
        username="testadmin",
        hashed_password=hash_password("adminpass123"),
        display_name="Test Admin",
        role="admin",
        is_active=True,
        daily_quota=10000,
    )
    test_db.add(admin)
    test_db.commit()
    test_db.refresh(admin)
    return admin


@pytest.fixture(scope="function")
def auth_headers(test_user: User) -> dict:
    """
    生成认证请求头

    为需要认证的API请求提供Bearer token。
    """
    token = create_access_token({"sub": str(test_user.id), "role": test_user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def admin_headers(test_admin: User) -> dict:
    """
    生成管理员认证请求头

    为需要管理员权限的API请求提供Bearer token。
    """
    token = create_access_token({"sub": str(test_admin.id), "role": test_admin.role})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="function")
def authenticated_client(test_client_with_db: Any, test_user: User) -> Any:
    """
    带认证的测试客户端

    自动包含用户认证token的测试客户端。
    """
    token = create_access_token({"sub": str(test_user.id), "role": test_user.role})
    test_client_with_db.headers.update({"Authorization": f"Bearer {token}"})
    return test_client_with_db


# ============================================
# Async Fixtures
# ============================================

@pytest.fixture(scope="function")
async def async_mock_tushare_api() -> AsyncMock:
    """
    异步 Mock Tushare API fixture

    提供异步版本的 Tushare API mock 对象。
    """
    mock_api = AsyncMock()

    mock_api.pro_bar = AsyncMock(return_value=None)
    mock_api.daily = AsyncMock(return_value=None)

    return mock_api
