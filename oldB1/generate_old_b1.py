#!/usr/bin/env python3
"""Generate oldB1 candidates using the current production B1 pipeline rules.

The CLI intentionally mirrors ``newB1/generate_new_b1.py`` so the two scripts
can be compared side by side with the same invocation pattern.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
OLD_B1_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
DEFAULT_OUTPUT_DIR = OLD_B1_DIR / "output"
DEFAULT_STOCKLIST = ROOT / "pipeline" / "stocklist.csv"
DEFAULT_INDEX_CACHE = ROOT / "data" / "tushare_cache" / "index_daily"
MARKET_CACHE = ROOT / "data" / ".market_cache.json"
PRESELECT_CONFIG = ROOT / "config" / "rules_preselect.yaml"

for path in (ROOT, ROOT / "pipeline", ROOT / "agent"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)

from Selector import B1Selector  # noqa: E402
from pipeline_core import MarketDataPreparer, TopTurnoverPoolBuilder  # noqa: E402
from quant_reviewer import load_config as load_review_config  # noqa: E402
from review_prefilter import Step4Prefilter  # noqa: E402
from select_stock import _calc_warmup, _resolve_pick_date, load_raw_data  # noqa: E402


@dataclass(frozen=True)
class RuleParams:
    top_m: int = 2000
    n_turnover_days: int = 43
    min_bars_buffer: int = 10
    kdj_n: int = 9
    j_threshold: float = 15.0
    j_q_threshold: float = 0.10
    zx_m1: int = 14
    zx_m2: int = 28
    zx_m3: int = 57
    zx_m4: int = 114
    zxdq_span: int = 10
    wma_short: int = 10
    wma_mid: int = 20
    wma_long: int = 30
    max_vol_lookback: int = 20
    limit: int = 0


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _round(value: Any, digits: int = 6) -> float | None:
    num = _safe_float(value)
    if num is None:
        return None
    return round(num, digits)


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_stock_names(stocklist_path: Path) -> dict[str, str]:
    if not stocklist_path.exists():
        return {}
    frame = pd.read_csv(stocklist_path, dtype={"symbol": str})
    if "symbol" not in frame.columns or "name" not in frame.columns:
        return {}
    return {
        str(row.symbol).zfill(6): str(row.name)
        for row in frame[["symbol", "name"]].itertuples(index=False)
    }


def resolve_pick_date(raw_dir: Path, requested: str | None) -> pd.Timestamp:
    if requested:
        target = pd.Timestamp(requested).normalize()
    else:
        target = None
        if MARKET_CACHE.exists():
            try:
                payload = json.loads(MARKET_CACHE.read_text(encoding="utf-8"))
                latest = payload.get("latest_trade_date")
                if latest:
                    target = pd.Timestamp(latest).normalize()
            except Exception:
                target = None

    probes = [raw_dir / "000001.csv", raw_dir / "600000.csv"]
    probes.extend(sorted(raw_dir.glob("*.csv"))[:20])
    for path in probes:
        if not path.exists():
            continue
        try:
            dates = pd.read_csv(path, usecols=["date"])["date"]
        except Exception:
            continue
        dates = pd.to_datetime(dates, errors="coerce").dropna().sort_values()
        if dates.empty:
            continue
        if target is None:
            return pd.Timestamp(dates.iloc[-1]).normalize()
        eligible = dates[dates <= target]
        if not eligible.empty:
            return pd.Timestamp(eligible.iloc[-1]).normalize()

    raise RuntimeError(f"Cannot resolve pick date from raw data: {raw_dir}")


def build_params(preselect_cfg: dict[str, Any], top_m: int, limit: int) -> RuleParams:
    global_cfg = preselect_cfg.get("global", {}) or {}
    b1_cfg = preselect_cfg.get("b1", {}) or {}
    zx_vals = sorted(
        [
            int(b1_cfg.get("zx_m1", 14)),
            int(b1_cfg.get("zx_m2", 28)),
            int(b1_cfg.get("zx_m3", 57)),
            int(b1_cfg.get("zx_m4", 114)),
        ]
    )
    return RuleParams(
        top_m=int(top_m),
        n_turnover_days=int(global_cfg.get("n_turnover_days", 43)),
        min_bars_buffer=int(global_cfg.get("min_bars_buffer", 10)),
        kdj_n=9,
        j_threshold=float(b1_cfg.get("j_threshold", 15.0)),
        j_q_threshold=float(b1_cfg.get("j_q_threshold", 0.10)),
        zx_m1=zx_vals[0],
        zx_m2=zx_vals[1],
        zx_m3=zx_vals[2],
        zx_m4=zx_vals[3],
        zxdq_span=10,
        wma_short=10,
        wma_mid=20,
        wma_long=30,
        max_vol_lookback=20,
        limit=int(limit),
    )


def build_selector(params: RuleParams) -> B1Selector:
    return B1Selector(
        j_threshold=params.j_threshold,
        j_q_threshold=params.j_q_threshold,
        kdj_n=params.kdj_n,
        zx_m1=params.zx_m1,
        zx_m2=params.zx_m2,
        zx_m3=params.zx_m3,
        zx_m4=params.zx_m4,
        zxdq_span=params.zxdq_span,
        wma_short=params.wma_short,
        wma_mid=params.wma_mid,
        wma_long=params.wma_long,
        max_vol_lookback=params.max_vol_lookback,
    )


def evaluate_market_gate(pick_date: str, skip_market_gate: bool) -> dict[str, Any]:
    if skip_market_gate:
        return {
            "passed": True,
            "skipped": True,
            "summary": "跳过市场环境 gate",
            "details": [],
        }

    try:
        review_cfg = load_review_config()
        prefilter = Step4Prefilter(review_cfg)
        result = prefilter.check_market_regime_only(pick_date)
        result["skipped"] = False
        result["source"] = "quant_review.prefilter.market_regime"
        return result
    except Exception as exc:
        return {
            "passed": True,
            "skipped": False,
            "summary": f"市场环境检查失败，按当前主流程继续执行: {exc}",
            "details": [],
            "error": str(exc),
            "source": "quant_review.prefilter.market_regime",
        }


def build_pool_ranks(
    prepared: dict[str, pd.DataFrame],
    pool_codes: list[str],
    pick_ts: pd.Timestamp,
) -> dict[str, int]:
    pairs: list[tuple[float, str]] = []
    for code in pool_codes:
        df = prepared.get(code)
        if df is None or pick_ts not in df.index:
            continue
        turnover_n = _safe_float(df.at[pick_ts, "turnover_n"])
        if turnover_n is None:
            continue
        pairs.append((turnover_n, code))
    pairs.sort(key=lambda item: (-item[0], item[1]))
    return {code: idx for idx, (_, code) in enumerate(pairs, start=1)}


def analyze_pool_code(
    code: str,
    df: pd.DataFrame,
    *,
    pick_ts: pd.Timestamp,
    selector: B1Selector,
) -> dict[str, Any] | None:
    if df is None or pick_ts not in df.index:
        return None

    prepared = selector.prepare_df(df)
    if pick_ts not in prepared.index:
        return None

    row = prepared.loc[pick_ts]
    hist = prepared.loc[:pick_ts]
    if hist.empty:
        return None

    passed = bool(selector.vec_picks_from_prepared(prepared, start=pick_ts, end=pick_ts))
    kdj_ok = bool(selector._kdj_filter(hist))
    zx_ok = bool(selector._zx_filter(hist))
    wma_ok = bool(selector._wma_filter(hist))
    max_vol_ok = bool(selector._max_vol_filter(hist))

    j_series = hist["J"].dropna() if "J" in hist.columns else pd.Series(dtype=float)
    j_q_value = (
        float(j_series.quantile(selector._kdj_filter.j_q_threshold))
        if not j_series.empty
        else float("nan")
    )

    zxdq = _safe_float(row.get("zxdq"))
    zxdkx = _safe_float(row.get("zxdkx"))
    close = _safe_float(row.get("close"))

    return {
        "code": str(code).zfill(6),
        "date": pick_ts.strftime("%Y-%m-%d"),
        "listed_bars": int(len(df)),
        "close": close,
        "turnover_n": _safe_float(row.get("turnover_n")),
        "b1_passed": passed,
        "metrics": {
            "kdj_j": _safe_float(row.get("J")),
            "kdj_k": _safe_float(row.get("K")),
            "kdj_d": _safe_float(row.get("D")),
            "kdj_q10": j_q_value,
            "zxdq": zxdq,
            "zxdkx": zxdkx,
            "close_gt_zxdkx": bool(close is not None and zxdkx is not None and close > zxdkx),
            "zxdq_gt_zxdkx": bool(zxdq is not None and zxdkx is not None and zxdq > zxdkx),
            "wma_bull": bool(row.get("wma_bull", False)),
            "max_vol_not_bearish": max_vol_ok,
        },
        "rules": {
            "kdj_low": kdj_ok,
            "zx_condition": zx_ok,
            "weekly_ma_bull": wma_ok,
            "max_vol_not_bearish": max_vol_ok,
            "b1_passed": passed,
        },
    }


def build_candidates(
    results: list[dict[str, Any]],
    names: dict[str, str],
    rank_by_code: dict[str, int],
    market_state: dict[str, Any],
    params: RuleParams,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counters = {
        "pool_size": len(results),
        "b1_failed": 0,
        "qualified": 0,
        "selected": 0,
    }
    candidates: list[dict[str, Any]] = []

    for row in results:
        code = str(row["code"]).zfill(6)
        if not row.get("b1_passed", False):
            counters["b1_failed"] += 1
            continue

        metrics = dict(row.get("metrics") or {})
        item = {
            "code": code,
            "name": names.get(code, ""),
            "date": row["date"],
            "strategy": "old_b1",
            "close": _round(row.get("close"), 4),
            "turnover_n": _round(row.get("turnover_n"), 4),
            "score": None,
            "grade": "PASS",
            "active_pool_rank": rank_by_code.get(code),
            "extra": {
                "listed_bars": row.get("listed_bars"),
                "kdj_j": _round(metrics.get("kdj_j"), 6),
                "kdj_k": _round(metrics.get("kdj_k"), 6),
                "kdj_d": _round(metrics.get("kdj_d"), 6),
                "kdj_q10": _round(metrics.get("kdj_q10"), 6),
                "zxdq": _round(metrics.get("zxdq"), 6),
                "zxdkx": _round(metrics.get("zxdkx"), 6),
                "close_gt_zxdkx": metrics.get("close_gt_zxdkx"),
                "zxdq_gt_zxdkx": metrics.get("zxdq_gt_zxdkx"),
                "wma_bull": metrics.get("wma_bull"),
                "max_vol_not_bearish": metrics.get("max_vol_not_bearish"),
                "rules": row.get("rules") or {},
                "market": {
                    "passed": market_state.get("passed"),
                    "summary": market_state.get("summary"),
                    "skipped": market_state.get("skipped", False),
                },
                "pipeline_strategy": "b1",
            },
        }
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            int(item["active_pool_rank"]) if item.get("active_pool_rank") is not None else 10**9,
            str(item["code"]),
        )
    )
    counters["qualified"] = len(candidates)
    if params.limit > 0:
        candidates = candidates[: params.limit]
    counters["selected"] = len(candidates)
    return candidates, counters


def write_outputs(payload: dict[str, Any], output_dir: Path, pick_date: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"old_b1_{pick_date}.json"
    latest_path = output_dir / "old_b1_latest.json"
    csv_path = output_dir / f"old_b1_{pick_date}.csv"

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")

    rows = []
    for item in payload["candidates"]:
        extra = item.get("extra", {})
        rows.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "date": item.get("date"),
                "close": item.get("close"),
                "score": item.get("score"),
                "grade": item.get("grade"),
                "active_pool_rank": item.get("active_pool_rank"),
                "turnover_n": item.get("turnover_n"),
                "listed_bars": extra.get("listed_bars"),
                "kdj_j": extra.get("kdj_j"),
                "kdj_q10": extra.get("kdj_q10"),
                "zxdq": extra.get("zxdq"),
                "zxdkx": extra.get("zxdkx"),
                "wma_bull": extra.get("wma_bull"),
                "max_vol_not_bearish": extra.get("max_vol_not_bearish"),
            }
        )
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return {"json": str(json_path), "latest": str(latest_path), "csv": str(csv_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate oldB1 candidates with the current production rule set.")
    parser.add_argument("--date", help="Pick date, e.g. 2026-05-08. Defaults to data/.market_cache.json latest date.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stocklist", type=Path, default=DEFAULT_STOCKLIST)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--top-m", type=int, default=2000)
    parser.add_argument("--min-score", type=int, default=75)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum output count after筛选. 0 means output all qualified candidates.",
    )
    parser.add_argument("--workers", type=int, default=max(4, min(16, (os.cpu_count() or 8))))
    parser.add_argument("--skip-market-gate", action="store_true", help="Do not block candidates by market timing.")
    parser.add_argument("--max-rise-pct", type=float, default=40.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if int(args.limit) < 0:
        raise ValueError("--limit must be >= 0; use 0 to output all qualified candidates")

    files = sorted(args.raw_dir.glob("*.csv"))
    if not files:
        raise RuntimeError(f"No raw CSV files found: {args.raw_dir}")

    preselect_cfg = _load_yaml(PRESELECT_CONFIG)
    params = build_params(preselect_cfg, top_m=int(args.top_m), limit=int(args.limit))

    requested_pick = resolve_pick_date(args.raw_dir, args.date)
    started = time.perf_counter()
    raw_data = load_raw_data(str(args.raw_dir), end_date=requested_pick.strftime("%Y-%m-%d"))
    warmup = _calc_warmup(preselect_cfg, params.min_bars_buffer)
    preparer = MarketDataPreparer(
        end_date=requested_pick,
        warmup_bars=warmup,
        n_turnover_days=params.n_turnover_days,
        selector=None,
        n_jobs=max(1, int(args.workers)),
    )
    prepared = preparer.prepare(raw_data)
    pick_ts = _resolve_pick_date(prepared, requested_pick.strftime("%Y-%m-%d"))
    pick_date_str = pick_ts.strftime("%Y-%m-%d")

    market_state = evaluate_market_gate(pick_date_str, bool(args.skip_market_gate))
    pool_codes = TopTurnoverPoolBuilder(top_m=params.top_m).build(prepared).get(pick_ts, [])
    rank_by_code = build_pool_ranks(prepared, pool_codes, pick_ts)

    names = load_stock_names(args.stocklist)
    selector = build_selector(params)
    analysis_results: list[dict[str, Any]] = []
    read_errors = 0

    if market_state.get("passed", True):
        with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
            futures = {
                executor.submit(
                    analyze_pool_code,
                    code,
                    prepared.get(code),
                    pick_ts=pick_ts,
                    selector=selector,
                ): code
                for code in pool_codes
            }
            for future in as_completed(futures):
                try:
                    item = future.result()
                except Exception:
                    read_errors += 1
                    continue
                if item is not None:
                    analysis_results.append(item)

    candidates, counters = build_candidates(analysis_results, names, rank_by_code, market_state, params)
    counters["raw_rows"] = len(prepared)
    counters["pool_size"] = len(pool_codes)
    counters["market_blocked"] = 0 if market_state.get("passed", True) else 1

    elapsed = round(time.perf_counter() - started, 3)
    payload = {
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "pick_date": pick_date_str,
        "strategy": "old_b1",
        "candidates": candidates,
        "meta": {
            "elapsed_seconds": elapsed,
            "raw_dir": str(args.raw_dir),
            "source_files": len(files),
            "read_errors": read_errors,
            "params": asdict(params),
            "market": market_state,
            "counters": counters,
            "notes": [
                "Selection logic reuses the current production path: turnover pool + B1Selector + optional Step4 market gate.",
                "Accepted --min-score, --max-rise-pct, and --index-cache for CLI compatibility with newB1, but oldB1 does not use them in screening.",
                "Weekly MA settings follow the current B1Selector defaults: 10/20/30 weeks.",
            ],
            "compatibility": {
                "ignored_cli_args": {
                    "min_score": args.min_score,
                    "max_rise_pct": args.max_rise_pct,
                    "index_cache": str(args.index_cache),
                }
            },
        },
    }
    paths = write_outputs(payload, args.output_dir, pick_date_str)

    print(
        json.dumps(
            {
                "pick_date": pick_date_str,
                "selected": len(candidates),
                "elapsed_seconds": elapsed,
                "market_passed": market_state.get("passed"),
                "paths": paths,
                "counters": counters,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
