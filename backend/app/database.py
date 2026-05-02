"""
Database Configuration
~~~~~~~~~~~~~~~~~~~~~~
支持 SQLite 和 PostgreSQL 的数据库连接和会话管理
单实例 100 人规模优化配置
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool, NullPool
from fastapi import Request

from app.config import settings


def _create_engine():
    """根据数据库 URL 创建对应的引擎"""
    db_url = settings.database_url

    if db_url.startswith("sqlite"):
        # SQLite 配置
        sqlite_connect_args = {
            "check_same_thread": False,
            "timeout": 60,
        }
        engine = create_engine(
            db_url,
            connect_args=sqlite_connect_args,
            echo=settings.debug,
            poolclass=QueuePool,
            pool_size=50,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
            pool_timeout=30,
        )
        # SQLite WAL 模式 + 性能优化
        from sqlalchemy import event
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-20000")
            cursor.execute("PRAGMA page_size=8192")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    elif db_url.startswith("postgresql"):
        # PostgreSQL 配置
        engine = create_engine(
            db_url,
            echo=settings.debug,
            poolclass=QueuePool,
            pool_size=20,          # PostgreSQL 连接更昂贵，减少池大小
            max_overflow=30,       # 突发流量时额外连接
            pool_pre_ping=True,    # 连接前检查有效性
            pool_recycle=3600,     # 1 小时回收连接
            pool_timeout=30,       # 获取连接超时
        )
    else:
        # 其他数据库使用默认配置
        engine = create_engine(db_url, echo=settings.debug)

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


def close_db_session(db: Session | None) -> None:
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
