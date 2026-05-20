#!/usr/bin/env python3
"""
离线重新生成历史B1信号类型
==========================
更新 daily_b1_checks 表中的 b1_signal_type 字段
使用 HybridB1Selector 重新判断每条记录的信号类型
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# 添加项目路径
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "pipeline"))

from app.services.hybrid_b1_selector import HybridB1Selector, HybridB1Config
from app.database import SessionLocal
from app.models import DailyB1Check


def load_stock_data(code: str, data_dir: Path, days: int = 365) -> Optional[pd.DataFrame]:
    """从CSV加载股票数据"""
    csv_path = data_dir / f"{code}.csv"
    if not csv_path.exists():
        return None

    df = pd.read_csv(csv_path)
    if df.empty:
        return None

    df.columns = [c.lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    return df.tail(days).copy()


def update_b1_signal_types(
    batch_size: int = 100,
    limit: Optional[int] = None,
    data_dir: Optional[Path] = None,
) -> dict:
    """
    批量更新历史B1信号类型

    Args:
        batch_size: 每批处理的数量
        limit: 最大处理记录数（None表示全部）
        data_dir: 数据目录（None表示使用默认）

    Returns:
        统计信息字典
    """
    if data_dir is None:
        data_dir = ROOT / "data" / "raw"

    # 创建选择器
    cfg = HybridB1Config()
    selector = HybridB1Selector(cfg)

    stats = {
        "total": 0,
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "signal_types": {
            "old_b1": 0,
            "原始B1": 0,
            "回踩黄线B": 0,
            "回踩超级B": 0,
            "None": 0,
        },
    }

    with SessionLocal() as db:
        # 查询需要更新的记录
        query = db.query(DailyB1Check).filter(
            DailyB1Check.b1_passed == True,
            DailyB1Check.b1_signal_type == None,
        )

        if limit:
            query = query.limit(limit)

        total = query.count()
        stats["total"] = total

        if total == 0:
            print("没有需要更新的记录")
            return stats

        print(f"开始处理 {total} 条记录...")

        # 分批处理
        offset = 0
        while offset < total:
            records = query.offset(offset).limit(batch_size).all()

            for record in records:
                stats["processed"] += 1

                try:
                    # 加载股票数据
                    df = load_stock_data(record.code, data_dir, days=365)
                    if df is None:
                        stats["skipped"] += 1
                        print(f"  [{stats['processed']}/{total}] 跳过 {record.code}: 数据文件不存在")
                        continue

                    # 确保数据包含检查日期
                    check_date = pd.Timestamp(record.check_date).normalize()
                    df_before = df[df["date"] <= check_date].copy()
                    if len(df_before) < 60:
                        stats["skipped"] += 1
                        print(f"  [{stats['processed']}/{total}] 跳过 {record.code}: 数据不足")
                        continue

                    # 预计算指标
                    df_prepared = selector.prepare_df(df_before)

                    # 检查B1信号
                    result = selector.check_b1(df_prepared, record.code)

                    # 更新数据库
                    record.b1_signal_type = result.get("b1_signal_type")

                    # 统计
                    signal_type = record.b1_signal_type or "None"
                    if signal_type in stats["signal_types"]:
                        stats["signal_types"][signal_type] += 1
                    stats["updated"] += 1

                    print(f"  [{stats['processed']}/{total}] {record.code} @ {record.check_date}: {signal_type}")

                except Exception as e:
                    stats["errors"] += 1
                    print(f"  [{stats['processed']}/{total}] 错误 {record.code}: {e}")

            # 提交批次
            try:
                db.commit()
                print(f"批次提交成功: {stats['processed']}/{total}")
            except Exception as e:
                db.rollback()
                print(f"批次提交失败: {e}")
                break

            offset += batch_size

    # 打印统计
    print("\n" + "=" * 50)
    print("处理完成!")
    print("=" * 50)
    print(f"总计: {stats['total']} 条")
    print(f"已处理: {stats['processed']} 条")
    print(f"已更新: {stats['updated']} 条")
    print(f"跳过: {stats['skipped']} 条")
    print(f"错误: {stats['errors']} 条")
    print("\n信号类型分布:")
    for signal_type, count in stats["signal_types"].items():
        if count > 0:
            print(f"  - {signal_type}: {count} 条")

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="离线重新生成历史B1信号类型")
    parser.add_argument("--limit", type=int, help="最大处理记录数")
    parser.add_argument("--batch-size", type=int, default=100, help="每批处理数量")
    parser.add_argument("--data-dir", type=str, help="数据目录路径")

    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else None

    print("=" * 50)
    print("离线重新生成历史B1信号类型")
    print("=" * 50)
    print(f"数据目录: {data_dir or ROOT / 'data' / 'raw'}")
    print(f"批次大小: {args.batch_size}")
    if args.limit:
        print(f"处理上限: {args.limit}")
    print("=" * 50 + "\n")

    stats = update_b1_signal_types(
        batch_size=args.batch_size,
        limit=args.limit,
        data_dir=data_dir,
    )

    # 退出码
    sys.exit(0 if stats["errors"] == 0 else 1)


if __name__ == "__main__":
    main()
