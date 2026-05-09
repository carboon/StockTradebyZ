#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import tushare as ts
from sqlalchemy import text

from app.config import settings
from app.database import engine, SessionLocal
from app.services.daily_data_service import bulk_upsert_stock_daily
from app.utils.stock_metadata import resolve_ts_code
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
DEFAULT_START_DATE = "20190101"
DEFAULT_FLUSH_CODES = 20
DEFAULT_UPSERT_BATCH_SIZE = 5000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="修复 stock_daily 中缺失或样本不足的股票历史日线")
    parser.add_argument("--min-days", type=int, default=250, help="最少保留的交易日样本数，默认 250")
    parser.add_argument("--limit", type=int, default=0, help="最多修复多少只股票，0 表示不限制")
    parser.add_argument("--codes", nargs="*", default=None, help="只修复指定代码，支持多个 6 位股票代码")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE, help="历史抓取起始日期，格式 YYYYMMDD")
    parser.add_argument("--end-date", default="", help="历史抓取结束日期，默认自动取最近交易日")
    parser.add_argument("--flush-codes", type=int, default=DEFAULT_FLUSH_CODES, help="累计多少只股票后统一写库，默认 20")
    parser.add_argument("--upsert-batch-size", type=int, default=DEFAULT_UPSERT_BATCH_SIZE, help="数据库 UPSERT 的内部批大小，默认 5000")
    parser.add_argument("--write-csv", action="store_true", help="同时回写 data/raw/*.csv；默认关闭以提升修复速度")
    parser.add_argument("--dry-run", action="store_true", help="只输出待修复股票，不实际抓取")
    return parser.parse_args()


def normalize_codes(codes: list[str] | None) -> set[str]:
    return {
        str(code).zfill(6)
        for code in (codes or [])
        if str(code or "").strip()
    }


