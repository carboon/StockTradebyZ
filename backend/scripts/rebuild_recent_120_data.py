#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
import logging
import multiprocessing
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import pandas as pd
import tushare as ts
from sqlalchemy import func, or_

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

if (
    os.environ.get("STOCKTRADE_REBUILD_BOOTSTRAPPED") != "1"
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
):
    env = dict(os.environ)
    env["STOCKTRADE_REBUILD_BOOTSTRAPPED"] = "1"
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]], env)

pythonpath_entries = [entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry]
for required_path in (str(ROOT), str(BACKEND)):
    if required_path not in pythonpath_entries:
        pythonpath_entries.append(required_path)
    if required_path not in sys.path:
        sys.path.insert(0, required_path)
os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

from app.config import settings
from app.database import SessionLocal, engine
from app.models import (
    AnalysisResult,
    Candidate,
    Config,
    CurrentHotAnalysisResult,
    CurrentHotCandidate,
    CurrentHotIntradaySnapshot,
    CurrentHotRun,
    DailyB1Check,
    DailyB1CheckDetail,
    Stock,
    StockActivePoolRank,
    StockDaily,
    TomorrowStarRun,
)
from app.services.active_pool_rank_service import active_pool_rank_service
from app.services.analysis_service import analysis_service
from app.services.current_hot_service import CurrentHotService
from app.services.daily_batch_update_service import DailyBatchUpdateService
from app.services.tomorrow_star_window_service import TomorrowStarWindowService
from app.services.tushare_service import TushareService
from app.schema_migrations import apply_startup_sql_migrations
from app.utils.system_resources import detect_system_resources, recommend_process_workers
from app.utils.tushare_rate_limit import acquire_tushare_slot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


CRITICAL_CSV_COLUMNS = {
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
}

RAW_CSV_SYNC_COLUMNS = [
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "free_share",
    "circ_mv",
    "buy_sm_amount",
    "sell_sm_amount",
    "buy_md_amount",
    "sell_md_amount",
    "buy_lg_amount",
    "sell_lg_amount",
    "buy_elg_amount",
    "sell_elg_amount",
    "net_mf_amount",
    "code",
]

DEFAULT_AUTO_MAX_WORKERS = 4
DEFAULT_RESERVE_CPUS = 1
DEFAULT_MEMORY_PER_WORKER_MB = 900


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "清理并重建最近 N 个交易日的数据：检查 CSV/DB，按需补 Tushare，"
            "重建明日之星、当前热盘和可选单股诊断历史。"
        )
    )
    parser.add_argument("--window-size", type=int, default=120, help="重建最近多少个交易日，默认 120")
    parser.add_argument(
        "--warmup-trade-days",
        type=int,
        default=140,
        help="额外补齐多少个 warmup 交易日行情，保证 120 日窗口有足够历史样本，默认 140",
    )
    parser.add_argument("--reviewer", default="quant", help="复核器，默认 quant")
    parser.add_argument("--end-date", default="", help="最新交易日上限 YYYY-MM-DD / YYYYMMDD，默认今天之前最近开市日")
    parser.add_argument(
        "--min-db-records-per-day",
        type=int,
        default=3500,
        help="判断单个交易日 DB 是否基本完整的最低行数，默认 3500",
    )
    parser.add_argument(
        "--min-csv-records-per-day",
        type=int,
        default=3500,
        help="判断单个交易日 CSV 是否基本完整的最低行数，默认 3500",
    )
    parser.add_argument(
        "--min-metric-fill-ratio",
        type=float,
        default=0.95,
        help="判断换手率/量比是否完整的最低非空比例，默认 0.95",
    )
    parser.add_argument("--force-refetch", action="store_true", help="不做完整性判断，强制重拉整个数据窗口")
    parser.add_argument("--skip-data-fetch", action="store_true", help="跳过 Tushare 数据补齐，只重建派生数据")
    parser.add_argument("--skip-clean", action="store_true", help="不预清理派生表，直接重建覆盖")
    parser.add_argument("--skip-tomorrow-star", action="store_true", help="跳过明日之星重建")
    parser.add_argument("--skip-current-hot", action="store_true", help="跳过当前热盘重建")
    parser.add_argument(
        "--diagnosis-scope",
        choices=("none", "existing", "current-hot", "both", "candidates", "all"),
        default="both",
        help=(
            "单股诊断历史重建范围：none 不重建；existing 重建已有诊断股票；"
            "current-hot 重建当前热盘股票；both 两者；candidates 重建本轮明日之星候选股票；"
            "all 重建 stocks 表全部股票。默认 both"
        ),
    )
    parser.add_argument("--diagnosis-limit", type=int, default=0, help="限制诊断重建股票数量，0 表示不限")
    parser.add_argument(
        "--workers",
        default="auto",
        help="补数并发进程数；默认 auto，根据 CPU/内存保守估算，也可填写 1/2/4 等整数",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_AUTO_MAX_WORKERS,
        help=f"auto 模式的最大并发进程数，默认 {DEFAULT_AUTO_MAX_WORKERS}",
    )
    parser.add_argument(
        "--reserve-cpus",
        type=int,
        default=DEFAULT_RESERVE_CPUS,
        help=f"auto 模式预留给系统/数据库的 CPU 核数，默认 {DEFAULT_RESERVE_CPUS}",
    )
    parser.add_argument(
        "--memory-per-worker-mb",
        type=int,
        default=DEFAULT_MEMORY_PER_WORKER_MB,
        help=f"auto 模式估算每个补数进程占用内存（MB），默认 {DEFAULT_MEMORY_PER_WORKER_MB}",
    )
    parser.add_argument("--dry-run", action="store_true", help="只输出计划，不执行清理、抓取和重建")
    parser.add_argument("--yes", action="store_true", help="确认执行清理和重建")
    return parser.parse_args()


def normalize_tushare_date(value: str | None) -> str:
    if not value:
        return datetime.now().strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return datetime.now().strftime("%Y%m%d")
    return text.replace("-", "")


