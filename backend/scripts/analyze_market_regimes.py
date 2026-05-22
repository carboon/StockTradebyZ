"""Analyze market shock/rebound regimes and rank sectors/stocks.

Outputs:
    data/backtest/market_regime/summary_<today>.json
    data/backtest/market_regime/broad_sectors_<window>_<today>.csv
    data/backtest/market_regime/custom_pools_<window>_<today>.csv
    data/backtest/market_regime/strong_candidates_<today>.csv
    data/backtest/market_regime/defensive_candidates_<today>.csv

Default windows:
1. late_2025:
   2025-11-13 -> 2025-11-21 -> 2026-01-12
2. spring_2026:
   2026-03-02 -> 2026-03-23 -> 2026-05-13 -> latest trade date
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.services.sector_analysis_config import DEFAULT_SECTOR_ANALYSIS_POOL  # noqa: E402

OUTPUT_DIR = ROOT / "data" / "backtest" / "market_regime"
SW_CACHE_DIR = ROOT / "data" / "tushare_cache" / "sw"
INDEX_CACHE_DIR = ROOT / "data" / "tushare_cache" / "index_daily"
DEFENSIVE_SECTOR_WHITELIST = {"银行", "煤炭", "公用事业", "交通运输", "食品饮料"}


@dataclass(frozen=True)
class RegimeWindow:
    name: str
    peak_date: str
    trough_date: str
    rebound_date: str
    today_date: str


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze market shock/rebound regimes.")
    parser.add_argument("--today-date", default="2026-05-21", help="Latest trade date, default: 2026-05-21")
    parser.add_argument("--spring-peak", default="2026-03-02")
    parser.add_argument("--spring-trough", default="2026-03-23")
    parser.add_argument("--spring-rebound", default="2026-05-13")
    parser.add_argument("--late2025-peak", default="2025-11-13")
    parser.add_argument("--late2025-trough", default="2025-11-21")
    parser.add_argument("--late2025-rebound", default="2026-01-12")
    parser.add_argument("--top-n", type=int, default=10, help="Top sectors to keep in console summary.")
    parser.add_argument("--candidate-top-n", type=int, default=25, help="Top stock candidates to export/highlight.")
    return parser.parse_args()


def _replace_postgres_host(db_url: str, new_host: str) -> str:
    parsed = urlsplit(db_url)
    if not parsed.hostname:
        return db_url

    netloc = parsed.netloc
    if "@" in netloc:
        auth, host_part = netloc.rsplit("@", 1)
        if ":" in host_part:
            _, port = host_part.split(":", 1)
            host_part = f"{new_host}:{port}"
        else:
            host_part = new_host
        netloc = f"{auth}@{host_part}"
    else:
        if ":" in netloc:
            _, port = netloc.split(":", 1)
            netloc = f"{new_host}:{port}"
        else:
            netloc = new_host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _build_engine():
    candidates = [settings.database_url]
    if "postgres@" in settings.database_url or "@postgres:" in settings.database_url:
        candidates.append(_replace_postgres_host(settings.database_url, "localhost"))

    last_error: Exception | None = None
    for db_url in candidates:
        engine = create_engine(db_url)
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("select 1")
            return engine
        except OperationalError as exc:  # pragma: no cover - environment-specific fallback
            last_error = exc
    raise RuntimeError(f"Unable to connect to PostgreSQL: {last_error}")


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _to_timestamp(value: str) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _zscore(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").astype(float)
    if numeric.empty:
        return numeric
    std = numeric.std(ddof=0)
    if not math.isfinite(std) or std == 0:
        return pd.Series(0.0, index=numeric.index)
    mean = numeric.mean()
    return (numeric - mean) / std


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _load_index_series_from_cache(ts_code: str) -> pd.Series:
    frames: list[pd.DataFrame] = []
    for path in sorted(INDEX_CACHE_DIR.glob(f"{ts_code}_*.csv")):
        frame = pd.read_csv(path, usecols=["trade_date", "close"])
        frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str))
        frames.append(frame)
    if not frames:
        return pd.Series(dtype=float)
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.dropna(subset=["trade_date", "close"])
    merged = merged.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")
    return merged.set_index("trade_date")["close"].astype(float)


def _load_index_series(ts_code: str, *, start_date: str, end_date: str) -> pd.Series:
    cached = _load_index_series_from_cache(ts_code)
    start_ts = _to_timestamp(start_date)
    end_ts = _to_timestamp(end_date)
    if not cached.empty:
        sliced = cached[(cached.index >= start_ts) & (cached.index <= end_ts)]
        if start_ts in sliced.index and end_ts in sliced.index:
            return sliced.sort_index()

    token = settings.tushare_token
    if not token:
        if not cached.empty:
            return cached[(cached.index >= start_ts) & (cached.index <= end_ts)].sort_index()
        raise RuntimeError(f"Missing cached index data and Tushare token for {ts_code}")

    import tushare as ts  # noqa: WPS433

    pro = ts.pro_api(token)
    if ts_code.endswith(".SI"):
        frame = pro.sw_daily(ts_code=ts_code, start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""), fields="ts_code,trade_date,close")
    else:
        frame = pro.index_daily(ts_code=ts_code, start_date=start_date.replace("-", ""), end_date=end_date.replace("-", ""), fields="ts_code,trade_date,close")
    if frame is None or frame.empty:
        raise RuntimeError(f"Unable to load index series for {ts_code}")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str))
    frame = frame.sort_values("trade_date").drop_duplicates(subset=["trade_date"], keep="last")
    return frame.set_index("trade_date")["close"].astype(float)


def _load_sw_classify() -> pd.DataFrame:
    path = SW_CACHE_DIR / "sw_l1_classify.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing SW classify cache: {path}")
    frame = pd.read_csv(path, usecols=["index_code", "industry_name"])
    return frame.dropna(subset=["index_code", "industry_name"]).drop_duplicates(subset=["index_code"]).reset_index(drop=True)


def _active_sw_members(trade_date: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    target = trade_date.replace("-", "")
    sector_to_codes: dict[str, set[str]] = {}
    code_to_sectors: dict[str, set[str]] = {}
    for member_file in sorted(SW_CACHE_DIR.glob("member_*.csv")):
        frame = pd.read_csv(member_file, usecols=["index_code", "con_code", "in_date", "out_date"])
        if frame.empty:
            continue
        frame["con_code"] = frame["con_code"].astype(str).str.extract(r"(\d{6})", expand=False)
        frame["in_date"] = frame["in_date"].fillna("").astype(str).str.replace(".0", "", regex=False)
        frame["out_date"] = frame["out_date"].fillna("").astype(str).str.replace(".0", "", regex=False)
        frame = frame.dropna(subset=["con_code", "index_code"])
        active = frame[
            (frame["in_date"] <= target)
            & ((frame["out_date"] == "") | (frame["out_date"] > target))
        ]
        if active.empty:
            continue
        index_code = str(active["index_code"].iloc[0]).strip()
        codes = set(active["con_code"].astype(str).tolist())
        sector_to_codes[index_code] = codes
        for code in codes:
            code_to_sectors.setdefault(code, set()).add(index_code)
    return sector_to_codes, code_to_sectors


def _compute_leg_return(series: pd.Series, start_date: str, end_date: str) -> float | None:
    start_ts = _to_timestamp(start_date)
    end_ts = _to_timestamp(end_date)
    if start_ts not in series.index or end_ts not in series.index:
        return None
    start_value = _safe_float(series.loc[start_ts])
    end_value = _safe_float(series.loc[end_ts])
    if start_value in (None, 0.0) or end_value is None:
        return None
    return end_value / start_value - 1.0


def _analyze_broad_sectors(window: RegimeWindow) -> pd.DataFrame:
    classify = _load_sw_classify()
    rows: list[dict[str, Any]] = []
    for row in classify.itertuples(index=False):
        index_code = str(row.index_code)
        sector_name = str(row.industry_name)
        series = _load_index_series(index_code, start_date=window.peak_date, end_date=window.today_date)
        shock_ret = _compute_leg_return(series, window.peak_date, window.trough_date)
        rebound_ret = _compute_leg_return(series, window.trough_date, window.rebound_date)
        profit_ret = _compute_leg_return(series, window.rebound_date, window.today_date)
        full_ret = _compute_leg_return(series, window.trough_date, window.today_date)
        if None in (shock_ret, rebound_ret, profit_ret, full_ret):
            continue
        rows.append(
            {
                "window": window.name,
                "index_code": index_code,
                "sector_name": sector_name,
                "shock_ret": shock_ret,
                "rebound_ret": rebound_ret,
                "profit_ret": profit_ret,
                "full_ret": full_ret,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["strong_score"] = (
        0.50 * _zscore(frame["rebound_ret"])
        + 0.30 * _zscore(frame["full_ret"])
        + 0.20 * _zscore(frame["profit_ret"])
    )
    frame["defensive_score"] = (
        0.50 * _zscore(frame["shock_ret"])
        + 0.30 * _zscore(frame["profit_ret"])
        + 0.20 * _zscore(frame["full_ret"])
    )
    frame["strong_rank"] = frame["strong_score"].rank(method="dense", ascending=False).astype(int)
    frame["defensive_rank"] = frame["defensive_score"].rank(method="dense", ascending=False).astype(int)
    return frame.sort_values(["strong_rank", "sector_name"]).reset_index(drop=True)


def _load_custom_pool_prices(engine, start_date: str, end_date: str) -> pd.DataFrame:
    all_codes = sorted({item["code"] for items in DEFAULT_SECTOR_ANALYSIS_POOL.values() for item in items})
    codes_sql = ",".join(f"'{code}'" for code in all_codes)
    query = f"""
        select
            d.code,
            d.trade_date,
            d.close,
            d.turnover_rate,
            d.volume_ratio,
            d.net_mf_amount,
            d.circ_mv,
            s.name,
            s.industry
        from stock_daily d
        join stocks s on s.code = d.code
        where d.code in ({codes_sql})
          and d.trade_date between '{start_date}' and '{end_date}'
    """
    frame = pd.read_sql(query, engine)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def _calc_cross_section_leg_metrics(
    pivot: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
) -> tuple[float | None, float | None, float | None]:
    start_ts = _to_timestamp(start_date)
    end_ts = _to_timestamp(end_date)
    if start_ts not in pivot.index or end_ts not in pivot.index:
        return None, None, None
    ret = pivot.loc[end_ts] / pivot.loc[start_ts] - 1.0
    ret = pd.to_numeric(ret, errors="coerce").dropna()
    if ret.empty:
        return None, None, None
    return float(ret.mean()), float(ret.median()), float((ret > 0).mean())


def _analyze_custom_pools(engine, window: RegimeWindow) -> pd.DataFrame:
    frame = _load_custom_pool_prices(engine, window.peak_date, window.today_date)
    rows: list[dict[str, Any]] = []
    for sector_key, items in DEFAULT_SECTOR_ANALYSIS_POOL.items():
        codes = [item["code"] for item in items]
        sub = frame[frame["code"].isin(codes)].copy()
        if sub.empty:
            continue
        pivot = sub.pivot_table(index="trade_date", columns="code", values="close", aggfunc="last").sort_index()
        shock_mean, shock_median, shock_win = _calc_cross_section_leg_metrics(pivot, start_date=window.peak_date, end_date=window.trough_date)
        rebound_mean, rebound_median, rebound_win = _calc_cross_section_leg_metrics(pivot, start_date=window.trough_date, end_date=window.rebound_date)
        profit_mean, profit_median, profit_win = _calc_cross_section_leg_metrics(pivot, start_date=window.rebound_date, end_date=window.today_date)
        full_mean, full_median, full_win = _calc_cross_section_leg_metrics(pivot, start_date=window.trough_date, end_date=window.today_date)
        if None in (
            shock_mean,
            shock_median,
            shock_win,
            rebound_mean,
            rebound_median,
            rebound_win,
            profit_mean,
            profit_median,
            profit_win,
            full_mean,
            full_median,
            full_win,
        ):
            continue
        rows.append(
            {
                "window": window.name,
                "sector_key": sector_key,
                "member_count": len(codes),
                "shock_mean": shock_mean,
                "shock_median": shock_median,
                "shock_win": shock_win,
                "rebound_mean": rebound_mean,
                "rebound_median": rebound_median,
                "rebound_win": rebound_win,
                "profit_mean": profit_mean,
                "profit_median": profit_median,
                "profit_win": profit_win,
                "full_mean": full_mean,
                "full_median": full_median,
                "full_win": full_win,
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    result["strong_score"] = (
        0.40 * _zscore(result["rebound_mean"])
        + 0.30 * _zscore(result["full_mean"])
        + 0.20 * _zscore(result["profit_mean"])
        + 0.10 * _zscore(result["full_win"])
    )
    result["defensive_score"] = (
        0.45 * _zscore(result["shock_mean"])
        + 0.30 * _zscore(result["profit_mean"])
        + 0.15 * _zscore(result["shock_win"])
        + 0.10 * _zscore(result["full_mean"])
    )
    result["strong_rank"] = result["strong_score"].rank(method="dense", ascending=False).astype(int)
    result["defensive_rank"] = result["defensive_score"].rank(method="dense", ascending=False).astype(int)
    return result.sort_values(["strong_rank", "sector_key"]).reset_index(drop=True)


def _query_stock_universe(engine, codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    if not codes:
        return pd.DataFrame()
    codes_sql = ",".join(f"'{code}'" for code in sorted(set(codes)))
    query = f"""
        select
            d.code,
            d.trade_date,
            d.close,
            d.turnover_rate,
            d.volume_ratio,
            d.net_mf_amount,
            s.name,
            s.industry
        from stock_daily d
        join stocks s on s.code = d.code
        where d.code in ({codes_sql})
          and d.trade_date between '{start_date}' and '{end_date}'
        order by d.code, d.trade_date
    """
    frame = pd.read_sql(query, engine)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def _prepare_stock_candidate_frame(
    engine,
    window: RegimeWindow,
    sector_rows: pd.DataFrame,
    *,
    rank_column: str,
    top_sector_count: int,
    score_type: str,
) -> pd.DataFrame:
    classify = _load_sw_classify()
    sector_name_by_code = dict(zip(classify["index_code"], classify["industry_name"]))
    sector_to_codes, code_to_sectors = _active_sw_members(window.today_date)
    selected = sector_rows.sort_values(rank_column).head(top_sector_count)
    if score_type == "defensive":
        strict_selected = sector_rows[sector_rows["sector_name"].isin(DEFENSIVE_SECTOR_WHITELIST)].sort_values(rank_column)
        if not strict_selected.empty:
            selected = strict_selected.head(top_sector_count)
    selected_index_codes = selected["index_code"].astype(str).tolist()
    member_codes = sorted({code for sector_code in selected_index_codes for code in sector_to_codes.get(sector_code, set())})
    if not member_codes:
        return pd.DataFrame()

    query_start = min(window.peak_date, (pd.Timestamp(window.today_date) - pd.offsets.BDay(25)).strftime("%Y-%m-%d"))
    prices = _query_stock_universe(engine, member_codes, query_start, window.today_date)
    if prices.empty:
        return prices

    rows: list[dict[str, Any]] = []
    for code, sub in prices.groupby("code", sort=True):
        sub = sub.sort_values("trade_date").reset_index(drop=True)
        close = sub.set_index("trade_date")["close"].astype(float)
        peak_ts = _to_timestamp(window.peak_date)
        trough_ts = _to_timestamp(window.trough_date)
        rebound_ts = _to_timestamp(window.rebound_date)
        today_ts = _to_timestamp(window.today_date)
        if any(ts not in close.index for ts in (peak_ts, trough_ts, rebound_ts, today_ts)):
            continue
        latest_slice = sub[sub["trade_date"] <= today_ts].tail(20).copy()
        if len(latest_slice) < 10:
            continue
        pct_std_20 = close.loc[latest_slice["trade_date"]].pct_change().dropna().std(ddof=0)
        rows.append(
            {
                "code": code,
                "name": str(sub["name"].iloc[-1]),
                "industry": str(sub["industry"].iloc[-1]),
                "broad_sectors": " / ".join(sorted(sector_name_by_code.get(item, item) for item in code_to_sectors.get(code, set()))),
                "drop_peak_to_trough": _compute_leg_return(close, window.peak_date, window.trough_date),
                "rebound_trough_to_rebound": _compute_leg_return(close, window.trough_date, window.rebound_date),
                "rebound_trough_to_today": _compute_leg_return(close, window.trough_date, window.today_date),
                "pullback_rebound_to_today": _compute_leg_return(close, window.rebound_date, window.today_date),
                "ma20_gap_today": _safe_float(close.loc[today_ts] / latest_slice["close"].mean() - 1.0),
                "turnover_20d_avg": _safe_float(pd.to_numeric(latest_slice["turnover_rate"], errors="coerce").dropna().mean()),
                "volume_ratio_20d_avg": _safe_float(pd.to_numeric(latest_slice["volume_ratio"], errors="coerce").dropna().mean()),
                "net_mf_5d_sum": _safe_float(pd.to_numeric(sub[sub["trade_date"] <= today_ts]["net_mf_amount"], errors="coerce").dropna().tail(5).sum()),
                "volatility_20d": _safe_float(pct_std_20),
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result

    if score_type == "strong":
        result = result[
            (result["rebound_trough_to_today"] > 0)
            & (result["ma20_gap_today"] > -0.08)
        ].copy()
        result["candidate_score"] = (
            0.35 * _zscore(result["rebound_trough_to_today"])
            + 0.25 * _zscore(result["pullback_rebound_to_today"])
            + 0.15 * _zscore(result["ma20_gap_today"])
            + 0.15 * _zscore(result["net_mf_5d_sum"])
            + 0.10 * _zscore(result["turnover_20d_avg"])
        )
    else:
        result = result[
            (result["drop_peak_to_trough"] > -0.25)
            & (result["pullback_rebound_to_today"] > -0.10)
        ].copy()
        result["candidate_score"] = (
            0.35 * _zscore(result["drop_peak_to_trough"])
            + 0.25 * _zscore(result["pullback_rebound_to_today"])
            + 0.15 * _zscore(result["ma20_gap_today"])
            + 0.15 * _zscore(result["net_mf_5d_sum"])
            + 0.10 * _zscore(-result["volatility_20d"])
        )
    result["candidate_rank"] = result["candidate_score"].rank(method="dense", ascending=False).astype(int)
    result["source_window"] = window.name
    result["candidate_type"] = score_type
    return result.sort_values(["candidate_rank", "code"]).reset_index(drop=True)


def _round_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if pd.api.types.is_float_dtype(result[column]):
            result[column] = result[column].round(6)
    return result


def _load_market_index_snapshot(today_date: str) -> dict[str, Any]:
    snapshots = {}
    index_map = {
        "shanghai": "000001.SH",
        "csi300": "000300.SH",
        "chinext": "399006.SZ",
    }
    for key, ts_code in index_map.items():
        series = _load_index_series(ts_code, start_date="2025-11-01", end_date=today_date)
        if series.empty:
            continue
        snapshots[key] = {
            "ts_code": ts_code,
            "latest_date": series.index.max().strftime("%Y-%m-%d"),
            "latest_close": round(float(series.iloc[-1]), 4),
        }
    return snapshots


def main() -> None:
    args = _parse_args()
    _ensure_output_dir()
    engine = _build_engine()

    spring_window = RegimeWindow(
        name="spring_2026",
        peak_date=args.spring_peak,
        trough_date=args.spring_trough,
        rebound_date=args.spring_rebound,
        today_date=args.today_date,
    )
    late_2025_window = RegimeWindow(
        name="late_2025",
        peak_date=args.late2025_peak,
        trough_date=args.late2025_trough,
        rebound_date=args.late2025_rebound,
        today_date=args.late2025_rebound,
    )

    broad_spring = _round_frame(_analyze_broad_sectors(spring_window))
    broad_late_2025 = _round_frame(_analyze_broad_sectors(late_2025_window))
    custom_spring = _round_frame(_analyze_custom_pools(engine, spring_window))
    custom_late_2025 = _round_frame(_analyze_custom_pools(engine, late_2025_window))

    strong_candidates = _round_frame(
        _prepare_stock_candidate_frame(
            engine,
            spring_window,
            broad_spring,
            rank_column="strong_rank",
            top_sector_count=3,
            score_type="strong",
        )
    )
    defensive_candidates = _round_frame(
        _prepare_stock_candidate_frame(
            engine,
            spring_window,
            broad_spring,
            rank_column="defensive_rank",
            top_sector_count=3,
            score_type="defensive",
        )
    )

    today_tag = args.today_date.replace("-", "")
    broad_spring_path = OUTPUT_DIR / f"broad_sectors_{spring_window.name}_{today_tag}.csv"
    broad_late_2025_path = OUTPUT_DIR / f"broad_sectors_{late_2025_window.name}_{today_tag}.csv"
    custom_spring_path = OUTPUT_DIR / f"custom_pools_{spring_window.name}_{today_tag}.csv"
    custom_late_2025_path = OUTPUT_DIR / f"custom_pools_{late_2025_window.name}_{today_tag}.csv"
    strong_path = OUTPUT_DIR / f"strong_candidates_{today_tag}.csv"
    defensive_path = OUTPUT_DIR / f"defensive_candidates_{today_tag}.csv"
    summary_path = OUTPUT_DIR / f"summary_{today_tag}.json"

    broad_spring.to_csv(broad_spring_path, index=False)
    broad_late_2025.to_csv(broad_late_2025_path, index=False)
    custom_spring.to_csv(custom_spring_path, index=False)
    custom_late_2025.to_csv(custom_late_2025_path, index=False)
    strong_candidates.to_csv(strong_path, index=False)
    defensive_candidates.to_csv(defensive_path, index=False)

    summary = {
        "windows": [asdict(spring_window), asdict(late_2025_window)],
        "market_index_snapshot": _load_market_index_snapshot(args.today_date),
        "broad_sector_top_strong_spring_2026": broad_spring.head(args.top_n).to_dict(orient="records"),
        "broad_sector_top_defensive_spring_2026": broad_spring.sort_values("defensive_rank").head(args.top_n).to_dict(orient="records"),
        "custom_pool_top_strong_spring_2026": custom_spring.head(args.top_n).to_dict(orient="records"),
        "custom_pool_top_defensive_late_2025": custom_late_2025.sort_values("defensive_rank").head(args.top_n).to_dict(orient="records"),
        "strong_candidates": strong_candidates.head(args.candidate_top_n).to_dict(orient="records"),
        "defensive_candidates": defensive_candidates.head(args.candidate_top_n).to_dict(orient="records"),
        "artifacts": {
            "broad_spring_csv": str(broad_spring_path),
            "broad_late_2025_csv": str(broad_late_2025_path),
            "custom_spring_csv": str(custom_spring_path),
            "custom_late_2025_csv": str(custom_late_2025_path),
            "strong_candidates_csv": str(strong_path),
            "defensive_candidates_csv": str(defensive_path),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("spring_2026 broad strong top sectors")
    print(
        broad_spring[["strong_rank", "sector_name", "shock_ret", "rebound_ret", "profit_ret", "full_ret"]]
        .head(args.top_n)
        .to_string(index=False)
    )
    print("\nspring_2026 broad defensive top sectors")
    print(
        broad_spring.sort_values("defensive_rank")[["defensive_rank", "sector_name", "shock_ret", "rebound_ret", "profit_ret", "full_ret"]]
        .head(args.top_n)
        .to_string(index=False)
    )
    print("\nspring_2026 custom strong top pools")
    print(
        custom_spring[["strong_rank", "sector_key", "shock_mean", "rebound_mean", "profit_mean", "full_mean"]]
        .head(args.top_n)
        .to_string(index=False)
    )
    print("\nstrong stock candidates")
    if strong_candidates.empty:
        print("(empty)")
    else:
        print(
            strong_candidates[["candidate_rank", "code", "name", "industry", "broad_sectors", "rebound_trough_to_today", "pullback_rebound_to_today", "candidate_score"]]
            .head(args.candidate_top_n)
            .to_string(index=False)
        )
    print("\ndefensive stock candidates")
    if defensive_candidates.empty:
        print("(empty)")
    else:
        print(
            defensive_candidates[["candidate_rank", "code", "name", "industry", "broad_sectors", "drop_peak_to_trough", "pullback_rebound_to_today", "candidate_score"]]
            .head(args.candidate_top_n)
            .to_string(index=False)
        )
    print(f"\nsummary written to {summary_path}")


if __name__ == "__main__":
    main()
