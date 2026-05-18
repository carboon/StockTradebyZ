#!/usr/bin/env python3
"""Generate the experimental newB1 stock picks from local raw CSV data.

The script is intentionally independent from the production B1 pipeline so the
new rule set can be compared against the current candidates without overwriting
data/candidates.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from heapq import nlargest
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NEWB1_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
DEFAULT_OUTPUT_DIR = NEWB1_DIR / "output"
DEFAULT_STOCKLIST = ROOT / "pipeline" / "stocklist.csv"
DEFAULT_INDEX_CACHE = ROOT / "data" / "tushare_cache" / "index_daily"
MARKET_CACHE = ROOT / "data" / ".market_cache.json"

RAW_USECOLS = {
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "turnover_rate",
    "turnover_rate_f",
    "free_share",
    "circ_mv",
    "code",
}


@dataclass(frozen=True)
class RuleParams:
    top_m: int = 2000
    n_turnover_days: int = 43
    min_listed_bars: int = 120
    history_bars: int = 360
    kdj_n: int = 9
    j_threshold: float = 13.0
    w_span: int = 10
    y_ma1: int = 14
    y_ma2: int = 28
    y_ma3: int = 57
    y_ma4: int = 114
    n_shape_window: int = 60
    pivot_order: int = 2
    hard_max_rise_pct: float = 40.0
    absolute_max_rise_pct: float = 50.0
    hard_max_turnover_sum: float = 40.0
    ideal_rise_pct: float = 30.0
    ideal_turnover_sum: float = 30.0
    max_risk_pct: float = 5.0
    ideal_risk_pct: float = 3.0
    min_reward_risk: float = 3.0
    ideal_reward_risk: float = 5.0
    min_score: int = 75
    limit: int = 0


@dataclass
class NShape:
    valid: bool
    h0_idx: int | None = None
    p1_idx: int | None = None
    h1_idx: int | None = None
    p2_idx: int | None = None
    h0: float | None = None
    p1: float | None = None
    h1: float | None = None
    p2: float | None = None
    reason: str | None = None


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


def _pct(numerator: float, denominator: float) -> float:
    if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
        return float("nan")
    return numerator / denominator * 100.0


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


def is_blocked_name(name: str) -> bool:
    normalized = str(name or "").upper().replace(" ", "")
    if not normalized:
        return False
    blocked_tokens = ("ST", "*ST", "SST", "退", "退市")
    return any(token in normalized for token in blocked_tokens)


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


def compute_kdj_j(df: pd.DataFrame, n: int) -> pd.Series:
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()
    rsv = ((df["close"] - low_n) / (high_n - low_n + 1e-9) * 100.0).to_numpy(dtype=float)
    k = np.empty(len(rsv), dtype=float)
    d = np.empty(len(rsv), dtype=float)
    if len(rsv) == 0:
        return pd.Series([], index=df.index, dtype=float)
    k[0] = 50.0
    d[0] = 50.0
    for i in range(1, len(rsv)):
        k[i] = 2.0 / 3.0 * k[i - 1] + 1.0 / 3.0 * rsv[i]
        d[i] = 2.0 / 3.0 * d[i - 1] + 1.0 / 3.0 * k[i]
    return pd.Series(3.0 * k - 2.0 * d, index=df.index)


def compute_w_y(df: pd.DataFrame, params: RuleParams) -> tuple[pd.Series, pd.Series]:
    close = df["close"].astype(float)
    w = close.ewm(span=params.w_span, adjust=False).mean().ewm(span=params.w_span, adjust=False).mean()
    y = (
        close.rolling(params.y_ma1, min_periods=params.y_ma1).mean()
        + close.rolling(params.y_ma2, min_periods=params.y_ma2).mean()
        + close.rolling(params.y_ma3, min_periods=params.y_ma3).mean()
        + close.rolling(params.y_ma4, min_periods=params.y_ma4).mean()
    ) / 4.0
    return w, y


def find_local_pivots(values: np.ndarray, *, order: int, mode: str) -> list[int]:
    pivots: list[int] = []
    if len(values) < order * 2 + 1:
        return pivots
    for i in range(order, len(values) - order):
        window = values[i - order : i + order + 1]
        if mode == "high":
            if values[i] == np.nanmax(window) and values[i] > np.nanmax(np.delete(window, order)):
                pivots.append(i)
        else:
            if values[i] == np.nanmin(window) and values[i] < np.nanmin(np.delete(window, order)):
                pivots.append(i)
    return pivots


def detect_n_shape(df: pd.DataFrame, params: RuleParams) -> NShape:
    if len(df) < max(24, params.n_shape_window // 2):
        return NShape(valid=False, reason="not_enough_bars")

    start = max(0, len(df) - params.n_shape_window)
    high = df["high"].to_numpy(dtype=float)[start:]
    low = df["low"].to_numpy(dtype=float)[start:]
    close = df["close"].to_numpy(dtype=float)[start:]

    pivot_highs = find_local_pivots(high, order=params.pivot_order, mode="high")
    pivot_lows = find_local_pivots(low, order=params.pivot_order, mode="low")
    if len(pivot_highs) < 2:
        return NShape(valid=False, reason="not_enough_high_pivots")

    last_idx = len(high) - 1
    for h1_rel in reversed(pivot_highs):
        if h1_rel >= last_idx - 1:
            continue
        previous_highs = [idx for idx in pivot_highs if idx < h1_rel]
        for h0_rel in reversed(previous_highs):
            between_lows = [idx for idx in pivot_lows if h0_rel < idx < h1_rel]
            if between_lows:
                p1_rel = min(between_lows, key=lambda idx: low[idx])
            else:
                if h1_rel - h0_rel < 3:
                    continue
                p1_rel = int(np.nanargmin(low[h0_rel + 1 : h1_rel])) + h0_rel + 1

            after_high = low[h1_rel + 1 :]
            if len(after_high) == 0:
                continue
            p2_rel = int(np.nanargmin(after_high)) + h1_rel + 1

            h0 = float(high[h0_rel])
            h1 = float(high[h1_rel])
            p1 = float(low[p1_rel])
            p2 = float(low[p2_rel])
            current_close = float(close[-1])
            if h1 > h0 and p2 > p1 and current_close > p2:
                return NShape(
                    valid=True,
                    h0_idx=start + h0_rel,
                    p1_idx=start + p1_rel,
                    h1_idx=start + h1_rel,
                    p2_idx=start + p2_rel,
                    h0=h0,
                    p1=p1,
                    h1=h1,
                    p2=p2,
                )

    return NShape(valid=False, reason="no_higher_high_higher_low")


def weekly_trend_ok(df: pd.DataFrame) -> bool:
    if len(df) < 120:
        return False
    indexed = df.set_index("date", drop=False).sort_index()
    close = indexed["close"].astype(float)
    iso = close.index.isocalendar()
    week_key = iso.year.astype(str) + "-" + iso.week.astype(str).str.zfill(2)
    weekly = close.groupby(week_key).last()
    if len(weekly) < 30:
        return False

    ma_periods = (5, 10, 20, 30)
    up_count = 0
    for period in ma_periods:
        ma = weekly.rolling(period, min_periods=period).mean()
        if len(ma.dropna()) >= 2 and ma.iloc[-1] >= ma.iloc[-2] * 0.995:
            up_count += 1
    weekly_w = weekly.ewm(span=5, adjust=False).mean().ewm(span=5, adjust=False).mean()
    return bool(weekly.iloc[-1] > weekly_w.iloc[-1] and up_count >= 3)


def structure_clear(df: pd.DataFrame) -> bool:
    recent = df.tail(20).copy()
    if len(recent) < 10:
        return False
    prev_close = recent["close"].shift(1)
    amp = (recent["high"] - recent["low"]) / prev_close.replace(0, np.nan) * 100.0
    amp = amp.dropna()
    if amp.empty:
        return False
    quiet_ratio = float((amp < 8.0).mean())
    return bool(float(amp.median()) < 5.5 and quiet_ratio >= 0.70)


def _turnover_rate_series(df: pd.DataFrame) -> pd.Series:
    if "turnover_rate" in df.columns:
        rate = pd.to_numeric(df["turnover_rate"], errors="coerce")
    else:
        rate = pd.Series(np.nan, index=df.index, dtype=float)
    if rate.notna().any():
        return rate.fillna(0.0)

    if "free_share" not in df.columns:
        return pd.Series(0.0, index=df.index, dtype=float)

    free_share = pd.to_numeric(df["free_share"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")
    fallback = volume / free_share.replace(0, np.nan)
    return fallback.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def score_and_rules(df: pd.DataFrame, params: RuleParams) -> dict[str, Any]:
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    n_shape = detect_n_shape(df, params)
    w = float(df["W"].iloc[-1])
    y = float(df["Y"].iloc[-1])
    close = float(last["close"])
    low = float(last["low"])
    high = float(last["high"])
    prev_close = float(prev["close"])
    daily_pct = (close / prev_close - 1.0) * 100.0 if prev_close > 0 else float("nan")
    j = float(df["J"].iloc[-1])
    weekly_ok = weekly_trend_ok(df)
    clear = structure_clear(df)

    metrics: dict[str, Any] = {
        "j": j,
        "w": w,
        "y": y,
        "daily_pct": daily_pct,
        "weekly_trend_ok": weekly_ok,
        "n_shape_valid": n_shape.valid,
        "n_shape_reason": n_shape.reason,
    }
    rules: dict[str, bool] = {
        "stock_w_gt_y": bool(math.isfinite(w) and math.isfinite(y) and w > y),
        "close_above_y": bool(math.isfinite(y) and close >= y),
        "trend": bool(math.isfinite(w) and math.isfinite(y) and w > y and close >= y),
        "n_shape": n_shape.valid,
        "j_trigger": bool(j < params.j_threshold),
    }

    if not n_shape.valid or n_shape.p1_idx is None or n_shape.h1_idx is None or n_shape.p2_idx is None:
        metrics.update(
            {
                "rise_pct": None,
                "turnover_sum": None,
                "vol_shrink": None,
                "amp": None,
                "support_dist": None,
                "risk_pct": None,
                "reward_risk": None,
                "left_condition_count": 0,
                "right_condition_count": 0,
            }
        )
        rules.update(
            {
                "two_30": False,
                "risk_reward": False,
                "left_build": False,
                "right_wash": False,
            }
        )
        return {"metrics": metrics, "rules": rules, "stock_score": 0, "score_details": {}}

    p1_idx = int(n_shape.p1_idx)
    h1_idx = int(n_shape.h1_idx)
    p2_idx = int(n_shape.p2_idx)
    wave = df.iloc[p1_idx : h1_idx + 1].copy()
    right = df.iloc[h1_idx + 1 :].copy()
    if wave.empty:
        wave = df.iloc[max(0, h1_idx - 10) : h1_idx + 1].copy()
    if right.empty:
        right = df.tail(5).copy()

    rise_pct = (float(n_shape.h1 or 0.0) / float(n_shape.p1 or 1.0) - 1.0) * 100.0
    turnover_sum = float(wave.loc[wave["is_mid_big_bull"], "turnover_rate_calc"].sum())
    volshock_count = int(wave["vol_shock"].sum())
    strong_bull_count = int(wave["is_mid_big_bull"].sum())

    ma60 = df["close"].rolling(60, min_periods=20).mean()
    p1_ma60 = float(ma60.iloc[p1_idx]) if p1_idx < len(ma60) and pd.notna(ma60.iloc[p1_idx]) else float("nan")
    low_start = bool(math.isfinite(p1_ma60) and p1_ma60 > 0 and abs(float(n_shape.p1 or 0.0) / p1_ma60 - 1.0) <= 0.08)
    top_window = df.iloc[max(0, h1_idx - 2) : min(len(df), h1_idx + 3)]
    top_shrink = bool(
        not wave.empty
        and float(top_window["volume"].mean()) <= float(wave["volume"].max()) * 0.80
    )
    max_vol_idx = int(wave["volume"].to_numpy(dtype=float).argmax()) + wave.index[0]
    gap_pct = 0.0
    if max_vol_idx > 0:
        previous_close_for_gap = float(df["close"].iloc[max_vol_idx - 1])
        if previous_close_for_gap > 0:
            gap_pct = (float(df["open"].iloc[max_vol_idx]) / previous_close_for_gap - 1.0) * 100.0
    follow = df.iloc[max_vol_idx + 1 : min(len(df), max_vol_idx + 4)]
    isolated_gap_volume = bool(
        gap_pct >= 3.0
        and float(df["volume"].iloc[max_vol_idx]) >= float(df["volume"].iloc[max_vol_idx - 1]) * 2.0
        and (follow.empty or float(follow["close"].max()) <= float(df["close"].iloc[max_vol_idx]))
    )
    not_isolated_gap = not isolated_gap_volume

    vol_mean20_prev = float(df["volume"].shift(1).rolling(20, min_periods=5).mean().iloc[-1])
    if not math.isfinite(vol_mean20_prev) or vol_mean20_prev <= 0:
        vol_mean20_prev = float(df["volume"].tail(20).mean())
    vol_shrink = float(last["volume"]) / vol_mean20_prev if vol_mean20_prev > 0 else float("nan")
    amp = (high - low) / prev_close * 100.0 if prev_close > 0 else float("nan")
    support = float(n_shape.p2 or 0.0)
    support_dist = abs(close - support) / support * 100.0 if support > 0 else float("nan")
    stop_loss = min(low, support) * 0.99
    risk_pct = (close - stop_loss) / close * 100.0 if close > 0 and stop_loss > 0 else float("nan")
    upside_pct = max(0.0, (float(n_shape.h1 or 0.0) - close) / close * 100.0) if close > 0 else 0.0
    reward_risk = upside_pct / risk_pct if risk_pct > 0 else float("nan")

    recent_right = right.tail(12)
    quiet_k = bool(
        len(recent_right) > 0
        and float(((recent_right["pct_chg"] >= -2.0) & (recent_right["pct_chg"] <= 2.0)).mean()) >= 0.67
    )
    vol_ma5 = float(df["volume"].tail(5).mean()) if len(df) >= 5 else float("nan")
    vol_prev10 = float(df["volume"].iloc[max(0, len(df) - 15) : max(0, len(df) - 5)].mean())
    vol_contracting = bool(math.isfinite(vol_ma5) and math.isfinite(vol_prev10) and vol_prev10 > 0 and vol_ma5 <= vol_prev10)

    left_conditions = {
        "vol_shock": volshock_count >= 1,
        "mid_big_bull": strong_bull_count >= 1,
        "low_start": low_start,
        "not_one_wave": rise_pct <= params.hard_max_rise_pct,
        "top_shrink": top_shrink,
    }
    right_conditions = {
        "vol_shrink": bool(math.isfinite(vol_shrink) and vol_shrink <= 0.60),
        "vol_contracting": vol_contracting,
        "amp": bool(math.isfinite(amp) and amp < 4.0),
        "quiet_daily_pct": bool(math.isfinite(daily_pct) and -2.0 <= daily_pct <= 1.8),
        "quiet_k": quiet_k,
        "support_dist": bool(math.isfinite(support_dist) and support_dist <= 3.0),
        "j_ready": j < params.j_threshold,
    }
    left_count = sum(left_conditions.values())
    right_count = sum(right_conditions.values())

    two_30 = (
        math.isfinite(rise_pct)
        and math.isfinite(turnover_sum)
        and rise_pct <= params.hard_max_rise_pct
        and turnover_sum <= params.hard_max_turnover_sum
    )
    risk_reward = (
        math.isfinite(risk_pct)
        and math.isfinite(reward_risk)
        and risk_pct <= params.max_risk_pct
        and reward_risk >= params.min_reward_risk
    )

    score_details = {
        "cycle_trend": 0,
        "n_shape": 0,
        "left_build": 0,
        "right_wash": 0,
        "b1_signal": 0,
        "two_30": 0,
        "execution_value": 0,
    }
    if rules["stock_w_gt_y"]:
        score_details["cycle_trend"] += 6
    if rules["close_above_y"]:
        score_details["cycle_trend"] += 4
    if weekly_ok:
        score_details["cycle_trend"] += 5

    if float(n_shape.h1 or 0.0) > float(n_shape.h0 or 0.0):
        score_details["n_shape"] += 4
    if float(n_shape.p2 or 0.0) > float(n_shape.p1 or 0.0):
        score_details["n_shape"] += 4
    if float(n_shape.p2 or 0.0) > float(n_shape.p1 or 0.0):
        score_details["n_shape"] += 4
    if clear:
        score_details["n_shape"] += 3

    if left_conditions["vol_shock"]:
        score_details["left_build"] += 5
    if left_conditions["mid_big_bull"]:
        score_details["left_build"] += 4
    if left_conditions["top_shrink"]:
        score_details["left_build"] += 3
    if not_isolated_gap:
        score_details["left_build"] += 3

    if right_conditions["vol_shrink"]:
        score_details["right_wash"] += 5
    if right_conditions["vol_contracting"]:
        score_details["right_wash"] += 4
    if right_conditions["amp"]:
        score_details["right_wash"] += 3
    if right_conditions["quiet_daily_pct"]:
        score_details["right_wash"] += 3

    if j < params.j_threshold:
        score_details["b1_signal"] += 4
    if j < 0:
        score_details["b1_signal"] += 3
    if j < -10:
        score_details["b1_signal"] += 3

    if rise_pct <= params.ideal_rise_pct:
        score_details["two_30"] += 5
    if turnover_sum <= params.ideal_turnover_sum:
        score_details["two_30"] += 5

    if risk_pct <= params.ideal_risk_pct:
        score_details["execution_value"] += 3
    if reward_risk >= params.ideal_reward_risk:
        score_details["execution_value"] += 2

    metrics.update(
        {
            "h0": n_shape.h0,
            "p1": n_shape.p1,
            "h1": n_shape.h1,
            "p2": n_shape.p2,
            "rise_pct": rise_pct,
            "turnover_sum": turnover_sum,
            "vol_shock_count": volshock_count,
            "strong_bull_count": strong_bull_count,
            "vol_shrink": vol_shrink,
            "amp": amp,
            "support_dist": support_dist,
            "risk_pct": risk_pct,
            "upside_pct": upside_pct,
            "reward_risk": reward_risk,
            "left_condition_count": left_count,
            "right_condition_count": right_count,
            "left_conditions": left_conditions,
            "right_conditions": right_conditions,
            "support": support,
            "stop_loss": stop_loss,
        }
    )
    rules.update(
        {
            "two_30": bool(two_30),
            "risk_reward": bool(risk_reward),
            "left_build": left_count >= 2,
            "right_wash": right_count >= 3,
            "not_absolute_overheat": bool(rise_pct <= params.absolute_max_rise_pct),
        }
    )

    stock_score = int(sum(score_details.values()))
    return {
        "metrics": metrics,
        "rules": rules,
        "stock_score": stock_score,
        "score_details": score_details,
    }


def analyze_raw_file(path: Path, pick_date: pd.Timestamp, params: RuleParams) -> dict[str, Any] | None:
    code = path.stem.zfill(6)
    try:
        df = pd.read_csv(path, usecols=lambda col: str(col).lower() in RAW_USECOLS)
    except Exception as exc:
        return {"code": code, "error": f"read_failed:{exc}"}

    if df.empty or "date" not in df.columns:
        return None

    df.columns = [str(col).lower() for col in df.columns]
    for col in ("open", "close", "high", "low", "volume", "turnover_rate", "free_share", "circ_mv"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date", "open", "close", "high", "low", "volume"])
    df = df[df["date"] <= pick_date].sort_values("date").reset_index(drop=True)
    if df.empty or pd.Timestamp(df["date"].iloc[-1]).normalize() != pick_date:
        return None

    listed_bars = int(len(df))
    if len(df) > params.history_bars:
        df = df.tail(params.history_bars).reset_index(drop=True)

    df["signed_turnover"] = (df["open"] + df["close"]) / 2.0 * df["volume"]
    df["turnover_n"] = df["signed_turnover"].rolling(params.n_turnover_days, min_periods=1).sum()
    df["prev_close"] = df["close"].shift(1)
    df["pct_chg"] = (df["close"] / df["prev_close"] - 1.0) * 100.0
    df["turnover_rate_calc"] = _turnover_rate_series(df)
    df["is_mid_big_bull"] = (df["close"] > df["open"]) & (df["pct_chg"] >= 3.0)
    df["vol_shock"] = df["volume"] >= df["volume"].shift(1) * 2.0
    df["W"], df["Y"] = compute_w_y(df, params)
    df["J"] = compute_kdj_j(df, params.kdj_n)

    scored = score_and_rules(df, params)
    circ_mv_now = _safe_float(df["circ_mv"].iloc[-1]) if "circ_mv" in df.columns else None
    circ_mv_20 = _safe_float(df["circ_mv"].iloc[-21]) if "circ_mv" in df.columns and len(df) >= 21 else None
    result = {
        "code": code,
        "date": pick_date.strftime("%Y-%m-%d"),
        "listed_bars": listed_bars,
        "close": float(df["close"].iloc[-1]),
        "turnover_n": float(df["turnover_n"].iloc[-1]),
        "circ_mv": circ_mv_now,
        "circ_mv_20": circ_mv_20,
        **scored,
    }
    return result


def latest_index_file(index_cache: Path, ts_code: str, pick_date: pd.Timestamp) -> Path | None:
    if not index_cache.exists():
        return None
    candidates = sorted(index_cache.glob(f"{ts_code}_*.csv"))
    if not candidates:
        return None
    pick_int = int(pick_date.strftime("%Y%m%d"))

    def end_date(path: Path) -> int:
        try:
            return int(path.stem.rsplit("_", 1)[1])
        except Exception:
            return 0

    usable = [path for path in candidates if end_date(path) >= pick_int]
    if usable:
        return sorted(usable, key=end_date)[-1]
    return sorted(candidates, key=end_date)[-1]


def load_index_state(index_cache: Path, pick_date: pd.Timestamp, params: RuleParams) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    for ts_code in ("000905.SH", "399006.SZ"):
        path = latest_index_file(index_cache, ts_code, pick_date)
        if path is None:
            continue
        try:
            frame = pd.read_csv(path)
        except Exception:
            continue
        if "trade_date" not in frame.columns or "close" not in frame.columns:
            continue
        frame["trade_date"] = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d", errors="coerce").dt.normalize()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["trade_date", "close"])
        frame = frame[frame["trade_date"] <= pick_date].sort_values("trade_date").reset_index(drop=True)
        if len(frame) < params.y_ma4 + 1:
            continue
        proxy = pd.DataFrame(
            {
                "close": frame["close"],
                "open": frame["close"],
                "high": frame["close"],
                "low": frame["close"],
                "volume": 1.0,
            }
        )
        w, y = compute_w_y(proxy, params)
        ret20 = frame["close"].iloc[-1] / frame["close"].shift(20).iloc[-1] - 1.0 if len(frame) > 20 else float("nan")
        details.append(
            {
                "ts_code": ts_code,
                "close": _round(frame["close"].iloc[-1], 4),
                "w": _round(w.iloc[-1], 4),
                "y": _round(y.iloc[-1], 4),
                "w_gt_y": bool(w.iloc[-1] > y.iloc[-1]) if pd.notna(y.iloc[-1]) else False,
                "return_20d_pct": _round(ret20 * 100.0, 4),
                "source": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
            }
        )
    return {"details": details, "market_w_gt_y": any(item["w_gt_y"] for item in details)}


def build_market_state(
    rows: list[dict[str, Any]],
    index_cache: Path,
    pick_date: pd.Timestamp,
    params: RuleParams,
    *,
    skip_market_gate: bool,
) -> dict[str, Any]:
    circ_pairs = [
        (_safe_float(row.get("circ_mv")), _safe_float(row.get("circ_mv_20")))
        for row in rows
    ]
    circ_pairs = [
        (now, previous)
        for now, previous in circ_pairs
        if now is not None and previous is not None
    ]
    am_pct = None
    if circ_pairs and len(circ_pairs) >= 100:
        now_sum = float(np.nansum([item[0] for item in circ_pairs]))
        prev_sum = float(np.nansum([item[1] for item in circ_pairs]))
        if prev_sum > 0:
            am_pct = (now_sum / prev_sum - 1.0) * 100.0

    index_state = load_index_state(index_cache, pick_date, params)
    market_w_gt_y = bool(index_state["market_w_gt_y"])
    if skip_market_gate:
        passed = True
        reason = "skipped"
    elif am_pct is None and not index_state["details"]:
        passed = True
        reason = "no_market_data_neutral_pass"
    else:
        am_ok = am_pct is not None and am_pct >= 4.0
        am_bad = am_pct is not None and am_pct <= -2.3
        passed = bool((am_ok or market_w_gt_y) and not am_bad)
        reason = "passed" if passed else "failed"

    market_score = 0
    if am_pct is not None and am_pct >= 4.0:
        market_score += 10
    if market_w_gt_y:
        market_score += 5
    return {
        "passed": passed,
        "reason": reason,
        "am_pct": _round(am_pct, 4),
        "market_w_gt_y": market_w_gt_y,
        "score": market_score,
        **index_state,
    }


def grade_for_score(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 75:
        return "B"
    if score >= 65:
        return "C"
    return "FAIL"


def build_candidates(
    rows: list[dict[str, Any]],
    names: dict[str, str],
    market_state: dict[str, Any],
    params: RuleParams,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    eligible_rows = [row for row in rows if row.get("turnover_n") is not None]
    if params.top_m > 0 and params.top_m < len(eligible_rows):
        pool = nlargest(params.top_m, eligible_rows, key=lambda row: float(row["turnover_n"]))
        pool.sort(key=lambda row: (-float(row["turnover_n"]), str(row["code"])))
    else:
        pool = sorted(eligible_rows, key=lambda row: (-float(row["turnover_n"]), str(row["code"])))
    rank_by_code = {str(row["code"]): rank for rank, row in enumerate(pool, start=1)}

    counters = {
        "raw_rows": len(rows),
        "pool_size": len(pool),
        "basic_failed": 0,
        "market_failed": 0,
        "hard_failed": 0,
        "score_failed": 0,
        "qualified": 0,
        "selected": 0,
    }
    candidates: list[dict[str, Any]] = []
    hard_keys = (
        "basic",
        "market",
        "trend",
        "n_shape",
        "j_trigger",
        "two_30",
        "risk_reward",
        "not_absolute_overheat",
    )

    for row in pool:
        code = str(row["code"]).zfill(6)
        name = names.get(code, "")
        rules = dict(row.get("rules") or {})
        rules["basic"] = bool(row.get("listed_bars", 0) >= params.min_listed_bars and not is_blocked_name(name))
        rules["market"] = bool(market_state.get("passed", True))
        if not rules["basic"]:
            counters["basic_failed"] += 1
            continue
        if not rules["market"]:
            counters["market_failed"] += 1
            continue
        hard_pass = all(bool(rules.get(key)) for key in hard_keys)
        if not hard_pass:
            counters["hard_failed"] += 1
            continue

        score_details = dict(row.get("score_details") or {})
        score_details["market"] = int(market_state.get("score") or 0)
        score = int(row.get("stock_score") or 0) + int(market_state.get("score") or 0)
        if score < params.min_score:
            counters["score_failed"] += 1
            continue

        metrics = row.get("metrics") or {}
        item = {
            "code": code,
            "name": name,
            "date": row["date"],
            "strategy": "new_b1",
            "close": _round(row["close"], 4),
            "turnover_n": _round(row["turnover_n"], 4),
            "score": score,
            "grade": grade_for_score(score),
            "active_pool_rank": rank_by_code[code],
            "extra": {
                "kdj_j": _round(metrics.get("j"), 6),
                "rise_pct": _round(metrics.get("rise_pct"), 4),
                "turnover_sum": _round(metrics.get("turnover_sum"), 4),
                "vol_shrink": _round(metrics.get("vol_shrink"), 4),
                "amp": _round(metrics.get("amp"), 4),
                "support_dist": _round(metrics.get("support_dist"), 4),
                "risk_pct": _round(metrics.get("risk_pct"), 4),
                "reward_risk": _round(metrics.get("reward_risk"), 4),
                "support": _round(metrics.get("support"), 4),
                "stop_loss": _round(metrics.get("stop_loss"), 4),
                "left_condition_count": metrics.get("left_condition_count"),
                "right_condition_count": metrics.get("right_condition_count"),
                "rules": rules,
                "score_details": score_details,
                "market": {
                    "am_pct": market_state.get("am_pct"),
                    "market_w_gt_y": market_state.get("market_w_gt_y"),
                    "score": market_state.get("score"),
                },
            },
        }
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            -int(item["score"]),
            int(item["active_pool_rank"]),
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
    json_path = output_dir / f"new_b1_{pick_date}.json"
    latest_path = output_dir / "new_b1_latest.json"
    csv_path = output_dir / f"new_b1_{pick_date}.csv"

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
                "kdj_j": extra.get("kdj_j"),
                "rise_pct": extra.get("rise_pct"),
                "turnover_sum": extra.get("turnover_sum"),
                "vol_shrink": extra.get("vol_shrink"),
                "amp": extra.get("amp"),
                "support_dist": extra.get("support_dist"),
                "risk_pct": extra.get("risk_pct"),
                "reward_risk": extra.get("reward_risk"),
                "support": extra.get("support"),
                "stop_loss": extra.get("stop_loss"),
            }
        )
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return {"json": str(json_path), "latest": str(latest_path), "csv": str(csv_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate experimental newB1 candidates.")
    parser.add_argument("--date", help="Pick date, e.g. 2026-05-08. Defaults to data/.market_cache.json latest date.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stocklist", type=Path, default=DEFAULT_STOCKLIST)
    parser.add_argument("--index-cache", type=Path, default=DEFAULT_INDEX_CACHE)
    parser.add_argument("--top-m", type=int, default=RuleParams.top_m)
    parser.add_argument("--min-score", type=int, default=RuleParams.min_score)
    parser.add_argument(
        "--limit",
        type=int,
        default=RuleParams.limit,
        help="Maximum output count after scoring. 0 means output all qualified candidates.",
    )
    parser.add_argument("--workers", type=int, default=max(4, min(16, (os.cpu_count() or 8))))
    parser.add_argument("--skip-market-gate", action="store_true", help="Do not block candidates by market timing.")
    parser.add_argument("--max-rise-pct", type=float, default=RuleParams.hard_max_rise_pct)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if int(args.limit) < 0:
        raise ValueError("--limit must be >= 0; use 0 to output all qualified candidates")
    params = RuleParams(
        top_m=args.top_m,
        min_score=args.min_score,
        limit=args.limit,
        hard_max_rise_pct=args.max_rise_pct,
    )
    pick_date = resolve_pick_date(args.raw_dir, args.date)
    files = sorted(args.raw_dir.glob("*.csv"))
    if not files:
        raise RuntimeError(f"No raw CSV files found: {args.raw_dir}")

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as executor:
        futures = {
            executor.submit(analyze_raw_file, path, pick_date, params): path
            for path in files
        }
        for future in as_completed(futures):
            item = future.result()
            if item is None:
                continue
            if item.get("error"):
                errors += 1
                continue
            rows.append(item)

    names = load_stock_names(args.stocklist)
    market_state = build_market_state(
        rows,
        args.index_cache,
        pick_date,
        params,
        skip_market_gate=bool(args.skip_market_gate),
    )
    candidates, counters = build_candidates(rows, names, market_state, params)
    elapsed = round(time.perf_counter() - started, 3)
    pick_date_str = pick_date.strftime("%Y-%m-%d")
    payload = {
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "pick_date": pick_date_str,
        "strategy": "new_b1",
        "candidates": candidates,
        "meta": {
            "elapsed_seconds": elapsed,
            "raw_dir": str(args.raw_dir),
            "source_files": len(files),
            "read_errors": errors,
            "params": asdict(params),
            "market": market_state,
            "counters": counters,
            "notes": [
                "Liquidity pool uses the existing B1 precondition: 43-day rolling signed turnover top M.",
                "W/Y uses the current codebase's zxdq/zxdkx approximation: double EMA span 10 versus MA(14/28/57/114) average.",
                "AM is approximated by 20-bar total circulating market value change when circ_mv is available.",
            ],
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
