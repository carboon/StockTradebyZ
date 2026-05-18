"""
Backtest B1 hot-sector candidates with legacy vs optimized ranking.

Goal:
1. Use the current B1 + active-pool universe.
2. Restrict to locally-derived hot industries.
3. Compare legacy ranking vs optimized ranking on the same B1 events.
4. Evaluate with a fixed exit rule:
   - stop loss: within first 3 trading days, intraday -5%
   - profit run: hold to 20 trading days max

Outputs:
    data/backtest/b1_hot_sector_trades_<start>_<end>.csv
    data/backtest/b1_hot_sector_summary_<start>_<end>.json
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "agent"))

from Selector import B1Selector  # noqa: E402
from pipeline_core import TopTurnoverPoolBuilder  # noqa: E402
from select_stock import load_config as load_preselect_config, load_raw_data  # noqa: E402
from quant_reviewer import (  # noqa: E402
    _determine_signal,
    _determine_verdict,
    _generate_comment,
    _score_abnormal,
    _score_position,
    _score_trend,
    load_config as load_review_config,
    min_bars_required,
    prepare_review_frame,
    review_prepared_row,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backtest_b1_hot_sectors")

DEFAULT_LOOKBACK_TRADE_DAYS = 120
DEFAULT_HOT_TOP_PCT = 0.30
DEFAULT_INDUSTRY_LOOKBACK = 20
DEFAULT_STOP_DAYS = 3
DEFAULT_STOP_LOSS_PCT = 0.05
DEFAULT_MAX_HOLD_DAYS = 20
DEFAULT_TOP_NS = (1, 3, 5)


def _calc_backtest_warmup(cfg: dict[str, Any], review_cfg: dict[str, Any]) -> int:
    warmup = 120
    global_cfg = cfg.get("global", {})
    min_bars_buffer = int(global_cfg.get("min_bars_buffer", 10))
    b1_cfg = cfg.get("b1", {})
    if b1_cfg.get("enabled", True):
        warmup = max(warmup, int(b1_cfg.get("zx_m4", 114)) + min_bars_buffer)
    return max(warmup, min_bars_required(review_cfg))


def _prepare_base_frames(
    raw_data: dict[str, pd.DataFrame],
    n_turnover_days: int,
) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    for code, df in raw_data.items():
        frame = df.copy()
        frame.columns = [c.lower() for c in frame.columns]
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
        frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
        if frame.empty:
            continue
        frame["signed_turnover"] = (frame["open"] + frame["close"]) / 2.0 * frame["volume"]
        frame["turnover_n"] = frame["signed_turnover"].rolling(n_turnover_days, min_periods=1).sum()
        frame = frame.set_index("date", drop=False)
        prepared[code] = frame
    return prepared


def _build_b1_selector(cfg: dict[str, Any]) -> B1Selector:
    b1 = cfg["b1"]
    return B1Selector(
        j_threshold=float(b1["j_threshold"]),
        j_q_threshold=float(b1["j_q_threshold"]),
        zx_m1=int(b1["zx_m1"]),
        zx_m2=int(b1["zx_m2"]),
        zx_m3=int(b1["zx_m3"]),
        zx_m4=int(b1["zx_m4"]),
    )


def _reference_trade_dates(raw_dir: Path, desired: int) -> list[pd.Timestamp]:
    ref_path = raw_dir / "000001.csv"
    if not ref_path.exists():
        matches = sorted(raw_dir.glob("*.csv"))
        if not matches:
            raise FileNotFoundError(f"no csv found in {raw_dir}")
        ref_path = matches[0]
    frame = pd.read_csv(ref_path, usecols=["date"])
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna().sort_values().drop_duplicates()
    if dates.empty:
        raise ValueError(f"reference file has no dates: {ref_path}")
    return list(pd.DatetimeIndex(dates).to_pydatetime())[-desired:]


def _normalize_code(value: Any) -> str:
    text = str(value or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def _industry_map(stocklist_path: Path) -> dict[str, str]:
    frame = pd.read_csv(stocklist_path, usecols=["symbol", "industry"])
    out: dict[str, str] = {}
    for row in frame.itertuples(index=False):
        code = _normalize_code(getattr(row, "symbol", ""))
        industry = str(getattr(row, "industry", "") or "").strip()
        if code and industry:
            out[code] = industry
    return out


def _signal_priority(signal_type: str | None) -> int:
    if signal_type == "trend_start":
        return 0
    if signal_type == "rebound":
        return 1
    if signal_type == "distribution_risk":
        return 2
    return 3


def _score_volume_legacy(row: pd.Series, cfg: dict[str, Any]) -> tuple[int, str]:
    ratio = float(row.get("up_down_ratio", 0.0) or 0.0)
    dist_count = int(round(float(row.get("distribution_count", 0.0) or 0.0)))
    severe_count = int(round(float(row.get("severe_distribution_count", 0.0) or 0.0)))
    dryup = float(row.get("pullback_dryup", 0.0) or 0.0)
    obv_slope = float(row.get("obv_slope", 0.0) or 0.0)

    if severe_count >= 1 or dist_count >= 3:
        return 1, (
            f"最近 {int(cfg['window'])} 日出现 {dist_count} 次放量下跌，"
            "量价结构已明显恶化"
        )
    if (
        ratio >= float(cfg["up_down_ratio_strong"])
        and dryup <= float(cfg["pullback_dryup_strong"])
        and dist_count == 0
        and obv_slope > 0
    ):
        return 5, (
            f"上涨/下跌量比 {ratio:.2f}，最近回调量能仅为强攻量的 {dryup:.2f}，"
            "且未见放量阴线，量价配合极佳"
        )
    if (
        ratio >= float(cfg["up_down_ratio_healthy"])
        and dryup <= float(cfg["pullback_dryup_healthy"])
        and dist_count <= 1
    ):
        return 4, (
            f"上涨/下跌量比 {ratio:.2f}，回调量能比 {dryup:.2f}，"
            f"仅 {dist_count} 次分歧阴量，量价整体健康"
        )
    if ratio < float(cfg["up_down_ratio_weak"]) or dist_count == 2 or dryup > 1.05:
        return 2, (
            f"上涨/下跌量比 {ratio:.2f}，回调量能比 {dryup:.2f}，"
            "上涨承接一般，分歧偏多"
        )
    return 3, (
        f"上涨/下跌量比 {ratio:.2f}，回调量能比 {dryup:.2f}，"
        "量价中性，没有明显强化也未完全破坏"
    )


def _review_prepared_row_legacy(
    row: pd.Series | None,
    config: dict[str, Any],
    code: str,
    strategy: str = "b1",
) -> dict[str, Any]:
    if row is None or not bool(row.get("_ready", False)):
        return {
            "scores": {
                "trend_structure": 1,
                "price_position": 1,
                "volume_behavior": 1,
                "previous_abnormal_move": 1,
            },
            "total_score": 1.0,
            "signal_type": "distribution_risk",
            "verdict": "FAIL",
            "comment": "样本不足，无法完成第 4 步程序化复核。",
            "strategy": strategy,
            "code": code,
        }

    trend_score, trend_reasoning = _score_trend(row, config["trend"])
    pos_score, position_reasoning = _score_position(row, config["position"])
    vol_score, volume_reasoning = _score_volume_legacy(row, config["volume"])
    abn_score, abnormal_reasoning = _score_abnormal(row, config["abnormal"])
    scores = {
        "trend_structure": trend_score,
        "price_position": pos_score,
        "volume_behavior": vol_score,
        "previous_abnormal_move": abn_score,
    }
    total_score = round(
        trend_score * 0.20
        + pos_score * 0.20
        + vol_score * 0.30
        + abn_score * 0.30,
        1,
    )
    signal_type, signal_reasoning = _determine_signal(scores, total_score, config["thresholds"])
    verdict = _determine_verdict(scores, total_score, signal_type, config["thresholds"])
    comment = _generate_comment(row, scores, signal_type)
    return {
        "trend_reasoning": trend_reasoning,
        "position_reasoning": position_reasoning,
        "volume_reasoning": volume_reasoning,
        "abnormal_move_reasoning": abnormal_reasoning,
        "signal_reasoning": signal_reasoning,
        "scores": scores,
        "total_score": total_score,
        "signal_type": signal_type,
        "verdict": verdict,
        "comment": comment,
        "strategy": strategy,
        "code": code,
    }


def _industry_strength_by_date(
    base_frames: dict[str, pd.DataFrame],
    target_dates: list[pd.Timestamp],
    industry_by_code: dict[str, str],
    *,
    lookback_days: int,
    hot_top_pct: float,
) -> tuple[dict[pd.Timestamp, set[str]], dict[pd.Timestamp, dict[str, Any]]]:
    target_set = set(target_dates)
    returns_by_date: dict[pd.Timestamp, dict[str, list[float]]] = {
        dt: defaultdict(list) for dt in target_dates
    }

    for code, frame in base_frames.items():
        industry = industry_by_code.get(code)
        if not industry:
            continue
        close = frame["close"].astype(float)
        rets = close.pct_change(lookback_days)
        for dt in frame.index.intersection(target_set):
            value = rets.at[dt]
            if pd.notna(value):
                returns_by_date[dt][industry].append(float(value))

    hot_industries_by_date: dict[pd.Timestamp, set[str]] = {}
    rank_table_by_date: dict[pd.Timestamp, dict[str, Any]] = {}
    for dt in target_dates:
        items = []
        for industry, vals in returns_by_date.get(dt, {}).items():
            if not vals:
                continue
            items.append(
                {
                    "industry": industry,
                    "return": float(np.mean(vals)),
                    "count": len(vals),
                }
            )
        if not items:
            hot_industries_by_date[dt] = set()
            rank_table_by_date[dt] = {}
            continue
        ranked = sorted(items, key=lambda item: item["return"], reverse=True)
        top_n = max(1, int(math.ceil(len(ranked) * hot_top_pct)))
        hot_industries_by_date[dt] = {item["industry"] for item in ranked[:top_n]}
        rank_table_by_date[dt] = {
            item["industry"]: {
                "rank": idx + 1,
                "rank_pct": round((idx + 1) / float(len(ranked)), 6),
                "return": round(item["return"], 6),
                "member_count": int(item["count"]),
                "is_hot": idx < top_n,
            }
            for idx, item in enumerate(ranked)
        }
    return hot_industries_by_date, rank_table_by_date


def _simulate_trade(
    prices: pd.DataFrame,
    pick_date: pd.Timestamp,
    *,
    stop_days: int,
    stop_loss_pct: float,
    max_hold_days: int,
) -> dict[str, Any] | None:
    future = prices[prices.index > pick_date].head(max_hold_days).copy()
    if future.empty:
        return None

    entry = future.iloc[0]
    entry_open = float(entry["open"])
    if not np.isfinite(entry_open) or entry_open <= 0:
        return None

    stop_price = entry_open * (1.0 - stop_loss_pct)
    stop_window = future.head(stop_days)
    for idx, row in enumerate(stop_window.itertuples(index=False), start=1):
        low = float(getattr(row, "low"))
        if low <= stop_price:
            exit_date = pd.Timestamp(getattr(row, "date"))
            return {
                "entry_date": pd.Timestamp(entry["date"]),
                "entry_open": round(entry_open, 6),
                "exit_date": exit_date,
                "exit_price": round(stop_price, 6),
                "hold_days": idx,
                "ret": round(-stop_loss_pct, 6),
                "exit_reason": "stop_3d_5pct",
                "complete": True,
            }

    if len(future) < max_hold_days:
        last_row = future.iloc[-1]
        return {
            "entry_date": pd.Timestamp(entry["date"]),
            "entry_open": round(entry_open, 6),
            "exit_date": pd.Timestamp(last_row["date"]),
            "exit_price": round(float(last_row["close"]), 6),
            "hold_days": len(future),
            "ret": round(float(last_row["close"]) / entry_open - 1.0, 6),
            "exit_reason": "incomplete",
            "complete": False,
        }

    last_row = future.iloc[max_hold_days - 1]
    return {
        "entry_date": pd.Timestamp(entry["date"]),
        "entry_open": round(entry_open, 6),
        "exit_date": pd.Timestamp(last_row["date"]),
        "exit_price": round(float(last_row["close"]), 6),
        "hold_days": max_hold_days,
        "ret": round(float(last_row["close"]) / entry_open - 1.0, 6),
        "exit_reason": "max_hold_20d",
        "complete": True,
    }


def _metric_summary(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "trade_count": 0,
            "complete_trade_count": 0,
            "win_rate": None,
            "avg_win": None,
            "avg_loss": None,
            "payoff_ratio": None,
            "profit_factor": None,
            "mean_ret": None,
            "median_ret": None,
            "stop_hit_rate": None,
            "avg_hold_days": None,
        }

    complete = trades[trades["complete"] == True].copy()  # noqa: E712
    if complete.empty:
        return {
            "trade_count": int(len(trades)),
            "complete_trade_count": 0,
            "win_rate": None,
            "avg_win": None,
            "avg_loss": None,
            "payoff_ratio": None,
            "profit_factor": None,
            "mean_ret": None,
            "median_ret": None,
            "stop_hit_rate": None,
            "avg_hold_days": None,
        }

    wins = complete[complete["ret"] > 0]
    losses = complete[complete["ret"] < 0]
    avg_win = float(wins["ret"].mean()) if not wins.empty else None
    avg_loss = abs(float(losses["ret"].mean())) if not losses.empty else None
    payoff_ratio = None
    if avg_win is not None and avg_loss not in (None, 0.0):
        payoff_ratio = avg_win / avg_loss

    gross_profit = float(wins["ret"].sum()) if not wins.empty else 0.0
    gross_loss = abs(float(losses["ret"].sum())) if not losses.empty else 0.0
    profit_factor = None
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss

    return {
        "trade_count": int(len(trades)),
        "complete_trade_count": int(len(complete)),
        "win_rate": round(float((complete["ret"] > 0).mean()), 6),
        "avg_win": round(avg_win, 6) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 6) if avg_loss is not None else None,
        "payoff_ratio": round(payoff_ratio, 6) if payoff_ratio is not None else None,
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
        "mean_ret": round(float(complete["ret"].mean()), 6),
        "median_ret": round(float(complete["ret"].median()), 6),
        "stop_hit_rate": round(float((complete["exit_reason"] == "stop_3d_5pct").mean()), 6),
        "avg_hold_days": round(float(complete["hold_days"].mean()), 6),
    }


def _mode_trade_sets(events: pd.DataFrame, top_ns: Iterable[int]) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {
        "hot_b1_all": events.copy(),
    }
    for mode in ("legacy", "optimized"):
        signal_col = f"{mode}_signal_type"
        score_col = f"{mode}_total_score"
        volume_col = f"{mode}_volume_behavior"
        ranked = events.sort_values(
            ["pick_date", signal_col, score_col, volume_col, "code"],
            ascending=[True, True, False, False, True],
            key=lambda col: col.map(_signal_priority) if col.name == signal_col else col,
        )
        for top_n in top_ns:
            picked = ranked.groupby("pick_date", sort=True).head(int(top_n)).reset_index(drop=True)
            out[f"{mode}_top{int(top_n)}"] = picked
    return out


def _summarize_modes(events: pd.DataFrame, top_ns: Iterable[int]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    mode_frames = _mode_trade_sets(events, top_ns)
    for name, frame in mode_frames.items():
        summaries[name] = _metric_summary(frame)
    return summaries


def run_b1_hot_sector_backtest(
    *,
    trade_days: int = DEFAULT_LOOKBACK_TRADE_DAYS,
    hot_top_pct: float = DEFAULT_HOT_TOP_PCT,
    industry_lookback_days: int = DEFAULT_INDUSTRY_LOOKBACK,
    stop_days: int = DEFAULT_STOP_DAYS,
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
    max_hold_days: int = DEFAULT_MAX_HOLD_DAYS,
    top_ns: Iterable[int] = DEFAULT_TOP_NS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    preselect_cfg = load_preselect_config()
    review_cfg = load_review_config(ROOT / "config" / "quant_review.yaml")

    global_cfg = preselect_cfg.get("global", {})
    raw_dir = ROOT / global_cfg.get("data_dir", "./data/raw")
    if not raw_dir.exists():
        raise FileNotFoundError(f"raw data dir not found: {raw_dir}")

    target_dates = pd.DatetimeIndex(_reference_trade_dates(raw_dir, trade_days))
    if target_dates.empty:
        raise ValueError("no target trade dates found")
    start_date = target_dates[0].strftime("%Y-%m-%d")
    end_date = target_dates[-1].strftime("%Y-%m-%d")

    warmup_bars = _calc_backtest_warmup(preselect_cfg, review_cfg)
    raw_data = load_raw_data(
        str(raw_dir),
        start_date=start_date,
        end_date=end_date,
        warmup_bars=warmup_bars,
    )
    logger.info("loaded raw stocks: %d", len(raw_data))

    n_turnover_days = int(global_cfg.get("n_turnover_days", 43))
    top_m = int(global_cfg.get("top_m", 2000))
    base_frames = _prepare_base_frames(raw_data, n_turnover_days=n_turnover_days)
    raw_data.clear()
    del raw_data
    gc.collect()

    pool_by_date = TopTurnoverPoolBuilder(top_m=top_m).build(base_frames)
    pool_sets = {dt: set(codes) for dt, codes in pool_by_date.items()}
    industry_by_code = _industry_map(ROOT / "pipeline" / "stocklist.csv")
    hot_industries_by_date, hot_rank_table_by_date = _industry_strength_by_date(
        base_frames,
        list(target_dates),
        industry_by_code,
        lookback_days=industry_lookback_days,
        hot_top_pct=hot_top_pct,
    )
    selector = _build_b1_selector(preselect_cfg)

    events: list[dict[str, Any]] = []
    for idx, (code, base_df) in enumerate(base_frames.items(), start=1):
        if idx % 500 == 0:
            logger.info("processed base frames: %d / %d", idx, len(base_frames))
        industry = industry_by_code.get(code)
        if not industry:
            continue

        b1_frame = selector.prepare_df(base_df)
        picked_dates = [
            dt for dt in selector.vec_picks_from_prepared(
                b1_frame,
                start=target_dates[0],
                end=target_dates[-1],
            )
            if dt in target_dates and code in pool_sets.get(dt, set())
        ]
        if not picked_dates:
            continue

        review_frame = prepare_review_frame(base_df, review_cfg)
        for dt in picked_dates:
            hot_industries = hot_industries_by_date.get(dt, set())
            if industry not in hot_industries:
                continue
            trade = _simulate_trade(
                base_df,
                dt,
                stop_days=stop_days,
                stop_loss_pct=stop_loss_pct,
                max_hold_days=max_hold_days,
            )
            if trade is None:
                continue
            row = review_frame.loc[dt] if dt in review_frame.index else None
            optimized = review_prepared_row(row, config=review_cfg, code=code, strategy="b1")
            legacy = _review_prepared_row_legacy(row, config=review_cfg, code=code, strategy="b1")
            industry_info = hot_rank_table_by_date.get(dt, {}).get(industry, {})
            events.append(
                {
                    "pick_date": dt.strftime("%Y-%m-%d"),
                    "code": code,
                    "industry": industry,
                    "industry_rank": industry_info.get("rank"),
                    "industry_rank_pct": industry_info.get("rank_pct"),
                    "industry_return_20d": industry_info.get("return"),
                    "entry_date": trade["entry_date"].strftime("%Y-%m-%d"),
                    "entry_open": trade["entry_open"],
                    "exit_date": trade["exit_date"].strftime("%Y-%m-%d"),
                    "exit_price": trade["exit_price"],
                    "hold_days": trade["hold_days"],
                    "ret": trade["ret"],
                    "exit_reason": trade["exit_reason"],
                    "complete": trade["complete"],
                    "legacy_total_score": legacy["total_score"],
                    "legacy_signal_type": legacy["signal_type"],
                    "legacy_verdict": legacy["verdict"],
                    "legacy_volume_behavior": legacy["scores"]["volume_behavior"],
                    "legacy_comment": legacy["comment"],
                    "optimized_total_score": optimized["total_score"],
                    "optimized_signal_type": optimized["signal_type"],
                    "optimized_verdict": optimized["verdict"],
                    "optimized_volume_behavior": optimized["scores"]["volume_behavior"],
                    "optimized_comment": optimized["comment"],
                    "optimized_pullback_quality": optimized.get("pullback_quality"),
                    "optimized_pullback_negative_flags": "|".join(optimized.get("pullback_negative_flags", [])),
                }
            )

    events_df = pd.DataFrame(events).sort_values(["pick_date", "code"]).reset_index(drop=True) if events else pd.DataFrame()
    summary = {
        "date_range": {"start": start_date, "end": end_date},
        "trade_days": int(trade_days),
        "hot_sector_definition": {
            "source": "pipeline/stocklist.csv industry",
            "industry_lookback_days": int(industry_lookback_days),
            "hot_top_pct": float(hot_top_pct),
            "ranking": "equal-weight average 20d stock return by industry",
        },
        "exit_rule": {
            "entry": "next_trade_day_open",
            "stop": f"first_{int(stop_days)}d_intraday_-{stop_loss_pct * 100:.1f}pct",
            "take_profit": "none",
            "max_hold_days": int(max_hold_days),
        },
        "event_count": int(len(events_df)),
        "complete_event_count": int(events_df["complete"].sum()) if not events_df.empty else 0,
        "metrics": _summarize_modes(events_df, top_ns) if not events_df.empty else {},
    }
    return events_df, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="B1 hot-sector backtest with legacy vs optimized ranking")
    parser.add_argument("--trade-days", type=int, default=DEFAULT_LOOKBACK_TRADE_DAYS)
    parser.add_argument("--hot-top-pct", type=float, default=DEFAULT_HOT_TOP_PCT)
    parser.add_argument("--industry-lookback-days", type=int, default=DEFAULT_INDUSTRY_LOOKBACK)
    parser.add_argument("--stop-days", type=int, default=DEFAULT_STOP_DAYS)
    parser.add_argument("--stop-loss-pct", type=float, default=DEFAULT_STOP_LOSS_PCT)
    parser.add_argument("--max-hold-days", type=int, default=DEFAULT_MAX_HOLD_DAYS)
    parser.add_argument("--top-ns", default="1,3,5")
    args = parser.parse_args()

    top_ns = tuple(int(item.strip()) for item in str(args.top_ns).split(",") if item.strip())
    events_df, summary = run_b1_hot_sector_backtest(
        trade_days=args.trade_days,
        hot_top_pct=args.hot_top_pct,
        industry_lookback_days=args.industry_lookback_days,
        stop_days=args.stop_days,
        stop_loss_pct=args.stop_loss_pct,
        max_hold_days=args.max_hold_days,
        top_ns=top_ns,
    )

    out_dir = ROOT / "data" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    date_range = summary["date_range"]
    label = f"{date_range['start'].replace('-', '')}_{date_range['end'].replace('-', '')}"
    events_path = out_dir / f"b1_hot_sector_trades_{label}.csv"
    summary_path = out_dir / f"b1_hot_sector_summary_{label}.json"

    events_df.to_csv(events_path, index=False, encoding="utf-8")
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info("events: %s", events_path)
    logger.info("summary: %s", summary_path)
    logger.info("event_count: %d", len(events_df))
    logger.info("metrics: %s", json.dumps(summary.get("metrics", {}), ensure_ascii=False))


if __name__ == "__main__":
    main()