def get_recent_trade_dates(pro: ts.pro_api, *, total_days: int, end_date: str = "") -> list[str]:
    end_text = normalize_tushare_date(end_date)
    end_dt = datetime.strptime(end_text, "%Y%m%d")
    lookback_days = max(365, total_days * 3)
    start_dt = end_dt - timedelta(days=lookback_days)

    while True:
        acquire_tushare_slot("trade_cal")
        cal = pro.trade_cal(
            exchange="SSE",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_text,
        )
        if cal is not None and not cal.empty:
            open_days = cal[cal["is_open"] == 1].sort_values("cal_date")
            dates = [pd.to_datetime(item).date().isoformat() for item in open_days["cal_date"].tolist()]
            if len(dates) >= total_days:
                return dates[-total_days:]

        lookback_days *= 2
        if lookback_days > 3650:
            raise RuntimeError(f"无法从 Tushare 交易日历获取足够交易日: need={total_days}")
        start_dt = end_dt - timedelta(days=lookback_days)


def get_stock_codes() -> list[str]:
    with SessionLocal() as db:
        return [
            str(code).zfill(6)
            for code, in db.query(Stock.code).order_by(Stock.code.asc()).all()
            if str(code or "").strip()
        ]


def sync_stock_list() -> int:
    with SessionLocal() as db:
        return TushareService().sync_stock_list_to_db(db)


def db_incomplete_dates(
    trade_dates: list[str],
    *,
    min_records: int,
    min_metric_fill_ratio: float,
) -> tuple[set[str], dict[str, Any]]:
    if not trade_dates:
        return set(), {}

    date_objs = [date.fromisoformat(item) for item in trade_dates]
    with SessionLocal() as db:
        rows = (
            db.query(
                StockDaily.trade_date,
                func.count(StockDaily.id).label("row_count"),
                func.count(StockDaily.turnover_rate).label("turnover_count"),
                func.count(StockDaily.volume_ratio).label("volume_ratio_count"),
            )
            .filter(StockDaily.trade_date.in_(date_objs))
            .group_by(StockDaily.trade_date)
            .all()
        )

    stats = {
        trade_date.isoformat(): {
            "row_count": int(row_count or 0),
            "turnover_count": int(turnover_count or 0),
            "volume_ratio_count": int(volume_ratio_count or 0),
        }
        for trade_date, row_count, turnover_count, volume_ratio_count in rows
    }

    incomplete: set[str] = set()
    for trade_date in trade_dates:
        item = stats.get(trade_date, {"row_count": 0, "turnover_count": 0, "volume_ratio_count": 0})
        row_count = int(item["row_count"])
        if row_count < min_records:
            incomplete.add(trade_date)
            continue
        metric_count = min(int(item["turnover_count"]), int(item["volume_ratio_count"]))
        if row_count > 0 and metric_count / row_count < min_metric_fill_ratio:
            incomplete.add(trade_date)

    return incomplete, stats


def csv_incomplete_dates(
    trade_dates: list[str],
    stock_codes: list[str],
    *,
    min_records: int,
    min_metric_fill_ratio: float,
) -> tuple[set[str], dict[str, Any]]:
    raw_dir = Path(settings.raw_data_dir)
    if not raw_dir.is_absolute():
        raw_dir = ROOT / raw_dir
    if not raw_dir.exists():
        return set(trade_dates), {"raw_dir": str(raw_dir), "missing_raw_dir": True}

    target_dates = {date.fromisoformat(item) for item in trade_dates}
    row_count_by_date: dict[date, int] = defaultdict(int)
    metric_count_by_date: dict[date, int] = defaultdict(int)
    missing_file_count = 0
    missing_column_files: list[str] = []
    failed_files: list[str] = []

    for code in stock_codes:
        csv_path = raw_dir / f"{code}.csv"
        if not csv_path.exists():
            missing_file_count += 1
            continue
        try:
            header = pd.read_csv(csv_path, nrows=0)
            columns = set(str(column) for column in header.columns)
            if not CRITICAL_CSV_COLUMNS.issubset(columns):
                missing_column_files.append(code)
                continue
            frame = pd.read_csv(csv_path, usecols=["date", "turnover_rate", "volume_ratio"])
            if frame.empty:
                continue
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
            frame = frame[frame["date"].isin(target_dates)]
            if frame.empty:
                continue
            grouped_count = frame.groupby("date").size()
            grouped_metric = frame[
                frame["turnover_rate"].notna() & frame["volume_ratio"].notna()
            ].groupby("date").size()
            for trade_date, count in grouped_count.items():
                row_count_by_date[trade_date] += int(count)
            for trade_date, count in grouped_metric.items():
                metric_count_by_date[trade_date] += int(count)
        except Exception as exc:
            failed_files.append(f"{code}: {exc}")

    if missing_column_files:
        return set(trade_dates), {
            "raw_dir": str(raw_dir),
            "missing_file_count": missing_file_count,
            "missing_column_file_count": len(missing_column_files),
            "missing_column_samples": missing_column_files[:20],
            "failed_file_samples": failed_files[:20],
            "reason": "csv_missing_required_columns",
        }

    incomplete: set[str] = set()
    stats: dict[str, Any] = {}
    for trade_date_text in trade_dates:
        trade_date = date.fromisoformat(trade_date_text)
        row_count = int(row_count_by_date.get(trade_date, 0))
        metric_count = int(metric_count_by_date.get(trade_date, 0))
        stats[trade_date_text] = {
            "row_count": row_count,
            "metric_count": metric_count,
        }
        if row_count < min_records:
            incomplete.add(trade_date_text)
            continue
        if row_count > 0 and metric_count / row_count < min_metric_fill_ratio:
            incomplete.add(trade_date_text)

    stats["_meta"] = {
        "raw_dir": str(raw_dir),
        "missing_file_count": missing_file_count,
        "failed_file_samples": failed_files[:20],
    }
    return incomplete, stats


