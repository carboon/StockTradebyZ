#!/usr/bin/env python3
"""
批量导入 CSV 原始数据到数据库
"""
import os
import sys
from pathlib import Path
from datetime import datetime

# 添加项目路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import StockDaily
import pandas as pd


def import_csv_to_db(csv_dir: Path, db_path: Path) -> dict:
    """批量导入 CSV 数据到数据库

    Args:
        csv_dir: CSV 文件目录
        db_path: 数据库文件路径

    Returns:
        导入统计
    """
    # 创建数据库引擎
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url)

    # 获取所有 CSV 文件
    csv_files = list(csv_dir.glob("*.csv"))
    total = len(csv_files)

    if total == 0:
        return {"success": False, "message": "没有找到 CSV 文件"}

    print(f"找到 {total} 个 CSV 文件")
    print(f"数据库路径: {db_path}")

    imported = 0
    failed = 0
    skipped = 0
    total_rows = 0

    from tqdm import tqdm

    for csv_file in tqdm(csv_files, desc="导入进度"):
        code = csv_file.stem
        if not code or code == "000000":
            skipped += 1
            continue

        try:
            # 读取 CSV
            df = pd.read_csv(csv_file)

            # 检查必需列
            required_cols = ["date", "open", "close", "high", "low", "volume"]
            if not all(col in df.columns for col in required_cols):
                failed += 1
                continue

            # 标准化列名
            df = df[required_cols].copy()
            df["code"] = code
            df["trade_date"] = pd.to_datetime(df["date"]).dt.date

            # 删除已存在的数据
            with Session(engine) as db:
                db.query(StockDaily).filter(StockDaily.code == code).delete()

                # 批量插入
                records = []
                for _, row in df.iterrows():
                    records.append({
                        "code": code,
                        "trade_date": row["trade_date"],
                        "open": float(row["open"]),
                        "close": float(row["close"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "volume": float(row["volume"]),
                    })

                db.bulk_insert_mappings(StockDaily, records)
                db.commit()

            imported += 1
            total_rows += len(df)

        except Exception as e:
            failed += 1
            print(f"\n错误 {code}: {e}")

    return {
        "success": True,
        "total": total,
        "imported": imported,
        "failed": failed,
        "skipped": skipped,
        "total_rows": total_rows,
    }


if __name__ == "__main__":
    csv_dir = ROOT / "data" / "raw"
    db_dir = ROOT / "data" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "stocktrade.db"

    print("=" * 60)
    print("CSV 数据批量导入到数据库")
    print("=" * 60)

    result = import_csv_to_db(csv_dir, db_path)

    print("\n" + "=" * 60)
    print("导入完成！")
    print("=" * 60)
    print(f"总文件数: {result['total']}")
    print(f"成功导入: {result['imported']}")
    print(f"失败数量: {result['failed']}")
    print(f"跳过数量: {result['skipped']}")
    print(f"总行数: {result['total_rows']}")
    print("=" * 60)
