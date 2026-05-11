"""
backtest_quant.py
~~~~~~~~~~~~~~~~~
完整滚动回测：

1. 保持第 2 步初选规则不变
2. 对每个候选日运行新的第 4 步程序化复核
3. 统计各持有周期的分层收益 / 胜率 / 批次资金曲线

用法：
    python -m pipeline.backtest_quant
    python -m pipeline.backtest_quant --start-date 2023-01-01 --end-date 2026-04-16
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "agent"))

from Selector import B1Selector, BrickChartSelector  # noqa: E402
from pipeline_core import TopTurnoverPoolBuilder  # noqa: E402
from select_stock import load_config as load_preselect_config, load_raw_data  # noqa: E402
from quant_reviewer import (  # noqa: E402
    load_config as load_review_config,
    min_bars_required,
    prepare_review_frame,
    review_prepared_row,
)
from review_prefilter import Step4Prefilter  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backtest_quant")


def _calc_backtest_warmup(cfg: dict[str, Any]) -> int:
    warmup = 120
    global_cfg = cfg.get("global", {})
    min_bars_buffer = int(global_cfg.get("min_bars_buffer", 10))

    b1_cfg = cfg.get("b1", {})
    if b1_cfg.get("enabled", True):
        warmup = max(warmup, int(b1_cfg.get("zx_m4", 371)) + min_bars_buffer)

    brick_cfg = cfg.get("brick", {})
    if brick_cfg.get("enabled", True):
        warmup = max(
            warmup,
            int(brick_cfg.get("wma_long", 120)) * 5 + min_bars_buffer,
            int(brick_cfg.get("zxdkx_m4", 114)) + min_bars_buffer,
        )
    return warmup


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


def _build_brick_selector(cfg: dict[str, Any]) -> BrickChartSelector:
    brick = cfg["brick"]
    return BrickChartSelector(
        daily_return_threshold=float(brick.get("daily_return_threshold", 0.05)),
        brick_growth_ratio=float(brick.get("brick_growth_ratio", 1.0)),
        min_prior_green_bars=int(brick.get("min_prior_green_bars", 1)),
        zxdq_ratio=brick.get("zxdq_ratio"),
        zxdq_span=int(brick.get("zxdq_span", 10)),
        require_zxdq_gt_zxdkx=bool(brick.get("require_zxdq_gt_zxdkx", True)),
        zxdkx_m1=int(brick.get("zxdkx_m1", 14)),
        zxdkx_m2=int(brick.get("zxdkx_m2", 28)),
        zxdkx_m3=int(brick.get("zxdkx_m3", 57)),
        zxdkx_m4=int(brick.get("zxdkx_m4", 114)),
        require_weekly_ma_bull=bool(brick.get("require_weekly_ma_bull", True)),
        wma_short=int(brick.get("wma_short", 20)),
        wma_mid=int(brick.get("wma_mid", 60)),
        wma_long=int(brick.get("wma_long", 120)),
        n=int(brick.get("n", 4)),
        m1=int(brick.get("m1", 4)),
        m2=int(brick.get("m2", 6)),
        m3=int(brick.get("m3", 6)),
        t=float(brick.get("t", 4.0)),
        shift1=float(brick.get("shift1", 90.0)),
        shift2=float(brick.get("shift2", 100.0)),
        sma_w1=int(brick.get("sma_w1", 1)),
        sma_w2=int(brick.get("sma_w2", 1)),
        sma_w3=int(brick.get("sma_w3", 1)),
    )


def _stats(values: pd.Series) -> dict[str, Any]:
    vals = values.dropna()
    if vals.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "win_rate": None,
        }
    return {
        "count": int(len(vals)),
        "mean": round(float(vals.mean()), 6),
        "median": round(float(vals.median()), 6),
        "win_rate": round(float((vals > 0).mean()), 6),
    }


def _equity_stats(values: pd.Series) -> dict[str, Any]:
    vals = values.dropna().sort_index()
    if vals.empty:
        return {
            "count": 0,
            "mean": None,
            "win_rate": None,
            "final_equity": None,
            "max_drawdown": None,
        }
    equity = (1.0 + vals).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return {
        "count": int(len(vals)),
        "mean": round(float(vals.mean()), 6),
        "win_rate": round(float((vals > 0).mean()), 6),
        "final_equity": round(float(equity.iloc[-1]), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
    }


def _score_bucket_labels(boundaries: list[float]) -> tuple[list[float], list[str]]:
    labels: list[str] = []
    prev: float | None = None
    for bound in boundaries:
        if prev is None:
            labels.append(f"<{bound:.1f}")
        else:
            labels.append(f"{prev:.1f}-{bound:.1f}")
        prev = bound
    labels.append(f">={boundaries[-1]:.1f}")
    bins = [-np.inf, *boundaries, np.inf]
    return bins, labels


def _summarize_events(events: pd.DataFrame, horizons: list[int], score_buckets: list[float]) -> dict[str, Any]:
    if events.empty:
        return {
            "total_events": 0,
            "verdict_counts": {},
            "signal_type_counts": {},
            "strategy_counts": {},
            "prefilter_counts": {},
            "prefilter_reason_counts": {},
            "horizons": {f"{h}d": {} for h in horizons},
        }

    events = events.copy()
    events["total_score"] = pd.to_numeric(events["total_score"], errors="coerce")
    summary: dict[str, Any] = {
        "total_events": int(len(events)),
        "verdict_counts": {k: int(v) for k, v in events["verdict"].value_counts().sort_index().items()},
        "signal_type_counts": {k: int(v) for k, v in events["signal_type"].value_counts().sort_index().items()},
        "strategy_counts": {k: int(v) for k, v in events["strategy"].value_counts().sort_index().items()},
        "prefilter_counts": {k: int(v) for k, v in events["prefilter_status"].value_counts().sort_index().items()},
        "prefilter_reason_counts": {},
        "horizons": {},
    }

    blocked_reasons = (
        events["prefilter_blocked_by"]
        .fillna("")
        .astype(str)
        .str.split("|", regex=False)
        .explode()
        .str.strip()
    )
    blocked_reasons = blocked_reasons[blocked_reasons != ""]
    summary["prefilter_reason_counts"] = {
        k: int(v) for k, v in blocked_reasons.value_counts().sort_index().items()
    }

    bins, labels = _score_bucket_labels(score_buckets)
    bucketed = events.copy()
    bucketed["score_bucket"] = pd.cut(bucketed["total_score"], bins=bins, labels=labels, right=False)

    for horizon in horizons:
        ret_col = f"ret_{horizon}d"
        by_verdict = {
            verdict: _stats(group[ret_col])
            for verdict, group in bucketed.groupby("verdict", sort=True)
        }
        by_signal = {
            signal: _stats(group[ret_col])
            for signal, group in bucketed.groupby("signal_type", sort=True)
        }
        by_strategy = {
            strategy: _stats(group[ret_col])
            for strategy, group in bucketed.groupby("strategy", sort=True)
        }
        by_prefilter = {
            status: _stats(group[ret_col])
            for status, group in bucketed.groupby("prefilter_status", sort=True)
        }
        by_bucket = {
            str(bucket): _stats(group[ret_col])
            for bucket, group in bucketed.groupby("score_bucket", sort=True, observed=False)
        }

        pass_daily = (
            bucketed[bucketed["verdict"] == "PASS"]
            .groupby("pick_date", sort=True)[ret_col]
            .mean()
        )
        prefilter_passed_by_size = {
            str(bucket): _stats(group[ret_col])
            for bucket, group in bucketed[bucketed["prefilter_status"] == "passed"].groupby("size_bucket", sort=True)
        }
        pass_by_size = {
            str(bucket): _stats(group[ret_col])
            for bucket, group in bucketed[bucketed["verdict"] == "PASS"].groupby("size_bucket", sort=True)
        }
        summary["horizons"][f"{horizon}d"] = {
            "by_verdict": by_verdict,
            "by_signal_type": by_signal,
            "by_strategy": by_strategy,
            "by_prefilter_status": by_prefilter,
            "by_score_bucket": by_bucket,
            "prefilter_passed_by_size_bucket": prefilter_passed_by_size,
            "pass_by_size_bucket": pass_by_size,
            "pass_daily_batch_curve": _equity_stats(pass_daily),
        }

    return summary


def run_backtest(
    *,
    preselect_config_path: str | None = None,
    review_config_path: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    skip_market_regime_check: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    preselect_cfg = load_preselect_config(preselect_config_path)
    review_cfg = load_review_config(Path(review_config_path) if review_config_path else None)
    global_cfg = preselect_cfg.get("global", {})
    raw_dir = ROOT / global_cfg.get("data_dir", "./data/raw")
    warmup_bars = max(_calc_backtest_warmup(preselect_cfg), min_bars_required(review_cfg))
    raw_data = load_raw_data(
        str(raw_dir),
        end_date=end_date,
        start_date=start_date,
        warmup_bars=warmup_bars,
    )

    n_turnover_days = int(global_cfg.get("n_turnover_days", 43))
    top_m = int(global_cfg.get("top_m", 2000))
    horizons = [int(v) for v in review_cfg.get("backtest", {}).get("holding_periods", [1, 3, 5, 10])]
    score_buckets = [float(v) for v in review_cfg.get("backtest", {}).get("score_buckets", [3.2, 3.5, 4.0])]
    disabled_strategies = {str(s).lower() for s in review_cfg.get("disabled_strategies", [])}
    prefilter = Step4Prefilter(review_cfg)

    # 提前检查市场环境，获取需要跳过的日期
    blocked_trade_dates: set[pd.Timestamp] = set()
    market_regime_summary: dict[str, Any] = {}
    if not skip_market_regime_check and prefilter.enabled:
        market_cfg = prefilter.config.get("market_regime", {}) or {}
        if bool(market_cfg.get("enabled", False)):
            logger.info("检查市场环境...")
            # 获取交易日历中的日期范围
            all_trade_dates = sorted({
                dt.strftime("%Y-%m-%d")
                for df in raw_data.values()
                if "date" in df.columns
                for dt in pd.to_datetime(df["date"]).dt.date
            })
            if start_date:
                all_trade_dates = [d for d in all_trade_dates if d >= start_date]
            if end_date:
                all_trade_dates = [d for d in all_trade_dates if d <= end_date]

            for trade_date_str in all_trade_dates:
                result = prefilter.check_market_regime_only(trade_date_str)
                if not result.get("passed", True):
                    blocked_trade_dates.add(pd.Timestamp(trade_date_str))
                    market_regime_summary[trade_date_str] = result

            if blocked_trade_dates:
                blocked_list = sorted({d.strftime("%Y-%m-%d") for d in blocked_trade_dates})
                logger.info(
                    "市场环境不佳，跳过 %d 个交易日: %s",
                    len(blocked_list),
                    ", ".join(blocked_list[:5]) + ("..." if len(blocked_list) > 5 else ""),
                )

    logger.info("读取股票数量: %d", len(raw_data))
    base_frames = _prepare_base_frames(raw_data, n_turnover_days=n_turnover_days)
    raw_data.clear()
    del raw_data
    gc.collect()
    logger.info("基础预处理完成: %d", len(base_frames))

    pool_by_date = TopTurnoverPoolBuilder(top_m=top_m).build(base_frames)
    pool_sets = {dt: set(codes) for dt, codes in pool_by_date.items()}
    logger.info("流动性池日期数: %d", len(pool_sets))

    b1_selector = _build_b1_selector(preselect_cfg)
    brick_enabled = bool(preselect_cfg.get("brick", {}).get("enabled", True))
    use_brick = brick_enabled and "brick" not in disabled_strategies
    brick_selector = _build_brick_selector(preselect_cfg) if use_brick else None

    start_ts = pd.to_datetime(start_date) if start_date else None
    end_ts = pd.to_datetime(end_date) if end_date else None
    events: list[dict[str, Any]] = []

    for code, base_df in tqdm(base_frames.items(), desc="滚动回测", ncols=90):
        b1_frame = b1_selector.prepare_df(base_df)
        brick_frame = brick_selector.prepare_df(base_df) if brick_selector is not None else None

        picked: dict[pd.Timestamp, str] = {}
        for dt in b1_selector.vec_picks_from_prepared(b1_frame, start=start_ts, end=end_ts):
            codes_today = pool_sets.get(dt)
            if codes_today and code in codes_today and "b1" not in disabled_strategies:
                picked.setdefault(dt, "b1")
        if brick_selector is not None and brick_frame is not None:
            for dt in brick_selector.vec_picks_from_prepared(brick_frame, start=start_ts, end=end_ts):
                codes_today = pool_sets.get(dt)
                if codes_today and code in codes_today:
                    picked.setdefault(dt, "brick")

        # 过滤掉市场环境不佳的日期
        if blocked_trade_dates:
            picked = {dt: strategy for dt, strategy in picked.items() if dt not in blocked_trade_dates}

        if not picked:
            continue

        review_frame = prepare_review_frame(base_df, review_cfg)
        entry_open = base_df["open"].shift(-1)
        entry_date = base_df["date"].shift(-1)
        exit_dates = {h: base_df["date"].shift(-h) for h in horizons}
        returns = {h: base_df["close"].shift(-h) / entry_open - 1.0 for h in horizons}

        for dt, strategy in sorted(picked.items()):
            prefilter_result = prefilter.evaluate(code=code, pick_date=dt, price_df=base_df)
            result = review_prepared_row(review_frame.loc[dt], config=review_cfg, code=code, strategy=strategy)
            result["prefilter"] = prefilter_result

            pf_details = (result.get("prefilter") or {}).get("details", {})
            market_regime = pf_details.get("market_regime") or {}
            event: dict[str, Any] = {
                "pick_date": dt.strftime("%Y-%m-%d"),
                "code": code,
                "strategy": strategy,
                "close": round(float(base_df.at[dt, "close"]), 6) if dt in base_df.index else None,
                "turnover_n": round(float(base_df.at[dt, "turnover_n"]), 6) if dt in base_df.index else None,
                "kdj_j": round(float(b1_frame.at[dt, "J"]), 6) if dt in b1_frame.index and pd.notna(b1_frame.at[dt, "J"]) else None,
                "signal_type": result["signal_type"],
                "verdict": result["verdict"],
                "total_score": result["total_score"],
                "comment": result.get("comment"),
                "trend_structure": result["scores"]["trend_structure"],
                "price_position": result["scores"]["price_position"],
                "volume_behavior": result["scores"]["volume_behavior"],
                "previous_abnormal_move": result["scores"]["previous_abnormal_move"],
                "prefilter_status": "passed" if prefilter_result.get("passed", True) else "blocked",
                "prefilter_summary": prefilter_result.get("summary"),
                "prefilter_blocked_by": "|".join(prefilter_result.get("blocked_by", [])),
                "size_bucket": pf_details.get("size_bucket"),
                "circ_mv_100m": pf_details.get("circ_mv_100m"),
                "listing_days": pf_details.get("listing_days"),
                "is_st": pf_details.get("is_st"),
                "unlock_ratio_to_free_share": pf_details.get("unlock_ratio_to_free_share"),
                "sw_l1_industry": pf_details.get("sw_l1_industry"),
                "industry_rank": pf_details.get("industry_rank"),
                "industry_rank_pct": pf_details.get("industry_rank_pct"),
                "industry_relative_strength": pf_details.get("industry_relative_strength"),
                "industry_filter_pass": pf_details.get("industry_filter_pass"),
                "market_regime_pass": market_regime.get("passed"),
                "details_json": result,
            }

            next_entry_date = entry_date.at[dt]
            event["entry_date"] = next_entry_date.strftime("%Y-%m-%d") if pd.notna(next_entry_date) else None
            for horizon in horizons:
                ret_val = returns[horizon].at[dt]
                exit_dt = exit_dates[horizon].at[dt]
                event[f"exit_date_{horizon}d"] = exit_dt.strftime("%Y-%m-%d") if pd.notna(exit_dt) else None
                event[f"ret_{horizon}d"] = round(float(ret_val), 6) if pd.notna(ret_val) else None

            events.append(event)

    events_df = pd.DataFrame(events)
    if not events_df.empty:
        events_df = events_df.sort_values(["pick_date", "code"]).reset_index(drop=True)
    summary = _summarize_events(events_df, horizons=horizons, score_buckets=score_buckets)
    if not events_df.empty:
        summary["date_range"] = {
            "start": str(events_df["pick_date"].min()),
            "end": str(events_df["pick_date"].max()),
        }
    else:
        summary["date_range"] = {"start": start_date, "end": end_date}
    return events_df, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="第 2 步 + 第 4 步完整滚动回测")
    parser.add_argument("--preselect-config", default=None, help="初选配置文件路径")
    parser.add_argument("--review-config", default=str(ROOT / "config" / "quant_review.yaml"), help="复核配置文件路径")
    parser.add_argument("--start-date", default=None, help="回测起始日期 YYYY-MM-DD（默认自动最早）")
    parser.add_argument("--end-date", default=None, help="回测结束日期 YYYY-MM-DD（默认自动最新）")
    args = parser.parse_args()

    events_df, summary = run_backtest(
        preselect_config_path=args.preselect_config,
        review_config_path=args.review_config,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    review_cfg = load_review_config(Path(args.review_config))
    out_dir = Path(review_cfg.get("backtest", {}).get("output_dir", ROOT / "data" / "backtest"))
    out_dir.mkdir(parents=True, exist_ok=True)

    date_range = summary["date_range"]
    start_label = (date_range.get("start") or "auto").replace("-", "")
    end_label = (date_range.get("end") or "auto").replace("-", "")

    events_path = out_dir / f"quant_roll_events_{start_label}_{end_label}.csv"
    summary_path = out_dir / f"quant_roll_summary_{start_label}_{end_label}.json"
    events_df.to_csv(events_path, index=False, encoding="utf-8")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info("事件文件: %s", events_path)
    logger.info("汇总文件: %s", summary_path)
    logger.info("总事件数: %d", len(events_df))
    logger.info("判定计数: %s", summary.get("verdict_counts", {}))


if __name__ == "__main__":
    main()
