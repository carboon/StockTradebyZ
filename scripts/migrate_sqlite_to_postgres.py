#!/usr/bin/env python3
"""
SQLite 到 PostgreSQL 数据迁移脚本

用法:
    # 从环境变量读取 PostgreSQL 连接
    export DATABASE_URL="postgresql://user:pass@host:port/db"
    python scripts/migrate_sqlite_to_postgres.py

    # 或直接指定
    python scripts/migrate_sqlite_to_postgres.py \\
        --sqlite /path/to/stocktrade.db \\
        --postgres "postgresql://user:pass@host:port/db"
"""
import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

# 添加项目路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


# 布尔字段映射表：SQLite 使用 0/1 存储布尔值，PostgreSQL 需要真正的布尔类型
BOOLEAN_COLUMNS = {
    "users": ["is_active"],
    "api_keys": ["is_active"],
    "watchlist": ["is_active"],
    "candidates": ["b1_passed"],
    "daily_b1_checks": ["zx_long_pos", "weekly_ma_aligned", "volume_healthy", "b1_passed"],
}


def migrate(sqlite_path: str, postgres_url: str) -> tuple:
    """执行迁移

    Args:
        sqlite_path: SQLite 数据库文件路径
        postgres_url: PostgreSQL 连接 URL

    Returns:
        (迁移统计, 表名列表)
    """
    # 创建引擎
    sqlite_engine = create_engine(f"sqlite:///{sqlite_path}")
    pg_engine = create_engine(postgres_url)

    # 获取所有表名
    with sqlite_engine.begin() as conn:
        result = conn.execute(text("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """))
        tables = [row[0] for row in result]

    print(f"找到 {len(tables)} 个表: {', '.join(tables)}")

    stats = {}

    for table in tables:
        print(f"\n迁移表: {table}")

        # 读取数据
        with sqlite_engine.begin() as src_conn:
            result = src_conn.execute(text(f"SELECT * FROM {table}"))
            rows = result.fetchall()
            columns = result.keys()

        if not rows:
            print(f"  跳过 (空表)")
            stats[table] = 0
            continue

        # 写入 PostgreSQL
        with pg_engine.begin() as dst_conn:
            # 先清空目标表
            dst_conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))

            # 批量插入
            for row in rows:
                values = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    # 处理布尔字段：SQLite 的 0/1 → PostgreSQL 的 true/false
                    if table in BOOLEAN_COLUMNS and col in BOOLEAN_COLUMNS[table]:
                        if val == 0:
                            values[col] = False
                        elif val == 1:
                            values[col] = True
                        else:
                            values[col] = val  # None 或其他值保持原样
                    # 处理日期类型
                    elif isinstance(val, datetime):
                        pass  # SQLAlchemy 会自动处理
                    elif val is None:
                        values[col] = None
                    else:
                        values[col] = val

                # 构建插入语句
                placeholders = ", ".join([f":{col}" for col in columns])
                insert_sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
                dst_conn.execute(text(insert_sql), values)

        stats[table] = len(rows)
        print(f"  完成: {len(rows)} 行")

    # 验证
    print("\n" + "=" * 50)
    print("迁移结果验证")
    print("=" * 50)

    with sqlite_engine.begin() as src_conn:
        src_result = src_conn.execute(text("""
            SELECT name, (SELECT COUNT(*) FROM pragma_table_info(name)) as cols
            FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """))
        table_info = {row[0]: row[1] for row in src_result}

    with pg_engine.begin() as dst_conn:
        for table in tables:
            result = dst_conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
            count = result.scalar()
            expected = stats[table]
            status = "✓" if count == expected else "✗"
            print(f"{status} {table}: {count} 行 (预期 {expected})")

    return stats, tables


def reset_sequences(postgres_url: str, tables: list):
    """重置 PostgreSQL 序列以确保自增 ID 正确工作

    Args:
        postgres_url: PostgreSQL 连接 URL
        tables: 需要处理的表名列表
    """
    print("\n" + "=" * 50)
    print("校准序列 (Sequences)")
    print("=" * 50)

    pg_engine = create_engine(postgres_url)
    inspector = inspect(pg_engine)

    with pg_engine.begin() as conn:
        for table in tables:
            try:
                # 获取主键约束
                pk_constraint = inspector.get_pk_constraint(table)

                if pk_constraint and pk_constraint.get("constrained_columns"):
                    pk_column = pk_constraint["constrained_columns"][0]
                    sequence_name = f"{table}_{pk_column}_seq"

                    # 获取表中最大的 ID 值
                    result = conn.execute(
                        text(f"SELECT COALESCE(MAX({pk_column}), 0) FROM {table}")
                    )
                    max_id = result.scalar()

                    if max_id > 0:
                        # 重置序列到 max_id + 1
                        conn.execute(
                            text(f"SELECT setval('{sequence_name}', {max_id}, true)")
                        )
                        print(f"  ✓ {sequence_name}: 重置到 {max_id + 1}")
                    else:
                        print(f"  - {table}: 空表，跳过")
                else:
                    print(f"  - {table}: 无主键，跳过")

            except Exception as e:
                print(f"  ⚠ {table}: 无法重置序列 - {e}")


def main():
    parser = argparse.ArgumentParser(description="SQLite 到 PostgreSQL 迁移")
    parser.add_argument(
        "--sqlite",
        default=str(ROOT / "data" / "db" / "stocktrade.db"),
        help="SQLite 数据库路径",
    )
    parser.add_argument(
        "--postgres",
        default=os.environ.get("DATABASE_URL"),
        help="PostgreSQL 连接 URL",
    )
    args = parser.parse_args()

    if not args.postgres:
        print("错误: 请指定 PostgreSQL 连接 URL (--postgres 或 DATABASE_URL 环境变量)")
        sys.exit(1)

    if not Path(args.sqlite).exists():
        print(f"错误: SQLite 数据库不存在: {args.sqlite}")
        sys.exit(1)

    print("=" * 50)
    print("SQLite → PostgreSQL 数据迁移")
    print("=" * 50)
    print(f"SQLite: {args.sqlite}")
    print(f"PostgreSQL: {args.postgres}")
    print("=" * 50)

    start = datetime.now()
    stats, tables = migrate(args.sqlite, args.postgres)

    # 重置序列
    reset_sequences(args.postgres, tables)

    elapsed = (datetime.now() - start).total_seconds()

    print("\n" + "=" * 50)
    print(f"迁移完成! 耗时: {elapsed:.1f} 秒")
    print("=" * 50)

    total = sum(stats.values())
    print(f"总计: {total} 行, {len(stats)} 个表")


if __name__ == "__main__":
    main()
