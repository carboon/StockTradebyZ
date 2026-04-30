#!/usr/bin/env python3
"""
Database Configuration Migration Script
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Updates application configuration to support PostgreSQL.

This script:
1. Updates config.py to support PostgreSQL connection string
2. Updates database.py for PostgreSQL-compatible settings
3. Creates example .env.postgres file
"""
import re
import sys
from pathlib import Path


def update_config_py(project_root: Path) -> bool:
    """Update config.py to support PostgreSQL database URL."""
    config_path = project_root / "backend" / "app" / "config.py"

    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        return False

    content = config_path.read_text(encoding="utf-8")

    # Check if already updated
    if "postgresql://" in content or "POSTGRES" in content:
        print("config.py already has PostgreSQL support")
        return True

    # Find the database_url property and update it
    old_property = '''    @property
    def database_url(self) -> str:
        """Database URL (absolute path)"""
        self.db_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.db_dir}/stocktrade.db"'''

    new_property = '''    @property
    def database_url(self) -> str:
        """Database URL (supports SQLite and PostgreSQL)"""
        # Check if PostgreSQL URL is provided via environment variable
        postgres_url = os.getenv("POSTGRES_DATABASE_URL")
        if postgres_url:
            return postgres_url

        # Default to SQLite for development
        self.db_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.db_dir}/stocktrade.db"'''

    if old_property in content:
        content = content.replace(old_property, new_property)

        # Add os import if not present
        if "import os" not in content:
            import_section = "from pathlib import Path\n"
            content = content.replace(import_section, f"{import_section}import os\n")

        config_path.write_text(content, encoding="utf-8")
        print("Updated config.py with PostgreSQL support")
        return True
    else:
        print("WARNING: Could not find database_url property in config.py")
        return False


def update_database_py(project_root: Path) -> bool:
    """Update database.py for better PostgreSQL compatibility."""
    db_path = project_root / "backend" / "app" / "database.py"

    if not db_path.exists():
        print(f"ERROR: {db_path} not found")
        return False

    content = db_path.read_text(encoding="utf-8")

    # Check if already updated
    if "postgresql" in content.lower():
        print("database.py already has PostgreSQL support")
        return True

    # Update imports to include URL parsing
    old_imports = """from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings"""

    new_imports = """from contextlib import contextmanager
from typing import Generator
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from app.config import settings"""

    if old_imports in content:
        content = content.replace(old_imports, new_imports)

        # Update engine creation logic
        old_engine = """# 创建数据库引擎
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
    )"""

        new_engine = '''# 创建数据库引擎
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
elif settings.database_url.startswith("postgresql"):
    # PostgreSQL 配置
    parsed = urlparse(settings.database_url)
    engine = create_engine(
        settings.database_url,
        echo=settings.debug,
        poolclass=QueuePool,
        pool_size=5,  # 连接池大小
        max_overflow=10,  # 最大溢出连接数
        pool_pre_ping=True,  # 连接健康检查
        pool_recycle=3600,  # 1小时回收连接
    )
else:
    engine = create_engine(
        settings.database_url,
        echo=settings.debug,
    )'''

        content = content.replace(old_engine, new_engine)
        db_path.write_text(content, encoding="utf-8")
        print("Updated database.py with PostgreSQL support")
        return True
    else:
        print("WARNING: Could not find engine creation code in database.py")
        return False


def create_example_env(project_root: Path) -> bool:
    """Create example .env.postgres file."""
    env_path = project_root / ".env.postgres"

    if env_path.exists():
        print(".env.postgres already exists")
        return True

    content = """# PostgreSQL Database Configuration
# Copy this file to .env and update with your actual values

# Database URL format: postgresql://user:password@host:port/database
# Example with local PostgreSQL:
POSTGRES_DATABASE_URL=postgresql://stocktrade:change_me@localhost:5432/stocktrade

# Example with remote PostgreSQL (e.g., AWS RDS, Heroku, etc.):
# POSTGRES_DATABASE_URL=postgresql://user:password@host:5432/database

# Other application settings (copy from existing .env)
APP_NAME=StockTrader
DEBUG=False
SECRET_KEY=change-me-in-production-use-a-random-string

# Tushare configuration
TUSHARE_TOKEN=your_tushare_token_here

# LLM API Keys (optional)
ZHIPUAI_API_KEY=
DASHSCOPE_API_KEY=
GEMINI_API_KEY=

# Analysis configuration
DEFAULT_REVIEWER=quant
MIN_SCORE_THRESHOLD=4.0

# Authentication configuration
ACCESS_TOKEN_EXPIRE_MINUTES=1440
ADMIN_DEFAULT_USERNAME=admin
ADMIN_DEFAULT_PASSWORD=admin123

# Environment
ENVIRONMENT=production
"""

    env_path.write_text(content, encoding="utf-8")
    print(f"Created .env.postgres example file")
    return True


def create_postgres_setup_script(project_root: Path) -> bool:
    """Create SQL script for PostgreSQL database setup."""
    sql_path = project_root / "scripts" / "setup_postgres.sql"

    if sql_path.exists():
        print("setup_postgres.sql already exists")
        return True

    sql_path.parent.mkdir(parents=True, exist_ok=True)

    content = """-- PostgreSQL Database Setup Script for StockTradebyZ
-- Run this as postgres superuser to create the database and user

-- Create database user
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'stocktrade') THEN
        CREATE DATABASE stocktrade;
    END IF;
END $$;

-- Create user and grant privileges
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'stocktrade') THEN
        CREATE USER stocktrade WITH PASSWORD 'change_me';
    END IF;
END $$;

-- Grant privileges on database
GRANT ALL PRIVILEGES ON DATABASE stocktrade TO stocktrade;

-- Connect to the stocktrade database and grant schema privileges
\\c stocktrade

GRANT ALL ON SCHEMA public TO stocktrade;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO stocktrade;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO stocktrade;

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Print success message
SELECT 'PostgreSQL database setup complete!' AS status;
"""

    sql_path.write_text(content, encoding="utf-8")
    print(f"Created setup_postgres.sql")
    return True


def main():
    project_root = Path(__file__).parent.parent

    print("Updating configuration for PostgreSQL support...")
    print(f"Project root: {project_root}")
    print("-" * 60)

    results = {
        "config.py": update_config_py(project_root),
        "database.py": update_database_py(project_root),
        ".env.postgres": create_example_env(project_root),
        "setup_postgres.sql": create_postgres_setup_script(project_root),
    }

    print("-" * 60)
    print("\nResults:")
    for name, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {name}: {status}")

    if all(results.values()):
        print("\nAll configuration updates completed successfully!")
        print("\nNext steps:")
        print("  1. Set up PostgreSQL database: psql -U postgres -f scripts/setup_postgres.sql")
        print("  2. Copy .env.postgres to .env and update with your values")
        print("  3. Run: python scripts/migrate_data.py to migrate data")
        return 0
    else:
        print("\nSome updates failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