def detect_data_fetch_plan(args: argparse.Namespace, data_dates: list[str], stock_codes: list[str]) -> dict[str, Any]:
    if args.force_refetch:
        return {
            "fetch_dates": data_dates,
            "full_fetch_dates": data_dates,
            "metric_fetch_dates": [],
            "csv_sync_dates": data_dates,
            "db_incomplete_dates": data_dates,
            "csv_incomplete_dates": data_dates,
            "db_stats": {},
            "csv_stats": {"reason": "force_refetch"},
        }

    db_missing, db_stats = db_incomplete_dates(
        data_dates,
        min_records=max(1, int(args.min_db_records_per_day)),
        min_metric_fill_ratio=max(0.0, min(float(args.min_metric_fill_ratio), 1.0)),
    )
    csv_missing, csv_stats = csv_incomplete_dates(
        data_dates,
        stock_codes,
        min_records=max(1, int(args.min_csv_records_per_day)),
        min_metric_fill_ratio=max(0.0, min(float(args.min_metric_fill_ratio), 1.0)),
    )
    min_records = max(1, int(args.min_db_records_per_day))
    min_metric_fill_ratio = max(0.0, min(float(args.min_metric_fill_ratio), 1.0))
    full_fetch_dates: set[str] = set()
    metric_fetch_dates: set[str] = set()
    for trade_date in db_missing:
        item = db_stats.get(trade_date, {"row_count": 0, "turnover_count": 0, "volume_ratio_count": 0})
        row_count = int(item.get("row_count") or 0)
        if row_count < min_records:
            full_fetch_dates.add(trade_date)
            continue
        metric_count = min(int(item.get("turnover_count") or 0), int(item.get("volume_ratio_count") or 0))
        if row_count > 0 and metric_count / row_count < min_metric_fill_ratio:
            metric_fetch_dates.add(trade_date)

    fetch_dates = sorted(full_fetch_dates | metric_fetch_dates)
    csv_sync_dates = sorted(csv_missing | full_fetch_dates | metric_fetch_dates)
    return {
        "fetch_dates": fetch_dates,
        "full_fetch_dates": sorted(full_fetch_dates),
        "metric_fetch_dates": sorted(metric_fetch_dates),
        "csv_sync_dates": csv_sync_dates,
        "db_incomplete_dates": sorted(db_missing),
        "csv_incomplete_dates": sorted(csv_missing),
        "db_stats": db_stats,
        "csv_stats": csv_stats,
    }


def _raw_csv_dir() -> Path:
    raw_dir = Path(settings.raw_data_dir)
    if not raw_dir.is_absolute():
        raw_dir = ROOT / raw_dir
    return raw_dir


