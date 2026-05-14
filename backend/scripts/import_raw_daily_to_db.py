#!/usr/bin/env python3
"""从 data/raw_daily 目录批量导入本地数据到数据库"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[2]
RAW_DAILY_DIR = ROOT / "data" / "raw_daily"

import sys
sys.path.insert(0, str(ROOT / "backend"))

from app.database import SessionLocal
from app.models import StockDaily
from app.services.daily_data_service import bulk_upsert_stock_daily


def import_jsonl(file_path: Path) -> int:
    """导入单个 jsonl 文件"""
    records = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                obj = json.loads(line)
                records.append(obj)

    if not records:
        return 0

    # 转换格式
    kline_records = []
    for item in records:
        kline_records.append({
            "code": item["code"],
            "trade_date": date.fromisoformat(item["trade_date"]) if isinstance(item["trade_date"], str) else item["trade_date"],
            "open": item.get("open"),
            "close": item.get("close"),
            "high": item.get("high"),
            "low": item.get("low"),
            "volume": item.get("volume"),
            "turnover_rate": item.get("turnover_rate"),
            "turnover_rate_f": item.get("turnover_rate_f"),
            "volume_ratio": item.get("volume_ratio"),
            "free_share": item.get("free_share"),
            "circ_mv": item.get("circ_mv"),
            "buy_sm_amount": item.get("buy_sm_amount"),
            "sell_sm_amount": item.get("sell_sm_amount"),
            "buy_md_amount": item.get("buy_md_amount"),
            "sell_md_amount": item.get("sell_md_amount"),
            "buy_lg_amount": item.get("buy_lg_amount"),
            "sell_lg_amount": item.get("sell_lg_amount"),
            "buy_elg_amount": item.get("buy_elg_amount"),
            "sell_elg_amount": item.get("sell_elg_amount"),
            "net_mf_amount": item.get("net_mf_amount"),
        })

    with SessionLocal() as db:
        result = bulk_upsert_stock_daily(db, kline_records)
        db.commit()
        return result.get("upserted", 0)


def main():
    if not RAW_DAILY_DIR.exists():
        print(f"目录不存在: {RAW_DAILY_DIR}")
        return 1

    jsonl_files = sorted(RAW_DAILY_DIR.glob("*.jsonl"))
    print(f"找到 {len(jsonl_files)} 个 jsonl 文件")

    total_imported = 0
    for index, file_path in enumerate(jsonl_files, start=1):
        print(f"[{index}/{len(jsonl_files)}] 导入 {file_path.name}")
        try:
            count = import_jsonl(file_path)
            total_imported += count
            print(f"  -> 导入 {count} 条记录")
        except Exception as e:
            print(f"  -> 失败: {e}")

    print(f"\n总计导入 {total_imported} 条记录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
