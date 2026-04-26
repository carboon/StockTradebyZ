"""
Database Configuration
~~~~~~~~~~~~~~~~~~~~~~
SQLite 数据库连接和会话管理
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

# SQLite 连接参数 - 优化并发性能
sqlite_connect_args = {
    "check_same_thread": False,
    "timeout": 30,  # 30秒锁超时
}

# 创建数据库引擎
if settings.database_url.startswith("sqlite"):
    engine = create_engine(
        settings.database_url,
        connect_args=sqlite_connect_args,
        echo=settings.debug,
        poolclass=StaticPool,  # SQLite使用静态连接池
    )
    # 启用 WAL 模式以支持更好的并发读写
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")  # 30秒
        cursor.close()
else:
    engine = create_engine(
        settings.database_url,
        echo=settings.debug,
    )

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """所有模型的基类 (SQLAlchemy 2.0)"""

    def to_dict(self) -> dict:
        """转换为字典"""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


def get_db() -> Generator[Session, None, None]:
    """
    数据库会话依赖注入
    用法: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
        db.close()
