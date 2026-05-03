"""
Database Configuration
~~~~~~~~~~~~~~~~~~~~~~
PostgreSQL 数据库连接和会话管理
"""
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool
from fastapi import Request

from app.config import settings


def _create_engine():
    """根据数据库 URL 创建引擎。当前仅支持 PostgreSQL。"""
    db_url = settings.database_url

    if not db_url.startswith("postgresql"):
        raise RuntimeError(
            "Unsupported DATABASE_URL. StockTrader now requires PostgreSQL."
        )

    engine = create_engine(
        db_url,
        echo=settings.debug,
        poolclass=QueuePool,
        pool_size=20,
        max_overflow=30,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_timeout=30,
    )

    return engine


# 创建数据库引擎
engine = _create_engine()

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """所有模型的基类 (SQLAlchemy 2.0)"""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


def close_db_session(db: Optional[Session]) -> None:
    """安全关闭会话，确保未提交事务被回滚。"""
    if db is None:
        return
    try:
        db.rollback()
    except Exception:
        pass
    try:
        db.close()
    except Exception:
        pass


def get_db(request: Request) -> Generator[Session, None, None]:
    """
    数据库会话依赖注入
    用法: db: Session = Depends(get_db)
    """
    db = getattr(request.state, "db_session", None)
    owns_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        yield db
    finally:
        if owns_session:
            close_db_session(db)


@contextmanager
def get_db_context() -> Session:
    """
    数据库会话上下文管理器
    用法: with get_db_context() as db:
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        close_db_session(db)
