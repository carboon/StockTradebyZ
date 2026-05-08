#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pandas as pd
import tushare as ts

from app.config import settings
from app.database import SessionLocal
from app.services.kline_service import save_daily_data
from app.utils.stock_metadata import resolve_ts_code
from app.utils.tushare_rate_limit import acquire_tushare_slot

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"


def _fetch_daily_basic(pro: ts.pro_api, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    acquire_tushare_slot("daily_basic")
    frame = pro.daily_basic(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        fields="ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,free_share,circ_mv",
    )
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["date", "turnover_rate", "turnover_rate_f", "volume_ratio", "free_share", "circ_mv"])
    frame = frame.rename(columns={"trade_date": "date"})
    frame["date"] = pd.to_datetime(frame["date"])
    return frame[["date", "turnover_rate", "turnover_rate_f", "volume_ratio", "free_share", "circ_mv"]]


def _fetch_moneyflow(pro: ts.pro_api, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    acquire_tushare_slot("moneyflow")
    frame = pro.moneyflow(
        ts_code=ts_code,
        start_date=start_date,
        end_date=end_date,
        fields=(
            "ts_code,trade_date,buy_sm_amount,sell_sm_amount,"
            "buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,"
            "buy_elg_amount,sell_elg_amount,net_mf_amount"
        ),
    )
    if frame is None or frame.empty:
        return pd.DataFrame(
            columns=[
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
        )
    frame = frame.rename(columns={"trade_date": "date"})
    frame["date"] = pd.to_datetime(frame["date"])
    return frame[
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
    ]


def _backfill_one(pro: ts.pro_api, csv_path: Path) -> tuple[bool, str]:
    code = csv_path.stem.zfill(6)
    frame = pd.read_csv(csv_path)
    if frame.empty or "date" not in frame.columns:
        return False, f"{code} empty_or_invalid"

    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    start_date = frame["date"].iloc[0].strftime("%Y%m%d")
    end_date = frame["date"].iloc[-1].strftime("%Y%m%d")
    ts_code = resolve_ts_code(code)

    daily_basic = _fetch_daily_basic(pro, ts_code, start_date, end_date)
    moneyflow = _fetch_moneyflow(pro, ts_code, start_date, end_date)

    merged = frame.merge(daily_basic, on="date", how="left")
    merged = merged.merge(moneyflow, on="date", how="left")
    merged.to_csv(csv_path, index=False)

    with SessionLocal() as db:
        save_daily_data(db, code, merged)
    return True, f"{code} rows={len(merged)}"


def main() -> int:
    token = settings.tushare_token
    if not token:
        raise SystemExit("TUSHARE_TOKEN is not configured")
    if not RAW_DIR.exists():
        raise SystemExit(f"raw dir not found: {RAW_DIR}")

    pro = ts.pro_api(token)
    csv_files = sorted(RAW_DIR.glob("*.csv"))
    print(f"backfill_targets={len(csv_files)}")

    ok = 0
    failed = 0
    for index, csv_path in enumerate(csv_files, start=1):
        try:
            success, message = _backfill_one(pro, csv_path)
            if success:
                ok += 1
            else:
                failed += 1
            print(f"[{index}/{len(csv_files)}] {message}")
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(csv_files)}] {csv_path.stem} failed {exc}")

    print(f"ok={ok}")
    print(f"failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
