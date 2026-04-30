#!/usr/bin/env python3
"""
CSV to Database Migration Tool
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
将 data/raw/ 目录下的 K 线 CSV 文件导入 stock_daily 数据库表。

用法:
    python tools/migrate_csv_to_db.py [--skip-existing]
    python tools/migrate_csv_to_db.py --no-skip-existing  # 强制重新导入
"""
import argparse
import sys
import time
from pathlib import Path

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.services.kline_service import save_daily_data


def get_db_url() -> str:
    """获取数据库 URL。"""
    db_path = PROJECT_ROOT / "data" / "db" / "stocktrade.db"
    return f"sqlite:///{db_path}"


def get_csv_files(raw_dir: Path) -> list[Path]:
    """获取所有 CSV 文件。"""
    return sorted(raw_dir.glob("*.csv"))


def get_existing_codes(engine) -> set[str]:
    """获取数据库中已有数据的股票代码。"""
    with engine.connect() as conn:
        result = conn.execute(text("SELECT DISTINCT code FROM stock_daily"))
        return {row[0] for row in result}


def migrate_csv_to_db(skip_existing: bool = True) -> None:
    """执行 CSV 到数据库的迁移。"""
    raw_dir = PROJECT_ROOT / "data" / "raw"
    db_url = get_db_url()

    if not raw_dir.exists():
        print(f"错误: 数据目录不存在: {raw_dir}")
        sys.exit(1)

    csv_files = get_csv_files(raw_dir)
    if not csv_files:
        print("未找到 CSV 文件")
        return

    print(f"找到 {len(csv_files)} 个 CSV 文件")
    print(f"数据库: {db_url}")

    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)

    existing_codes: set[str] = set()
    if skip_existing:
        existing_codes = get_existing_codes(engine)
        print(f"数据库中已有 {len(existing_codes)} 只股票的数据（将跳过）")

    total_rows = 0
    processed = 0
    skipped = 0
    failed = 0
    start_time = time.time()

    for i, csv_path in enumerate(csv_files, 1):
        code = csv_path.stem

        if skip_existing and code in existing_codes:
            skipped += 1
            continue

        try:
            df = pd.read_csv(csv_path)
            if df.empty or "date" not in df.columns:
                skipped += 1
                continue

            df["date"] = pd.to_datetime(df["date"])

            db = Session()
            try:
                rows = save_daily_data(db, code, df)
                total_rows += rows
                processed += 1
            finally:
                db.close()

            # 进度显示
            if processed % 100 == 0 or i == len(csv_files):
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                print(
                    f"  进度: {i}/{len(csv_files)} | "
                    f"已处理: {processed} | 跳过: {skipped} | "
                    f"失败: {failed} | 速度: {rate:.1f} 只/秒"
                )

        except Exception as e:
            failed += 1
            print(f"  失败 {code}: {e}")

    elapsed = time.time() - start_time
    print()
    print("=" * 50)
    print("迁移完成!")
    print(f"  总文件数: {len(csv_files)}")
    print(f"  已处理: {processed}")
    print(f"  已跳过: {skipped}")
    print(f"  失败: {failed}")
    print(f"  总写入行数: {total_rows}")
    print(f"  耗时: {elapsed:.1f} 秒")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="将 CSV K 线数据迁移到数据库")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="跳过数据库中已有数据的股票（默认启用）",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_false",
        dest="skip_existing",
        help="不跳过已有数据，强制重新导入",
    )
    args = parser.parse_args()
    migrate_csv_to_db(skip_existing=args.skip_existing)


if __name__ == "__main__":
    main()