def get_stock_daily_counts() -> list[tuple[str, int]]:
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT s.code, COALESCE(d.day_count, 0) AS day_count
            FROM stocks s
            LEFT JOIN (
                SELECT code, COUNT(*) AS day_count
                FROM stock_daily
                GROUP BY code
            ) d ON s.code = d.code
            ORDER BY COALESCE(d.day_count, 0) ASC, s.code ASC
        """))
        return [(str(row[0]).zfill(6), int(row[1] or 0)) for row in rows]


def get_target_codes(*, min_days: int, codes: set[str] | None = None, limit: int = 0) -> list[tuple[str, int]]:
    targets: list[tuple[str, int]] = []
    for code, day_count in get_stock_daily_counts():
        if codes and code not in codes:
            continue
        if day_count >= min_days:
            continue
        targets.append((code, day_count))
        if limit > 0 and len(targets) >= limit:
            break
    return targets


def resolve_end_date(pro: ts.pro_api, requested: str) -> str:
    if requested:
        return str(requested).replace("-", "")

    today = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    acquire_tushare_slot("trade_cal")
    cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=today)
    open_days = cal[cal["is_open"] == 1].sort_values("cal_date")
    if open_days.empty:
        return today
    return str(open_days.iloc[-1]["cal_date"])


def fetch_kline(pro: ts.pro_api, code: str, *, start_date: str, end_date: str) -> pd.DataFrame:
    ts_code = resolve_ts_code(code)
    acquire_tushare_slot("pro_bar")
    df = ts.pro_bar(
        ts_code=ts_code,
        adj="qfq",
        start_date=start_date,
        end_date=end_date,
        freq="D",
        api=pro,
    )
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])

    frame = df.rename(columns={"trade_date": "date", "vol": "volume"})[
        ["date", "open", "close", "high", "low", "volume"]
    ].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    for column in ["open", "close", "high", "low", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "close", "high", "low", "volume"])
    frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return frame


def frame_to_records(code: str, frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []

    records: list[dict] = []
    normalized_code = str(code).zfill(6)
    for row in frame.itertuples(index=False):
        trade_date = pd.to_datetime(getattr(row, "date")).date()
        records.append({
            "code": normalized_code,
            "trade_date": trade_date,
            "open": float(getattr(row, "open")),
            "close": float(getattr(row, "close")),
            "high": float(getattr(row, "high")),
            "low": float(getattr(row, "low")),
            "volume": float(getattr(row, "volume")),
        })
    return records


def write_frame_csv(code: str, frame: pd.DataFrame) -> None:
    csv_path = RAW_DIR / f"{str(code).zfill(6)}.csv"
    export_frame = frame.copy()
    export_frame["date"] = pd.to_datetime(export_frame["date"], errors="coerce")
    export_frame = export_frame.dropna(subset=["date"])
    export_frame["date"] = export_frame["date"].dt.strftime("%Y-%m-%d")
    export_frame.to_csv(csv_path, index=False)


def flush_records(db, pending_records: list[dict], *, batch_size: int) -> dict[str, int]:
    if not pending_records:
        return {"written": 0, "failed": 0}
    result = bulk_upsert_stock_daily(db, pending_records, batch_size=batch_size)
    return {
        "written": int(result.get("inserted") or 0),
        "failed": int(result.get("failed") or 0),
    }


def main() -> int:
    args = parse_args()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    token = settings.tushare_token
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured")

    selected_codes = normalize_codes(args.codes)
    targets = get_target_codes(
        min_days=max(1, int(args.min_days)),
        codes=selected_codes or None,
        limit=max(0, int(args.limit)),
    )
    print(f"target_codes_before={len(targets)}")
    if targets:
        print(f"target_codes_sample={targets[:20]}")
    if not targets or args.dry_run:
        return 0

    pro = ts.pro_api(token)
    end_date = resolve_end_date(pro, args.end_date)
    start_date = str(args.start_date).replace("-", "")

    success = 0
    empty = 0
    failed: list[tuple[str, str]] = []
    db_failed_records = 0
    total_written = 0
    flush_codes = max(1, int(args.flush_codes))
    upsert_batch_size = max(1, int(args.upsert_batch_size))
    pending_records: list[dict] = []
    pending_codes = 0

    with SessionLocal() as db:
        for index, (code, before_count) in enumerate(targets, start=1):
            try:
                frame = fetch_kline(pro, code, start_date=start_date, end_date=end_date)
                if frame.empty:
                    empty += 1
                    print(f"[{index}/{len(targets)}] {code} empty before={before_count}")
                    continue

                if args.write_csv:
                    write_frame_csv(code, frame)

                pending_records.extend(frame_to_records(code, frame))
                pending_codes += 1

                if pending_codes >= flush_codes:
                    flush_result = flush_records(db, pending_records, batch_size=upsert_batch_size)
                    total_written += flush_result["written"]
                    db_failed_records += flush_result["failed"]
                    pending_records.clear()
                    pending_codes = 0

                success += 1
                print(f"[{index}/{len(targets)}] {code} ok before={before_count} after={len(frame)}")
            except Exception as exc:
                failed.append((code, str(exc)))
                print(f"[{index}/{len(targets)}] {code} failed {exc}")

        if pending_records:
            flush_result = flush_records(db, pending_records, batch_size=upsert_batch_size)
            total_written += flush_result["written"]
            db_failed_records += flush_result["failed"]

    print(f"success={success}")
    print(f"empty={empty}")
    print(f"failed={len(failed)}")
    print(f"db_written={total_written}")
    print(f"db_failed_records={db_failed_records}")
    if failed:
        for code, reason in failed[:20]:
            print(f"failed_sample {code} {reason}")

    remaining = get_target_codes(
        min_days=max(1, int(args.min_days)),
        codes=selected_codes or {code for code, _ in targets},
    )
    print(f"target_codes_after={len(remaining)}")
    if remaining:
        print(f"target_codes_remaining_sample={remaining[:20]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