def _optional_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _write_stock_raw_csv(raw_dir: Path, code: str, rows: list[dict[str, Any]]) -> bool:
    if not rows:
        return False

    csv_path = raw_dir / f"{code}.csv"
    next_frame = pd.DataFrame(rows)
    for column in RAW_CSV_SYNC_COLUMNS:
        if column not in next_frame.columns:
            next_frame[column] = None
    next_frame = next_frame[RAW_CSV_SYNC_COLUMNS].copy()
    next_frame["date"] = pd.to_datetime(next_frame["date"], errors="coerce")
    next_frame = next_frame.dropna(subset=["date"])
    if next_frame.empty:
        return False

    if csv_path.exists():
        try:
            existing = pd.read_csv(csv_path)
            if not existing.empty:
                if "date" not in existing.columns:
                    existing = pd.DataFrame()
                else:
                    existing["date"] = pd.to_datetime(existing["date"], errors="coerce")
                    existing = existing.dropna(subset=["date"])
        except Exception as exc:
            print(f"[csv] read failed, overwrite {csv_path}: {exc}")
            existing = pd.DataFrame()
    else:
        existing = pd.DataFrame()

    columns = list(dict.fromkeys([*existing.columns.tolist(), *RAW_CSV_SYNC_COLUMNS]))
    for column in columns:
        if column not in existing.columns:
            existing[column] = None
        if column not in next_frame.columns:
            next_frame[column] = None

    if existing.empty:
        output = next_frame[columns].copy()
    else:
        output = pd.concat([existing[columns], next_frame[columns]], ignore_index=True)
    output = output.drop_duplicates(subset="date", keep="last").sort_values("date").reset_index(drop=True)
    output["date"] = pd.to_datetime(output["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    output.to_csv(csv_path, index=False)
    return True


def sync_raw_csv_from_db(trade_dates: list[str]) -> dict[str, Any]:
    """按股票一次性回写 raw CSV，避免按交易日重复读写几千个 CSV 文件。"""
    if not trade_dates:
        return {"success": True, "trade_dates_count": 0, "updated_files": 0, "synced_rows": 0}

    raw_dir = _raw_csv_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)
    date_values = date_objects(trade_dates)
    updated_files = 0
    synced_rows = 0
    current_code: str | None = None
    current_rows: list[dict[str, Any]] = []

    def flush_current() -> None:
        nonlocal updated_files, synced_rows, current_rows, current_code
        if current_code is None or not current_rows:
            return
        if _write_stock_raw_csv(raw_dir, current_code, current_rows):
            updated_files += 1
            synced_rows += len(current_rows)
            if updated_files % 500 == 0:
                print(f"[csv] synced {updated_files} stock files, {synced_rows} rows")
        current_rows = []

    with SessionLocal() as db:
        query = (
            db.query(
                StockDaily.code,
                StockDaily.trade_date,
                StockDaily.open,
                StockDaily.close,
                StockDaily.high,
                StockDaily.low,
                StockDaily.volume,
                StockDaily.turnover_rate,
                StockDaily.turnover_rate_f,
                StockDaily.volume_ratio,
                StockDaily.free_share,
                StockDaily.circ_mv,
                StockDaily.buy_sm_amount,
                StockDaily.sell_sm_amount,
                StockDaily.buy_md_amount,
                StockDaily.sell_md_amount,
                StockDaily.buy_lg_amount,
                StockDaily.sell_lg_amount,
                StockDaily.buy_elg_amount,
                StockDaily.sell_elg_amount,
                StockDaily.net_mf_amount,
            )
            .filter(StockDaily.trade_date.in_(date_values))
            .order_by(StockDaily.code.asc(), StockDaily.trade_date.asc())
            .yield_per(10000)
        )
        for row in query:
            code = str(row.code).zfill(6)
            if current_code is None:
                current_code = code
            elif code != current_code:
                flush_current()
                current_code = code

            current_rows.append(
                {
                    "date": row.trade_date,
                    "open": _optional_float(row.open),
                    "close": _optional_float(row.close),
                    "high": _optional_float(row.high),
                    "low": _optional_float(row.low),
                    "volume": _optional_float(row.volume),
                    "turnover_rate": _optional_float(row.turnover_rate),
                    "turnover_rate_f": _optional_float(row.turnover_rate_f),
                    "volume_ratio": _optional_float(row.volume_ratio),
                    "free_share": _optional_float(row.free_share),
                    "circ_mv": _optional_float(row.circ_mv),
                    "buy_sm_amount": _optional_float(row.buy_sm_amount),
                    "sell_sm_amount": _optional_float(row.sell_sm_amount),
                    "buy_md_amount": _optional_float(row.buy_md_amount),
                    "sell_md_amount": _optional_float(row.sell_md_amount),
                    "buy_lg_amount": _optional_float(row.buy_lg_amount),
                    "sell_lg_amount": _optional_float(row.sell_lg_amount),
                    "buy_elg_amount": _optional_float(row.buy_elg_amount),
                    "sell_elg_amount": _optional_float(row.sell_elg_amount),
                    "net_mf_amount": _optional_float(row.net_mf_amount),
                    "code": code,
                }
            )

    flush_current()
    return {
        "success": True,
        "trade_dates_count": len(trade_dates),
        "updated_files": updated_files,
        "synced_rows": synced_rows,
        "raw_dir": str(raw_dir),
    }


def _fetch_trade_date_metric_frame(pro: Any, trade_date: str) -> pd.DataFrame:
    normalized = trade_date.replace("-", "")
    acquire_tushare_slot("daily_basic")
    daily_basic = pro.daily_basic(
        trade_date=normalized,
        fields="ts_code,trade_date,turnover_rate,turnover_rate_f,volume_ratio,free_share,circ_mv",
    )
    if daily_basic is None:
        daily_basic = pd.DataFrame()

    acquire_tushare_slot("moneyflow")
    moneyflow = pro.moneyflow(
        trade_date=normalized,
        fields=(
            "ts_code,trade_date,buy_sm_amount,sell_sm_amount,"
            "buy_md_amount,sell_md_amount,buy_lg_amount,sell_lg_amount,"
            "buy_elg_amount,sell_elg_amount,net_mf_amount"
        ),
    )
    if moneyflow is None:
        moneyflow = pd.DataFrame()

    if daily_basic.empty and moneyflow.empty:
        return pd.DataFrame()
    if daily_basic.empty:
        frame = moneyflow.copy()
    elif moneyflow.empty:
        frame = daily_basic.copy()
    else:
        frame = daily_basic.merge(moneyflow, on=["ts_code", "trade_date"], how="outer")

    frame["code"] = frame["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    ).dt.date
    frame = frame.dropna(subset=["trade_date"])
    return frame.sort_values(["trade_date", "code"]).reset_index(drop=True)


def _update_db_metrics_from_frame(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0

    metric_columns = [
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "free_share",
        "circ_mv",
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
    trade_date = frame["trade_date"].iloc[0]
    codes = [str(item).zfill(6) for item in frame["code"].dropna().astype(str).unique().tolist()]
    if not codes:
        return 0

    with SessionLocal() as db:
        id_by_code = {
            str(code).zfill(6): row_id
            for row_id, code in (
                db.query(StockDaily.id, StockDaily.code)
                .filter(StockDaily.trade_date == trade_date, StockDaily.code.in_(codes))
                .all()
            )
        }
        mappings: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            code = str(row["code"]).zfill(6)
            row_id = id_by_code.get(code)
            if row_id is None:
                continue
            mapping: dict[str, Any] = {"id": row_id}
            for column in metric_columns:
                if column in frame.columns and pd.notna(row.get(column)):
                    mapping[column] = float(row[column])
            if len(mapping) > 1:
                mappings.append(mapping)
        if not mappings:
            return 0
        db.bulk_update_mappings(StockDaily, mappings)
        db.commit()
    return len(mappings)


def _dispose_inherited_engine() -> None:
    try:
        engine.dispose()
    except Exception:
        pass


def _metric_fetch_job(trade_date: str) -> dict[str, Any]:
    _dispose_inherited_engine()
    pro = ts.pro_api(settings.tushare_token)
    frame = _fetch_trade_date_metric_frame(pro, trade_date)
    updated_count = _update_db_metrics_from_frame(frame)
    return {
        "ok": not frame.empty,
        "trade_date": trade_date,
        "record_count": int(len(frame.index)),
        "updated_count": updated_count,
    }


def _trade_date_fetch_job(trade_date: str) -> dict[str, Any]:
    _dispose_inherited_engine()
    with DailyBatchUpdateService() as service:
        return service.update_trade_date(
            trade_date,
            source="recent_120_full_rebuild",
            sync_raw_csv=False,
        )


def resolve_parallel_workers(
    requested_workers: str | int,
    *,
    task_count: int,
    max_workers: int,
    reserve_cpus: int,
    memory_per_worker_mb: int,
) -> dict[str, Any]:
    resources = detect_system_resources()
    requested_text = str(requested_workers or "auto").strip().lower()
    resolved_max_workers = max(1, int(max_workers or 1))

    if task_count <= 1:
        return {
            "mode": "sequential",
            "requested": requested_text,
            "resolved_workers": 1,
            "task_count": max(0, int(task_count)),
            "parallel_enabled": False,
            "reason": "task_count<=1",
            "cpu_count": resources.cpu_count,
            "total_memory_mb": resources.total_memory_mb,
            "available_memory_mb": resources.available_memory_mb,
            "max_workers": resolved_max_workers,
        }

    if requested_text in {"", "auto"}:
        resolved_workers = recommend_process_workers(
            resources,
            max_workers=resolved_max_workers,
            reserve_cpus=max(0, int(reserve_cpus)),
            memory_per_worker_bytes=max(1, int(memory_per_worker_mb)) * 1024 * 1024,
        )
        mode = "auto"
    else:
        try:
            manual_workers = max(1, int(requested_text))
        except ValueError as exc:
            raise SystemExit(f"--workers 参数非法: {requested_workers}") from exc
        resolved_workers = min(manual_workers, resolved_max_workers)
        mode = "manual"

    resolved_workers = max(1, min(int(task_count), int(resolved_workers)))
    return {
        "mode": mode,
        "requested": requested_text,
        "resolved_workers": resolved_workers,
        "task_count": int(task_count),
        "parallel_enabled": resolved_workers > 1,
        "reason": "resource_based" if mode == "auto" else "manual_override",
        "cpu_count": resources.cpu_count,
        "total_memory_mb": resources.total_memory_mb,
        "available_memory_mb": resources.available_memory_mb,
        "max_workers": resolved_max_workers,
        "reserve_cpus": max(0, int(reserve_cpus)),
        "memory_per_worker_mb": max(1, int(memory_per_worker_mb)),
    }


def summarize_update_mode(database_summary: dict[str, Any], fetch_plan: dict[str, Any], target_dates: list[str]) -> dict[str, Any]:
    stock_daily_count = int(database_summary.get("stock_daily_count") or 0)
    latest_stock_daily = database_summary.get("latest_stock_daily")
    fetch_dates = fetch_plan.get("fetch_dates", []) or []

    if stock_daily_count <= 0 or not latest_stock_daily:
        mode = "full_bootstrap"
        summary = "数据库无有效日线数据，执行近120日窗口全量补齐并重建派生结果"
    elif fetch_dates:
        mode = "incremental_backfill"
        summary = f"检测到 {len(fetch_dates)} 个交易日缺口，补齐到最新日线后重建派生结果"
    else:
        mode = "rebuild_only"
        summary = "近120日窗口数据完整，仅重建明日之星和当前热盘"

    return {
        "mode": mode,
        "summary": summary,
        "target_dates_count": len(target_dates),
        "fetch_dates_count": len(fetch_dates),
        "latest_stock_daily": latest_stock_daily,
    }


def _parallel_map_trade_dates(
    trade_dates: list[str],
    *,
    workers: int,
    label: str,
    job: Callable[[str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not trade_dates:
        return [], []

    if workers <= 1 or len(trade_dates) <= 1:
        results: list[dict[str, Any]] = []
        failures: list[str] = []
        for index, trade_date in enumerate(trade_dates, start=1):
            print(f"[{label} {index}/{len(trade_dates)}] fetch {trade_date}")
            try:
                result = job(trade_date)
            except Exception as exc:
                result = {"ok": False, "trade_date": trade_date, "error": str(exc)}
                failures.append(trade_date)
                print(f"[{label} {index}/{len(trade_dates)}] failed {trade_date}: {exc}")
            else:
                if not result.get("ok"):
                    failures.append(trade_date)
                    print(
                        f"[{label} {index}/{len(trade_dates)}] failed {trade_date}: "
                        f"{result.get('error') or result.get('message') or 'empty result'}"
                    )
            results.append(result)
        return results, failures

    print(f"[{label}] parallel fetch enabled: workers={workers}, tasks={len(trade_dates)}")
    result_by_date: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    mp_context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=workers, mp_context=mp_context) as executor:
        futures = {
            executor.submit(job, trade_date): trade_date
            for trade_date in trade_dates
        }
        for index, future in enumerate(as_completed(futures), start=1):
            trade_date = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"ok": False, "trade_date": trade_date, "error": str(exc)}
            result_by_date[trade_date] = result
            if not result.get("ok"):
                failures.append(trade_date)
                print(
                    f"[{label} {index}/{len(trade_dates)}] failed {trade_date}: "
                    f"{result.get('error') or result.get('message') or 'empty result'}"
                )
            else:
                print(f"[{label} {index}/{len(trade_dates)}] ok {trade_date}")

    ordered_results = [result_by_date[item] for item in trade_dates if item in result_by_date]
    return ordered_results, failures


def fetch_missing_metric_dates(pro: Any, trade_dates: list[str], *, workers: int = 1) -> dict[str, Any]:
    if not trade_dates:
        return {"success": True, "fetched_dates": [], "failed_dates": [], "results": []}

    if workers <= 1 or len(trade_dates) <= 1:
        fetched_dates: list[str] = []
        failed_dates: list[str] = []
        results: list[dict[str, Any]] = []
        for index, trade_date in enumerate(trade_dates, start=1):
            print(f"[metrics {index}/{len(trade_dates)}] fetch {trade_date}")
            try:
                frame = _fetch_trade_date_metric_frame(pro, trade_date)
                updated_count = _update_db_metrics_from_frame(frame)
                result = {
                    "ok": not frame.empty,
                    "trade_date": trade_date,
                    "record_count": int(len(frame.index)),
                    "updated_count": updated_count,
                }
                results.append(result)
                if result["ok"]:
                    fetched_dates.append(trade_date)
                else:
                    failed_dates.append(trade_date)
            except Exception as exc:
                failed_dates.append(trade_date)
                results.append({"ok": False, "trade_date": trade_date, "error": str(exc)})
                print(f"[metrics {index}/{len(trade_dates)}] failed {trade_date}: {exc}")
    else:
        results, failed_dates = _parallel_map_trade_dates(
            trade_dates,
            workers=workers,
            label="metrics",
            job=_metric_fetch_job,
        )
        fetched_dates = [
            item["trade_date"]
            for item in results
            if item.get("ok") is True and item.get("trade_date")
        ]

    return {
        "success": not failed_dates,
        "fetched_dates": fetched_dates,
        "failed_dates": failed_dates,
        "results": results,
    }


def fetch_missing_trade_dates(
    trade_dates: list[str],
    *,
    sync_csv: bool = True,
    workers: int = 1,
) -> dict[str, Any]:
    if not trade_dates:
        return {"success": True, "fetched_dates": [], "failed_dates": [], "raw_csv_sync": {}}

    results, failed_dates = _parallel_map_trade_dates(
        trade_dates,
        workers=workers,
        label="data",
        job=_trade_date_fetch_job,
    )
    fetched_dates = [
        item["trade_date"]
        for item in results
        if item.get("ok") is True and item.get("trade_date")
    ]

    raw_csv_sync: dict[str, Any] = {}
    if sync_csv and fetched_dates:
        print(f"[csv] sync raw CSV for {len(fetched_dates)} fetched trade dates")
        raw_csv_sync = sync_raw_csv_from_db(fetched_dates)

    return {
        "success": not failed_dates,
        "fetched_dates": fetched_dates,
        "failed_dates": failed_dates,
        "results": results,
        "raw_csv_sync": raw_csv_sync,
    }


def date_objects(trade_dates: Iterable[str]) -> list[date]:
    return [date.fromisoformat(item) for item in trade_dates]


def collect_existing_diagnosis_codes() -> set[str]:
    with SessionLocal() as db:
        return {
            str(code).zfill(6)
            for code, in db.query(DailyB1Check.code).distinct().all()
            if str(code or "").strip()
        }


def collect_current_hot_codes() -> set[str]:
    with SessionLocal() as db:
        service = CurrentHotService(db)
        return {entry.code for entry in service.get_pool_entries()}


def collect_candidate_codes(trade_dates: list[str]) -> set[str]:
    if not trade_dates:
        return set()
    with SessionLocal() as db:
        return {
            str(code).zfill(6)
            for code, in db.query(Candidate.code)
            .filter(Candidate.pick_date.in_(date_objects(trade_dates)))
            .distinct()
            .all()
            if str(code or "").strip()
        }


def collect_all_stock_codes() -> set[str]:
    return set(get_stock_codes())


def remove_file_artifacts(trade_dates: list[str]) -> dict[str, int]:
    removed_candidate_files = 0
    removed_review_dirs = 0
    candidates_dir = Path(settings.candidates_dir)
    review_dir = Path(settings.review_dir)
    if not candidates_dir.is_absolute():
        candidates_dir = ROOT / candidates_dir
    if not review_dir.is_absolute():
        review_dir = ROOT / review_dir

    for trade_date in trade_dates:
        candidate_file = candidates_dir / f"candidates_{trade_date}.json"
        if candidate_file.exists():
            candidate_file.unlink()
            removed_candidate_files += 1

        dated_review_dir = review_dir / trade_date
        if dated_review_dir.exists():
            shutil.rmtree(dated_review_dir)
            removed_review_dirs += 1

    return {
        "removed_candidate_files": removed_candidate_files,
        "removed_review_dirs": removed_review_dirs,
    }


def clean_derived_data(trade_dates: list[str], *, clean_diagnosis: bool) -> dict[str, Any]:
    if not trade_dates:
        return {}
    dates = date_objects(trade_dates)
    counts: dict[str, int] = {}
    with SessionLocal() as db:
        if clean_diagnosis:
            counts["daily_b1_check_details"] = db.query(DailyB1CheckDetail).filter(
                DailyB1CheckDetail.check_date.in_(dates)
            ).delete(synchronize_session=False)
            counts["daily_b1_checks"] = db.query(DailyB1Check).filter(
                DailyB1Check.check_date.in_(dates)
            ).delete(synchronize_session=False)

        counts["current_hot_intraday_snapshots"] = db.query(CurrentHotIntradaySnapshot).filter(
            or_(
                CurrentHotIntradaySnapshot.trade_date.in_(dates),
                CurrentHotIntradaySnapshot.source_pick_date.in_(dates),
            )
        ).delete(synchronize_session=False)
        counts["current_hot_analysis_results"] = db.query(CurrentHotAnalysisResult).filter(
            CurrentHotAnalysisResult.pick_date.in_(dates)
        ).delete(synchronize_session=False)
        counts["current_hot_candidates"] = db.query(CurrentHotCandidate).filter(
            CurrentHotCandidate.pick_date.in_(dates)
        ).delete(synchronize_session=False)
        counts["current_hot_runs"] = db.query(CurrentHotRun).filter(
            CurrentHotRun.pick_date.in_(dates)
        ).delete(synchronize_session=False)
        counts["stock_active_pool_ranks"] = db.query(StockActivePoolRank).filter(
            StockActivePoolRank.trade_date.in_(dates)
        ).delete(synchronize_session=False)
        counts["analysis_results"] = db.query(AnalysisResult).filter(
            AnalysisResult.pick_date.in_(dates)
        ).delete(synchronize_session=False)
        counts["candidates"] = db.query(Candidate).filter(
            Candidate.pick_date.in_(dates)
        ).delete(synchronize_session=False)
        counts["tomorrow_star_runs"] = db.query(TomorrowStarRun).filter(
            TomorrowStarRun.pick_date.in_(dates)
        ).delete(synchronize_session=False)
        db.commit()

    return {**counts, **remove_file_artifacts(trade_dates)}


def rebuild_tomorrow_star(trade_dates: list[str], *, reviewer: str, window_size: int) -> dict[str, Any]:
    if not trade_dates:
        return {"success": True, "rebuilt_dates": [], "failed_dates": []}
    with SessionLocal() as db:
        service = TomorrowStarWindowService(db)
        results = service.rebuild_trade_dates(
            trade_dates,
            reviewer=reviewer,
            source="recent_120_full_rebuild",
            window_size=window_size,
        )
    failed_dates = [str(item.get("pick_date")) for item in results if not item.get("success")]
    rebuilt_dates = [str(item.get("pick_date")) for item in results if item.get("success")]
    return {
        "success": not failed_dates,
        "rebuilt_dates": rebuilt_dates,
        "failed_dates": failed_dates,
        "results": results,
    }


def rebuild_current_hot(*, reviewer: str, window_size: int) -> dict[str, Any]:
    with SessionLocal() as db:
        config_row = db.query(Config).filter(Config.key == CurrentHotService.CONFIG_KEY).first()
        config_warning = None
        if config_row and str(config_row.value or "").strip() not in {"", "{}", "null"}:
            config_warning = (
                "current_hot_pool 数据库配置非空，本次会按数据库配置重建；"
                "脚本不会修改配置，因此不会强制使用代码默认热盘池。"
            )
        service = CurrentHotService(db)
        result = service.ensure_window(
            window_size=window_size,
            reviewer=reviewer,
            force=True,
            backfill_missing_history=False,
        )
    failed_dates = result.get("failed_dates", [])
    return {
        "success": not failed_dates,
        "warning": config_warning,
        **result,
    }


def resolve_diagnosis_codes(scope: str, target_dates: list[str], preclean_existing_codes: set[str]) -> list[str]:
    if scope == "none":
        return []
    if scope == "existing":
        codes = set(preclean_existing_codes)
    elif scope == "current-hot":
        codes = collect_current_hot_codes()
    elif scope == "both":
        codes = set(preclean_existing_codes) | collect_current_hot_codes()
    elif scope == "candidates":
        codes = collect_candidate_codes(target_dates)
    elif scope == "all":
        codes = collect_all_stock_codes()
    else:
        codes = set()
    return sorted(codes)


def _prewarm_diagnosis_active_pool(codes: list[str], target_dates: list[str]) -> dict[str, Any]:
    if not target_dates:
        return {"skipped": True, "reason": "empty_dates"}
    result = build_active_pool_rank_factors(target_dates, force=False)
    return {
        **result,
        "skipped": False,
        "codes_count": len(codes),
    }


def build_active_pool_rank_factors(target_dates: list[str], *, force: bool) -> dict[str, Any]:
    if not target_dates:
        return {"success": True, "skipped": True, "reason": "empty_dates"}
    try:
        preselect_cfg = analysis_service._load_preselect_config()
        global_cfg = preselect_cfg.get("global", {})
        top_m = int(global_cfg.get("top_m", 2000))
        n_turnover_days = int(global_cfg.get("n_turnover_days", 43))
        print(f"[active-pool-rank] build factors for {len(target_dates)} dates")
        result = active_pool_rank_service.compute_for_dates(
            target_dates,
            top_m=top_m,
            n_turnover_days=n_turnover_days,
            force=force,
        )
        return {**result, "skipped": False}
    except Exception as exc:
        print(f"[active-pool-rank] build failed: {exc}")
        return {"success": False, "skipped": True, "error": str(exc)}


def _clear_runtime_caches() -> dict[str, Any]:
    try:
        from app.api.cache_decorators import build_freshness_cache_key
        from app.cache import cache
        from app.services.analysis_cache import analysis_cache

        analysis_cache.clear_memory_cache()
        return {
            "candidates": cache.delete_prefix("candidates:"),
            "analysis_results": cache.delete_prefix("analysis_results:"),
            "kline": cache.delete_prefix("kline:"),
            "diagnosis_history": cache.delete_prefix("diagnosis:history:"),
            "active_pool_rank": cache.delete_prefix("active_pool_rank:"),
            "freshness": cache.delete(build_freshness_cache_key()),
            "analysis_memory": "cleared",
        }
    except Exception as exc:
        return {"error": str(exc)}


def rebuild_diagnosis_history(
    codes: list[str],
    *,
    days: int,
    limit: int = 0,
    target_dates: list[str] | None = None,
) -> dict[str, Any]:
    selected = codes[: limit or None]
    success_codes: list[str] = []
    failed: list[dict[str, str]] = []
    prewarm = _prewarm_diagnosis_active_pool(selected, target_dates or [])

    for index, code in enumerate(selected, start=1):
        print(f"[diagnosis {index}/{len(selected)}] rebuild {code}")
        try:
            result = analysis_service.generate_stock_history_checks(
                code,
                days=days,
                clean=True,
                target_dates=target_dates,
            )
            if result.get("success"):
                success_codes.append(code)
            else:
                failed.append({"code": code, "error": str(result.get("error") or "unknown")})
        except Exception as exc:
            failed.append({"code": code, "error": str(exc)})
            print(f"[diagnosis {index}/{len(selected)}] failed {code}: {exc}")

    return {
        "success": not failed,
        "requested_count": len(codes),
        "selected_count": len(selected),
        "success_count": len(success_codes),
        "failed": failed,
        "prewarm": prewarm,
        "success_codes_sample": success_codes[:20],
    }


def prewarm_diagnosis_cache(limit: int = 0) -> dict[str, Any]:
    try:
        from app.services.diagnosis_history_cache_service import diagnosis_history_cache_service

        return diagnosis_history_cache_service.prewarm(
            limit=limit,
            force=True,
            generate_if_missing=False,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def recalculate_consecutive_metrics() -> dict[str, Any]:
    from app.services.candidate_service import CandidateService

    with SessionLocal() as db:
        candidate_stats = CandidateService.recalculate_consecutive_metrics(db, commit=False)
        current_hot_stats = CurrentHotService.recalculate_consecutive_metrics(db, commit=False)
        db.commit()
    return {
        "candidate_stats": candidate_stats,
        "current_hot_stats": current_hot_stats,
    }


def summarize_current_database() -> dict[str, Any]:
    with SessionLocal() as db:
        return {
            "database_url": settings.database_url,
            "stock_count": int(db.query(func.count(Stock.code)).scalar() or 0),
            "stock_daily_count": int(db.query(func.count(StockDaily.id)).scalar() or 0),
            "latest_stock_daily": (
                db.query(func.max(StockDaily.trade_date)).scalar().isoformat()
                if db.query(func.max(StockDaily.trade_date)).scalar()
                else None
            ),
        }


def ensure_schema_migrations() -> dict[str, list[str]]:
    return apply_startup_sql_migrations(engine, BACKEND / "migrations")


def main() -> int:
    args = parse_args()
    if not args.dry_run and not args.yes:
        raise SystemExit("该脚本会清理并重建派生数据；请加 --yes 确认执行，或加 --dry-run 查看计划。")

    token = settings.tushare_token
    if not token and not args.skip_data_fetch:
        raise SystemExit("TUSHARE_TOKEN is not configured")

    pro = ts.pro_api(token) if token else None
    target_window = max(1, int(args.window_size))
    warmup_days = max(0, int(args.warmup_trade_days))
    data_window = target_window + warmup_days
    schema_result = {"skipped": ["dry_run"], "applied": [], "already_recorded": []} if args.dry_run else ensure_schema_migrations()

    synced_stocks = 0
    if not args.dry_run and pro is not None:
        print("[stock] sync stock list")
        synced_stocks = sync_stock_list()

    if pro is None:
        raise SystemExit("需要 TUSHARE_TOKEN 获取最近交易日历")

    data_dates = get_recent_trade_dates(pro, total_days=data_window, end_date=args.end_date)
    target_dates = data_dates[-target_window:]
    stock_codes = get_stock_codes()
    preclean_existing_diagnosis_codes = collect_existing_diagnosis_codes()
    database_summary = summarize_current_database()

    fetch_plan = {"fetch_dates": []}
    if not args.skip_data_fetch:
        print("[plan] checking csv/db completeness")
        fetch_plan = detect_data_fetch_plan(args, data_dates, stock_codes)

    full_fetch_dates = fetch_plan.get("full_fetch_dates", fetch_plan.get("fetch_dates", []))
    metric_fetch_dates = fetch_plan.get("metric_fetch_dates", [])
    csv_sync_dates = fetch_plan.get("csv_sync_dates", fetch_plan.get("fetch_dates", []))
    data_fetch_workers = resolve_parallel_workers(
        args.workers,
        task_count=len(full_fetch_dates),
        max_workers=max(1, int(args.max_workers)),
        reserve_cpus=max(0, int(args.reserve_cpus)),
        memory_per_worker_mb=max(1, int(args.memory_per_worker_mb)),
    )
    metric_fetch_workers = resolve_parallel_workers(
        args.workers,
        task_count=len(metric_fetch_dates),
        max_workers=max(1, int(args.max_workers)),
        reserve_cpus=max(0, int(args.reserve_cpus)),
        memory_per_worker_mb=max(1, int(args.memory_per_worker_mb)),
    )
    update_mode = summarize_update_mode(database_summary, fetch_plan, target_dates)

    diagnosis_codes_initial = resolve_diagnosis_codes(
        args.diagnosis_scope,
        target_dates,
        preclean_existing_diagnosis_codes,
    )

    plan = {
        "database": database_summary,
        "schema_migrations": schema_result,
        "synced_stock_count": synced_stocks,
        "update_mode": update_mode,
        "window_size": target_window,
        "warmup_trade_days": warmup_days,
        "data_date_range": [data_dates[0], data_dates[-1]] if data_dates else [],
        "target_date_range": [target_dates[0], target_dates[-1]] if target_dates else [],
        "target_dates_count": len(target_dates),
        "stock_codes_count": len(stock_codes),
        "data_fetch_dates_count": len(fetch_plan.get("fetch_dates", [])),
        "full_fetch_dates_count": len(full_fetch_dates),
        "metric_fetch_dates_count": len(metric_fetch_dates),
        "csv_sync_dates_count": len(csv_sync_dates),
        "data_fetch_dates_sample": fetch_plan.get("fetch_dates", [])[:20],
        "parallel_fetch": {
            "requested_workers": str(args.workers),
            "max_workers": max(1, int(args.max_workers)),
            "reserve_cpus": max(0, int(args.reserve_cpus)),
            "memory_per_worker_mb": max(1, int(args.memory_per_worker_mb)),
            "data_fetch": data_fetch_workers,
            "metric_fetch": metric_fetch_workers,
        },
        "diagnosis_scope": args.diagnosis_scope,
        "diagnosis_codes_count": len(diagnosis_codes_initial),
        "diagnosis_codes_sample": diagnosis_codes_initial[:20],
        "skip_tomorrow_star": args.skip_tomorrow_star,
        "skip_current_hot": args.skip_current_hot,
        "skip_clean": args.skip_clean,
        "dry_run": args.dry_run,
    }
    print(json.dumps({"plan": plan}, ensure_ascii=False, indent=2, default=str))

    if args.dry_run:
        return 0

    results: dict[str, Any] = {"plan": plan}

    if not args.skip_data_fetch:
        results["data_fetch"] = fetch_missing_trade_dates(
            full_fetch_dates,
            sync_csv=False,
            workers=int(data_fetch_workers.get("resolved_workers") or 1),
        )
        results["metric_fetch"] = fetch_missing_metric_dates(
            pro,
            metric_fetch_dates,
            workers=int(metric_fetch_workers.get("resolved_workers") or 1),
        )
        if not results["data_fetch"].get("success") or not results["metric_fetch"].get("success"):
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
            return 1
        if csv_sync_dates:
            print(f"[csv] sync raw CSV for {len(csv_sync_dates)} trade dates")
            results["raw_csv_sync"] = sync_raw_csv_from_db(csv_sync_dates)

    if not args.skip_clean:
        print("[clean] clear old derived data")
        results["clean"] = clean_derived_data(
            target_dates,
            clean_diagnosis=args.diagnosis_scope != "none",
        )

    print("[rebuild] active-pool-rank")
    results["active_pool_rank"] = build_active_pool_rank_factors(
        target_dates,
        force=not args.skip_clean,
    )
    if not results["active_pool_rank"].get("success"):
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return 1

    if not args.skip_tomorrow_star:
        print("[rebuild] tomorrow-star")
        results["tomorrow_star"] = rebuild_tomorrow_star(
            target_dates,
            reviewer=args.reviewer,
            window_size=target_window,
        )
        if not results["tomorrow_star"].get("success"):
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
            return 1

    if not args.skip_current_hot:
        print("[rebuild] current-hot")
        results["current_hot"] = rebuild_current_hot(
            reviewer=args.reviewer,
            window_size=target_window,
        )
        if results["current_hot"].get("warning"):
            print(f"[warning] {results['current_hot']['warning']}")
        if not results["current_hot"].get("success"):
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
            return 1

    diagnosis_codes = resolve_diagnosis_codes(
        args.diagnosis_scope,
        target_dates,
        preclean_existing_diagnosis_codes,
    )
    if diagnosis_codes:
        print("[rebuild] diagnosis history")
        results["diagnosis"] = rebuild_diagnosis_history(
            diagnosis_codes,
            days=target_window,
            limit=max(0, int(args.diagnosis_limit)),
            target_dates=target_dates,
        )
        if not results["diagnosis"].get("success"):
            print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
            return 1

    print("[metrics] recalculate consecutive metrics")
    results["consecutive_metrics"] = recalculate_consecutive_metrics()
    print("[cache] clear runtime caches")
    results["cache_clear"] = _clear_runtime_caches()
    print("[cache] prewarm diagnosis history")
    results["diagnosis_cache_prewarm"] = prewarm_diagnosis_cache(limit=max(0, int(args.diagnosis_limit)))
    results["database_after"] = summarize_current_database()
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
