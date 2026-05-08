#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pandas as pd
import tushare as ts
from sqlalchemy import text

from app.config import settings
from app.database import engine, SessionLocal
from app.services.kline_service import save_daily_data
from app.utils.stock_metadata import resolve_ts_code
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
START_DATE = "20190101"


def get_missing_codes() -> list[str]:
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT s.code
            FROM stocks s
            LEFT JOIN (SELECT DISTINCT code FROM stock_daily) d ON s.code = d.code
            WHERE d.code IS NULL
            ORDER BY s.code
        """))
        return [str(row[0]).zfill(6) for row in rows]


def fetch_kline(pro: ts.pro_api, code: str, end_date: str) -> pd.DataFrame:
    ts_code = resolve_ts_code(code)
    acquire_tushare_slot("pro_bar")
    df = ts.pro_bar(
        ts_code=ts_code,
        adj="qfq",
        start_date=START_DATE,
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
    acquire_tushare_slot("daily_basic")
    daily_basic = pro.daily_basic(
        ts_code=ts_code,
        start_date=START_DATE,
        end_date=end_date,
        fields="ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,free_share,circ_mv",
    )
    if daily_basic is not None and not daily_basic.empty:
        daily_basic = daily_basic.rename(columns={"trade_date": "date"})
        daily_basic["date"] = pd.to_datetime(daily_basic["date"])
        frame = frame.merge(
            daily_basic[["date", "turnover_rate", "turnover_rate_f", "volume_ratio", "free_share", "circ_mv"]],
            on="date",
            how="left",
        )
    acquire_tushare_slot("moneyflow")
    moneyflow = pro.moneyflow(
        ts_code=ts_code,
        start_date=START_DATE,
        end_date=end_date,
        fields=(
            "ts_code,trade_date,buy_sm_amount,sell_sm_amount,"
            "buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,"
            "buy_elg_amount,sell_elg_amount,net_mf_amount"
        ),
    )
    if moneyflow is not None and not moneyflow.empty:
        moneyflow = moneyflow.rename(columns={"trade_date": "date"})
        moneyflow["date"] = pd.to_datetime(moneyflow["date"])
        frame = frame.merge(
            moneyflow[
                [
                    "date",
                    "buy_sm_amount",
                    "sell_sm_amount",
                    "buy_md_amount",
                    "sell_md_amount",
                    "buy_lg_amount",
                    "sell_lg_amount",
                    "buy_elg_amount",
                    "sell_elg_amount",
                    "net_mf_amount",
                ]
            ],
            on="date",
            how="left",
        )
    frame = frame.dropna(subset=["date", "open", "close", "high", "low", "volume"])
    frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return frame


def main() -> int:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    latest_trade_date = settings.environment and None
    # Prefer the configured backend runtime token and current market trade date.
    token = settings.tushare_token
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured")

    pro = ts.pro_api(token)

    acquire_tushare_slot("trade_cal")
    cal = pro.trade_cal(exchange="SSE", start_date="20260420", end_date="20260510")
    open_days = cal[cal["is_open"] == 1].sort_values("cal_date")
    end_date = str(open_days.iloc[-1]["cal_date"]) if not open_days.empty else "20260505"

    missing_codes = get_missing_codes()
    print(f"missing_codes_before={len(missing_codes)}")
    if not missing_codes:
        return 0

    success = 0
    empty = 0
    failed: list[tuple[str, str]] = []

    for index, code in enumerate(missing_codes, start=1):
        try:
            frame = fetch_kline(pro, code, end_date)
            if frame.empty:
                empty += 1
                print(f"[{index}/{len(missing_codes)}] {code} empty")
                continue

            csv_path = RAW_DIR / f"{code}.csv"
            frame.to_csv(csv_path, index=False)

            with SessionLocal() as db:
                save_daily_data(db, code, frame)

            success += 1
            print(f"[{index}/{len(missing_codes)}] {code} ok rows={len(frame)}")
        except Exception as exc:
            failed.append((code, str(exc)))
            print(f"[{index}/{len(missing_codes)}] {code} failed {exc}")

    print(f"success={success}")
    print(f"empty={empty}")
    print(f"failed={len(failed)}")
    if failed:
        for code, reason in failed[:20]:
            print(f"failed_sample {code} {reason}")

    remaining = get_missing_codes()
    print(f"missing_codes_after={len(remaining)}")
    if remaining:
        print(f"missing_codes_sample={remaining[:20]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
