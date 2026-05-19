#!/usr/bin/env python3
"""Generate newB1 candidates using the 7-type B1 buy signals from newB1_readme.

This script implements the 超级B1选股公式 (Super B1 Stock Selection Formula)
which defines 7 types of B1 buy signals:
1. 超卖缩量拐头B - Oversold volume contraction with RSI turn
2. 超卖缩量B - Oversold volume contraction
3. 原始B1 - Original B1 pattern
4. 超卖超缩量B - Oversold extreme volume contraction
5. 回踩白线B - Pullback to white line (strong trend)
6. 回踩超级B - Pullback for super bull stocks
7. 回踩黄线B - Pullback to yellow line (medium-term trend)
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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NEWB1_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
DEFAULT_OUTPUT_DIR = NEWB1_DIR / "output"
DEFAULT_STOCKLIST = ROOT / "pipeline" / "stocklist.csv"
MARKET_CACHE = ROOT / "data" / ".market_cache.json"

RAW_USECOLS = {
    "date",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "turnover_rate",
    "free_share",
    "circ_mv",
}


@dataclass(frozen=True)
class RuleParams:
    """Parameters for the new B1 selection rules."""
    top_m: int = 2000
    n_turnover_days: int = 43
    min_listed_bars: int = 120
    history_bars: int = 360

    # Trend line parameters (趋势白线, 大哥黄线)
    trend_ema_span: int = 10  # EMA(EMA(C,10),10)
    yellow_ma1: int = 14
    yellow_ma2: int = 28
    yellow_ma3: int = 57
    yellow_ma4: int = 114

    # Short/Long term parameters
    short_term_n: int = 3
    long_term_n: int = 21

    # BBI parameters
    bbi_ma1: int = 3
    bbi_ma2: int = 6
    bbi_ma3: int = 12
    bbi_ma4: int = 24

    # KDJ parameters
    kdj_n: int = 9

    # RSI parameters
    rsi_n: int = 3

    # Volatility parameters (N, M)
    n_volatility: int = 20
    m_volatility: int = 50

    # Volume thresholds
    max_vol_lookback: int = 40

    limit: int = 0


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Convert value to Python bool (not numpy.bool_)."""
    try:
        return bool(value)
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 6) -> float | None:
    num = _safe_float(value)
    if num is None:
        return None
    return round(num, digits)


def _make_json_serializable(obj: Any) -> Any:
    """Convert numpy/pandas types to Python native types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _make_json_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_json_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer, np.floating)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif pd.isna(obj):
        return None
    return obj


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


def compute_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """Compute KDJ indicator."""
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()
    rsv = ((df["close"] - low_n) / (high_n - low_n + 1e-9) * 100.0)

    K = np.empty(len(rsv), dtype=float)
    D = np.empty(len(rsv), dtype=float)
    K[0] = D[0] = 50.0
    for i in range(1, len(rsv)):
        K[i] = 2.0 / 3.0 * K[i - 1] + 1.0 / 3.0 * rsv.iloc[i]
        D[i] = 2.0 / 3.0 * D[i - 1] + 1.0 / 3.0 * K[i]
    J = 3.0 * K - 2.0 * D

    return df.assign(K=K, D=D, J=J)


def compute_rsi(df: pd.DataFrame, n: int = 3) -> pd.Series:
    """Compute RSI indicator using SMA (通达信 style)."""
    lc = df["close"].shift(1)
    temp1 = (df["close"] - lc).clip(lower=0)
    temp2 = (df["close"] - lc).abs()

    # SMA in 通达信: SMA(X,N,M) = M*X + (1-M)*REF(SMA,1)
    # where M is typically 1
    rsi_ma = temp1.ewm(alpha=1.0/n, adjust=False).mean()
    abs_ma = temp2.ewm(alpha=1.0/n, adjust=False).mean()

    rsi = rsi_ma / (abs_ma + 1e-9) * 100.0
    return rsi


def compute_indicators(df: pd.DataFrame, params: RuleParams) -> pd.DataFrame:
    """Compute all required indicators for the new B1 strategy."""
    df = df.copy()

    # 趋势白线 = EMA(EMA(C,10),10)
    trend_white = df["close"].ewm(
        span=params.trend_ema_span, adjust=False
    ).mean().ewm(span=params.trend_ema_span, adjust=False).mean()

    # 大哥黄线 = (MA(C,14)+MA(C,28)+MA(C,57)+MA(C,114))/4
    yellow = (
        df["close"].rolling(params.yellow_ma1, min_periods=1).mean()
        + df["close"].rolling(params.yellow_ma2, min_periods=1).mean()
        + df["close"].rolling(params.yellow_ma3, min_periods=1).mean()
        + df["close"].rolling(params.yellow_ma4, min_periods=1).mean()
    ) / 4.0

    # 短期 = 100*(C-LLV(L,3))/(HHV(C,3)-LLV(L,3))
    llv_l_short = df["low"].rolling(params.short_term_n, min_periods=1).min()
    hhv_c_short = df["close"].rolling(params.short_term_n, min_periods=1).max()
    short_term = 100 * (df["close"] - llv_l_short) / (hhv_c_short - llv_l_short + 1e-9)

    # 长期 = 100*(C-LLV(L,21))/(HHV(C,21)-LLV(L,21))
    llv_l_long = df["low"].rolling(params.long_term_n, min_periods=1).min()
    hhv_c_long = df["close"].rolling(params.long_term_n, min_periods=1).max()
    long_term = 100 * (df["close"] - llv_l_long) / (hhv_c_long - llv_l_long + 1e-9)

    # BBI = (MA(C,3)+MA(C,6)+MA(C,12)+MA(C,24))/4
    bbi = (
        df["close"].rolling(params.bbi_ma1, min_periods=1).mean()
        + df["close"].rolling(params.bbi_ma2, min_periods=1).mean()
        + df["close"].rolling(params.bbi_ma3, min_periods=1).mean()
        + df["close"].rolling(params.bbi_ma4, min_periods=1).mean()
    ) / 4.0

    # KDJ
    kdj = compute_kdj(df, params.kdj_n)

    # RSI(3)
    rsi = compute_rsi(df, params.rsi_n)

    # Assign all indicators
    df["trend_white"] = trend_white
    df["yellow"] = yellow
    df["short_term"] = short_term
    df["long_term"] = long_term
    df["bbi"] = bbi
    df["K"] = kdj["K"]
    df["D"] = kdj["D"]
    df["J"] = kdj["J"]
    df["RSI"] = rsi

    return df


def check_pattern_conditions(df: pd.DataFrame) -> dict[str, bool]:
    """Check pattern conditions: 单针下20, 聚宝盆, 双叉戟, 红肥绿瘦."""
    if len(df) < 30:
        return {
            "single_needle_down": False,
            "treasure_basin": False,
            "trident": False,
            "red_fat_green_thin": False,
        }

    short = df["short_term"]
    long_term = df["long_term"]

    # 单针下20
    single_needle = (
        (short.iloc[-1] <= 20 and long_term.iloc[-1] >= 75)
        or ((long_term.iloc[-1] - short.iloc[-1]) >= 70)
    )

    # 聚宝盆
    long_gte75 = (long_term >= 75).rolling(8, min_periods=1).sum()
    short_lte70 = (short <= 70).rolling(7, min_periods=1).sum()
    short_lte50 = (short <= 50).rolling(8, min_periods=1).sum()
    treasure_basin = (long_gte75.iloc[-1] >= 6 and
                      short_lte70.iloc[-1] >= 4 and
                      short_lte50.iloc[-1] >= 1)

    # 双叉戟
    long_always_gte75 = (long_term >= 75).rolling(8, min_periods=1).apply(
        lambda x: x.all(), raw=False
    ).fillna(False).rolling(8, min_periods=1).sum()
    short_lte50_6 = (short <= 50).rolling(6, min_periods=1).sum()
    short_lte20_7 = (short <= 20).rolling(7, min_periods=1).sum()
    trident = (long_always_gte75.iloc[-1] >= 8 and
               short_lte50_6.iloc[-1] >= 2 and
               short_lte20_7.iloc[-1] >= 1)

    # 红肥绿瘦
    c_ge_o = (df["close"] >= df["open"]).rolling(15, min_periods=1).sum()
    c_gt_prev = (df["close"] > df["close"].shift(1)).rolling(11, min_periods=1).sum()
    red_fat_green_thin = (c_ge_o.iloc[-1] > 7) or (c_gt_prev.iloc[-1] > 5)

    return {
        "single_needle_down": bool(single_needle),
        "treasure_basin": bool(treasure_basin),
        "trident": bool(trident),
        "red_fat_green_thin": bool(red_fat_green_thin),
    }


def check_volume_conditions(df: pd.DataFrame, max_lookback: int = 40) -> dict[str, bool]:
    """Check volume conditions: 大绿棒, 缩量 variants."""
    if len(df) < 5:
        return {
            "not_big_green": False,
            "big_green_far": False,
            "volume_shrink": False,
            "pullback_shrink": False,
            "moderate_shrink": False,
            "extreme_shrink": False,
        }

    vol = df["volume"]
    open_price = df["open"]
    close = df["close"]

    # Find days with max volume in the lookback period
    hhv_vol_20 = vol.rolling(20, min_periods=1).max()
    hhv_vol_30 = vol.rolling(30, min_periods=1).max()
    hhv_vol_50 = vol.rolling(50, min_periods=1).max()

    # VDAY = distance to day with highest volume in 40 days
    vol_40 = vol.tail(40)
    if len(vol_40) > 0:
        vday_idx = vol_40.idxmax() if hasattr(vol_40, 'idxmax') else len(df) - 40 + vol_40.to_numpy().argmax()
    else:
        vday_idx = df.index[-1]

    # Get the row at vday_idx
    if vday_idx in df.index:
        vday_loc = df.index.get_loc(vday_idx)
        vday_close = close.iloc[vday_loc]
        vday_close_prev = close.iloc[vday_loc - 1] if vday_loc > 0 else vday_close
        vday_open = open_price.iloc[vday_loc]

        # 不是大绿棒: 收盘价 >= 前一日收盘价 OR 收盘价 >= 开盘价
        not_big_green = (vday_close >= vday_close_prev) or (vday_close >= vday_open)
        big_green_far = not_big_green and (len(df) - vday_loc >= 15)
    else:
        not_big_green = True
        big_green_far = False

    vol_today = vol.iloc[-1]

    # 缩量 conditions
    volume_shrink = (vol_today < hhv_vol_20.iloc[-1] * 0.416) or (
        vol_today < hhv_vol_50.iloc[-1] / 3
    )
    pullback_shrink = (vol_today < hhv_vol_20.iloc[-1] * 0.45) or (
        vol_today < hhv_vol_50.iloc[-1] / 3
    )
    moderate_shrink = (vol_today < hhv_vol_20.iloc[-1] * 0.618) or (
        vol_today < hhv_vol_50.iloc[-1] / 3
    )
    extreme_shrink = (vol_today < hhv_vol_30.iloc[-1] / 4) or (
        vol_today < hhv_vol_50.iloc[-1] / 6
    )

    return {
        "not_big_green": bool(not_big_green),
        "big_green_far": bool(big_green_far),
        "volume_shrink": bool(volume_shrink),
        "pullback_shrink": bool(pullback_shrink),
        "moderate_shrink": bool(moderate_shrink),
        "extreme_shrink": bool(extreme_shrink),
    }


def check_volatility_conditions(df: pd.DataFrame, n: int = 20, m: int = 50) -> dict[str, Any]:
    """Check volatility conditions: 近期异动, 远期异动, 洗盘异动."""
    if len(df) < max(n, m):
        return {
            "recent_move": False,
            "far_move": False,
            "super_move": False,
            "wash_move": False,
            "recent_amp_pct": None,
            "far_amp_pct": None,
        }

    high_n = df["high"].rolling(n, min_periods=1).max()
    low_n = df["low"].rolling(n, min_periods=1).min()
    recent_amp = (high_n - low_n) / (low_n + 1e-9) * 100

    high_m = df["high"].rolling(m, min_periods=1).max()
    low_m = df["low"].rolling(m, min_periods=1).min()
    far_amp = (high_m - low_m) / (low_m + 1e-9) * 100

    # 近期异动
    high_12 = df["high"].rolling(12, min_periods=1).max()
    low_14 = df["low"].rolling(14, min_periods=1).min()
    special_move = (high_12 - low_14) / (low_14 + 1e-9) * 100
    recent_move = (recent_amp.iloc[-1] >= 15) or (special_move.iloc[-1] >= 11)

    # 远期异动
    far_move = far_amp.iloc[-1] >= 30

    # 超级异动
    super_move = recent_amp.iloc[-1] >= 60

    # 洗盘异动
    pattern = check_pattern_conditions(df)
    wash_move = (pattern["single_needle_down"] or
                 pattern["treasure_basin"] or
                 pattern["trident"])

    return {
        "recent_move": bool(recent_move),
        "far_move": bool(far_move),
        "super_move": bool(super_move),
        "wash_move": bool(wash_move),
        "recent_amp_pct": _safe_float(recent_amp.iloc[-1]),
        "far_amp_pct": _safe_float(far_amp.iloc[-1]),
    }


def check_trend_conditions(df: pd.DataFrame) -> dict[str, bool]:
    """Check trend conditions: 做上涨趋势, 强趋势股, 超牛股."""
    if len(df) < 30:
        return {
            "uptrend": False,
            "strong_trend": False,
            "super_bull": False,
        }

    trend_white = df["trend_white"]
    yellow = df["yellow"]
    bbi = df["bbi"]
    close = df["close"]
    open_price = df["open"]

    # 做上涨趋势
    uptrend = (
        (trend_white.iloc[-1] >= yellow.iloc[-1]) and
        (close.iloc[-1] >= yellow.iloc[-1] or
         (close.iloc[-1] > yellow.iloc[-1] * 0.975 and close.iloc[-1] > open_price.iloc[-1]))
    )

    # 强趋势股
    yellow_rising = (yellow >= yellow.shift(1) * 0.999).rolling(13, min_periods=1).sum()
    white_rising = (trend_white >= trend_white.shift(1))
    white_above_yellow = (trend_white > yellow)
    white_always_above = white_above_yellow.rolling(20, min_periods=1).sum()
    white_always_rising = white_rising.rolling(11, min_periods=1).sum()

    pattern = check_pattern_conditions(df)
    strong_trend = (
        (yellow_rising.iloc[-1] >= 13) and
        white_rising.iloc[-1] and
        (white_always_above.iloc[-1] >= 20) and
        (white_always_rising.iloc[-1] >= 11) and
        pattern["red_fat_green_thin"]
    )

    # 超牛股
    bbi_rising = (bbi >= bbi.shift(1) * 0.999).rolling(20, min_periods=1).sum()
    bbi_rising_count = (bbi >= bbi.shift(1)).rolling(25, min_periods=1).sum()
    bbi_condition = (bbi_rising.iloc[-1] >= 20) or (bbi_rising_count.iloc[-1] >= 23)

    vol = check_volatility_conditions(df)
    cross_condition = False
    # Check for CROSS(C, 黄线) in past
    for i in range(min(len(df) - 1, 100)):
        idx = len(df) - 2 - i
        if idx < 0:
            break
        if (close.iloc[idx] <= yellow.iloc[idx] and
            close.iloc[idx + 1] > yellow.iloc[idx + 1]):
            cross_condition = True
            bars_since = i
            break

    cross_bars_gt_12 = cross_condition and bars_since > 12

    super_bull = (
        bbi_condition and
        ((vol["recent_amp_pct"] or 0) >= 30 or (vol["far_amp_pct"] or 0) > 80) and
        cross_bars_gt_12
    )

    return {
        "uptrend": bool(uptrend),
        "strong_trend": bool(strong_trend),
        "super_bull": bool(super_bull),
    }


def check_pullback_conditions(df: pd.DataFrame, code: str) -> dict[str, Any]:
    """Check pullback conditions: 回踩白线, 回踩黄线, etc."""
    if len(df) < 5:
        return {
            "pullback_white": False,
            "white_support": False,
            "strong_pullback_hold": False,
            "pullback_yellow": False,
            "dist_white": None,
            "dist_bbi": None,
            "dist_yellow": None,
        }

    close = df["close"].iloc[-1]
    low = df["low"].iloc[-1]
    open_price = df["open"].iloc[-1]
    trend_white = df["trend_white"].iloc[-1]
    bbi = df["bbi"].iloc[-1]
    yellow = df["yellow"].iloc[-1]

    prev_close = df["close"].iloc[-2] if len(df) >= 2 else close
    daily_change = abs(close - prev_close) / prev_close * 100 if prev_close > 0 else 0

    # Distances
    dist_white = abs(close - trend_white) / (close + 1e-9) * 100
    l_dist_white = abs(low - trend_white) / (trend_white + 1e-9) * 100
    dist_bbi = abs(close - bbi) / (close + 1e-9) * 100
    l_dist_bbi = abs(low - bbi) / (bbi + 1e-9) * 100
    dist_yellow = abs(close - yellow) / (yellow + 1e-9) * 100

    # 回踩白线
    pullback_white = (
        (close >= trend_white and dist_white <= 2) or
        (close < trend_white and dist_white < 0.8) or
        (close >= bbi and dist_bbi < 2.5 and l_dist_bbi < 1 and
         dist_white <= 3 and daily_change < 1 and close > prev_close)
    )

    white_support = close >= trend_white and dist_white < 1.5

    strong_pullback_hold = (
        (l_dist_white < 1 or l_dist_bbi < 0.5) and
        (close > trend_white) and
        (dist_white <= 3.5)
    )

    # 回踩黄线
    pullback_yellow = (
        (close >= yellow and (dist_yellow <= 1.5 or (dist_yellow <= 2 and daily_change < 1))) or
        (close < yellow and dist_yellow <= 0.8)
    )

    return {
        "pullback_white": bool(pullback_white),
        "white_support": bool(white_support),
        "strong_pullback_hold": bool(strong_pullback_hold),
        "pullback_yellow": bool(pullback_yellow),
        "dist_white": _safe_float(dist_white),
        "dist_bbi": _safe_float(dist_bbi),
        "dist_yellow": _safe_float(dist_yellow),
    }


def check_b1_signals(df: pd.DataFrame, code: str, params: RuleParams) -> dict[str, Any]:
    """Check all 7 types of B1 buy signals."""
    if len(df) < 30:
        return {
            "signal_type": None,
            "b1_passed": False,
            "j": None,
            "rsi": None,
            "trend_white": None,
            "yellow": None,
            "daily_amp": None,
            "daily_change": None,
            "doji_up": None,
        }

    result = {
        "signal_type": None,
        "b1_passed": False,
        "j": _safe_float(df["J"].iloc[-1]),
        "rsi": _safe_float(df["RSI"].iloc[-1]),
        "trend_white": _safe_float(df["trend_white"].iloc[-1]),
        "yellow": _safe_float(df["yellow"].iloc[-1]),
        "bbi": _safe_float(df["bbi"].iloc[-1]),
        "short_term": _safe_float(df["short_term"].iloc[-1]),
        "long_term": _safe_float(df["long_term"].iloc[-1]),
    }

    # Basic calculations
    close = df["close"].iloc[-1]
    low = df["low"].iloc[-1]
    high = df["high"].iloc[-1]
    open_price = df["open"].iloc[-1]
    prev_close = df["close"].iloc[-2] if len(df) >= 2 else close

    daily_amp = (high - low) / (low + 1e-9) * 100
    daily_change = abs(close - prev_close) / (prev_close + 1e-9) * 100
    doji_up = (close > prev_close) and (abs(close - open_price) / (open_price + 1e-9) * 100 < 1.8)

    result["daily_amp"] = _safe_float(daily_amp)
    result["daily_change"] = _safe_float(daily_change)
    result["doji_up"] = bool(doji_up)

    # Determine 振幅区间
    is_growth_stock = (
        code.startswith(("68", "30", "4", "8", "9")) or
        (df["close"].pct_change().rolling(200, min_periods=1).max().iloc[-1] > 0.15)
    )
    amp_range = 8 if is_growth_stock else 5
    relax_coef = 0.9 if is_growth_stock else 1.0
    daily_change_adj = daily_change * relax_coef

    result["is_growth_stock"] = is_growth_stock
    result["amp_range"] = amp_range

    # Get all conditions
    vol_cond = check_volume_conditions(df, params.max_vol_lookback)
    vol_cond2 = check_volatility_conditions(df, params.n_volatility, params.m_volatility)
    trend_cond = check_trend_conditions(df)
    pullback_cond = check_pullback_conditions(df, code)
    pattern_cond = check_pattern_conditions(df)

    # Check if any movement condition is met
    any_move = vol_cond2["recent_move"] or vol_cond2["far_move"] or vol_cond2["wash_move"]

    # Get values for conditions
    j = df["J"].iloc[-1]
    rsi = df["RSI"].iloc[-1]
    rsi_prev = df["RSI"].iloc[-2] if len(df) >= 2 else rsi
    j_prev = df["J"].iloc[-2] if len(df) >= 2 else j

    not_big_green_ok = vol_cond["not_big_green"] or vol_cond["big_green_far"]

    # Signal 1: 超卖缩量拐头B
    signal1 = (
        trend_cond["uptrend"] and
        ((rsi - 15) >= rsi_prev) and
        (rsi_prev < 20 or j_prev < 14) and
        daily_amp < (amp_range + 0.5) and
        (daily_change_adj < 2.3 or doji_up) and
        not_big_green_ok and
        any_move and
        close >= df["yellow"].iloc[-1]
    )

    # Signal 2: 超卖缩量B
    j_llv = df["J"].rolling(20, min_periods=1).min().iloc[-1]
    signal2 = (
        trend_cond["uptrend"] and
        (j < 14 or rsi < 23) and
        ((rsi + j < 55) or (j == j_llv)) and
        daily_amp < amp_range and
        (daily_change_adj < 2.5 or doji_up) and
        not_big_green_ok and
        (vol_cond["volume_shrink"] or (vol_cond["moderate_shrink"] and daily_change_adj < 1)) and
        any_move
    )

    # Signal 3: 原始B1
    rsi_j_llv = ((df["RSI"] + df["J"]).rolling(15, min_periods=1).min() * 1.5).iloc[-1]
    small_body = (abs(close - open_price) / (open_price + 1e-9) * 100 < 1.5)
    signal3 = (
        (df["trend_white"].iloc[-1] > df["yellow"].iloc[-1]) and
        (close >= df["yellow"].iloc[-1] * 0.99) and
        (df["yellow"].iloc[-1] >= df["yellow"].iloc[-2]) and
        (j < 13 or rsi < 21) and
        ((rsi + j) < rsi_j_llv) and
        vol_cond["moderate_shrink"] and
        not_big_green_ok and
        (small_body or vol_cond["extreme_shrink"] or
         (vol_cond["moderate_shrink"] and (pullback_cond["dist_white"] or 0) < 1.8)) and
        any_move
    )

    # Signal 4: 超卖超缩量B
    signal4 = (
        trend_cond["uptrend"] and
        (j < 14 or rsi < 23) and
        (rsi + j < 60) and
        (vol_cond2["far_amp_pct"] or 0) >= 45 and
        (daily_amp < amp_range or
         (vol_cond2["super_move"] and daily_amp < amp_range + 3.2 and
          close > open_price and close > df["trend_white"].iloc[-1])) and
        ((close < open_price and df["volume"].iloc[-1] < df["volume"].iloc[-2] and
          close >= df["yellow"].iloc[-1]) or (close >= open_price)) and
        (daily_change_adj < 2 or doji_up) and
        not_big_green_ok and
        vol_cond["extreme_shrink"] and
        any_move
    )

    # Signal 5: 回踩白线B
    signal5 = (
        trend_cond["strong_trend"] and
        (j < 30 or rsi < 40 or vol_cond2["wash_move"]) and
        (rsi + j < 70) and
        (daily_amp < amp_range + 0.5 or pullback_cond["dist_white"] < 1 or pullback_cond["dist_bbi"] < 1) and
        pullback_cond["pullback_white"] and
        (daily_change_adj < 2 or (daily_change_adj < 5 and pullback_cond["white_support"])) and
        not_big_green_ok and
        vol_cond["pullback_shrink"] and
        any_move and
        (low <= prev_close)
    )

    # Signal 6: 回踩超级B
    rsi_j_llv_25 = (df["RSI"] + df["J"]).rolling(25, min_periods=1).min().iloc[-1]
    signal6 = (
        trend_cond["super_bull"] and
        (j < 35 or rsi < 45 or vol_cond2["wash_move"]) and
        (rsi + j < 80) and
        abs((rsi + j) - rsi_j_llv_25) < 0.01 and
        daily_amp < amp_range + 1 and
        (daily_change_adj < 2.5 or pullback_cond["dist_white"] < 2) and
        pullback_cond["strong_pullback_hold"] and
        not_big_green_ok and
        any_move and
        vol_cond["moderate_shrink"]
    )

    # Signal 7: 回踩黄线B
    rsi_llv = df["RSI"].rolling(14, min_periods=1).min().iloc[-1]
    ma60 = df["close"].rolling(60, min_periods=20).mean().iloc[-1]
    ma60_prev = df["close"].rolling(60, min_periods=20).mean().iloc[-2]
    signal7 = (
        (df["trend_white"].iloc[-1] >= df["yellow"].iloc[-1]) and
        (close >= df["yellow"].iloc[-1] * 0.975) and
        (j < 13 or rsi < 18) and
        pullback_cond["pullback_yellow"] and
        not_big_green_ok and
        (vol_cond["volume_shrink"] or
         (vol_cond["moderate_shrink"] and (j == j_llv or abs(rsi - rsi_llv) < 0.01))) and
        (df["yellow"].iloc[-1] >= df["yellow"].iloc[-2] * 0.997) and
        (ma60 >= ma60_prev * 0.99 if pd.notna(ma60) and pd.notna(ma60_prev) else True) and
        (vol_cond2["recent_amp_pct"] or 0) >= 11.9 and
        (vol_cond2["far_amp_pct"] or 0) >= 19.5
    )

    signals = {
        1: signal1,
        2: signal2,
        3: signal3,
        4: signal4,
        5: signal5,
        6: signal6,
        7: signal7,
    }

    signal_names = {
        1: "超卖缩量拐头B",
        2: "超卖缩量B",
        3: "原始B1",
        4: "超卖超缩量B",
        5: "回踩白线B",
        6: "回踩超级B",
        7: "回踩黄线B",
    }

    for sig_id, sig_value in signals.items():
        if sig_value:
            result["signal_type"] = signal_names[sig_id]
            result["b1_passed"] = True
            break

    # Store additional condition details
    result["conditions"] = {
        "volume": vol_cond,
        "volatility": vol_cond2,
        "trend": trend_cond,
        "pullback": pullback_cond,
        "pattern": pattern_cond,
    }
    result["signals"] = {signal_names[i]: bool(v) for i, v in signals.items()}

    return result


def analyze_raw_file(path: Path, pick_date: pd.Timestamp, params: RuleParams) -> dict[str, Any] | None:
    """Analyze a single stock file."""
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

    # Calculate turnover
    df["prev_close"] = df["close"].shift(1)
    df["signed_turnover"] = (df["open"] + df["close"]) / 2.0 * df["volume"]
    df["turnover_n"] = df["signed_turnover"].rolling(params.n_turnover_days, min_periods=1).sum()

    # Compute all indicators
    df = compute_indicators(df, params)

    # Check B1 signals
    b1_result = check_b1_signals(df, code, params)

    result = {
        "code": code,
        "date": pick_date.strftime("%Y-%m-%d"),
        "listed_bars": listed_bars,
        "close": float(df["close"].iloc[-1]),
        "turnover_n": float(df["turnover_n"].iloc[-1]),
        **b1_result,
    }
    return result


def build_candidates(
    rows: list[dict[str, Any]],
    names: dict[str, str],
    params: RuleParams,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build final candidates list."""
    eligible_rows = [row for row in rows if row.get("turnover_n") is not None]

    # Sort by turnover and get top M
    if params.top_m > 0 and params.top_m < len(eligible_rows):
        pool = sorted(eligible_rows, key=lambda row: -float(row["turnover_n"]))[:params.top_m]
    else:
        pool = sorted(eligible_rows, key=lambda row: (-float(row["turnover_n"]), str(row["code"])))

    rank_by_code = {str(row["code"]): rank for rank, row in enumerate(pool, start=1)}

    counters = {
        "raw_rows": len(rows),
        "pool_size": len(pool),
        "basic_failed": 0,
        "b1_failed": 0,
        "selected": 0,
    }
    candidates: list[dict[str, Any]] = []

    for row in pool:
        code = str(row["code"]).zfill(6)
        name = names.get(code, "")

        # Basic filter
        if row.get("listed_bars", 0) < params.min_listed_bars or is_blocked_name(name):
            counters["basic_failed"] += 1
            continue

        # B1 signal check
        if not row.get("b1_passed", False):
            counters["b1_failed"] += 1
            continue

        # Build candidate item
        conditions = row.get("conditions", {})
        signals = row.get("signals", {})
        # Convert signals dict values to Python bool
        signals_safe = {k: _safe_bool(v) for k, v in signals.items()}

        item = {
            "code": code,
            "name": name,
            "date": row["date"],
            "strategy": "new_b1",
            "close": _round(row.get("close"), 4),
            "turnover_n": _round(row.get("turnover_n"), 4),
            "score": None,
            "grade": "PASS",
            "active_pool_rank": rank_by_code.get(code),
            "signal_type": row.get("signal_type"),
            "extra": {
                "listed_bars": row.get("listed_bars"),
                "j": _round(row.get("j"), 6),
                "rsi": _round(row.get("rsi"), 6),
                "trend_white": _round(row.get("trend_white"), 6),
                "yellow": _round(row.get("yellow"), 6),
                "bbi": _round(row.get("bbi"), 6),
                "short_term": _round(row.get("short_term"), 6),
                "long_term": _round(row.get("long_term"), 6),
                "daily_amp": _round(row.get("daily_amp"), 4),
                "daily_change": _round(row.get("daily_change"), 4),
                "doji_up": _safe_bool(row.get("doji_up")),
                "is_growth_stock": _safe_bool(row.get("is_growth_stock")),
                "signals": signals_safe,
            },
        }
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            int(item["active_pool_rank"]) if item.get("active_pool_rank") is not None else 10**9,
            str(item["code"]),
        )
    )

    counters["selected"] = len(candidates)
    if params.limit > 0:
        candidates = candidates[:params.limit]
        counters["selected"] = len(candidates)

    return candidates, counters


def write_outputs(payload: dict[str, Any], output_dir: Path, pick_date: str) -> dict[str, str]:
    """Write output files."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"new_b1_{pick_date}.json"
    latest_path = output_dir / "new_b1_latest.json"
    csv_path = output_dir / f"new_b1_{pick_date}.csv"

    # Ensure all values are JSON serializable
    payload = _make_json_serializable(payload)
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
                "signal_type": item.get("signal_type"),
                "j": extra.get("j"),
                "rsi": extra.get("rsi"),
                "trend_white": extra.get("trend_white"),
                "yellow": extra.get("yellow"),
                "bbi": extra.get("bbi"),
                "short_term": extra.get("short_term"),
                "long_term": extra.get("long_term"),
                "daily_amp": extra.get("daily_amp"),
                "daily_change": extra.get("daily_change"),
                "doji_up": extra.get("doji_up"),
            }
        )
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    return {"json": str(json_path), "latest": str(latest_path), "csv": str(csv_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate newB1 candidates using 7-type B1 buy signals."
    )
    parser.add_argument(
        "--date",
        help="Pick date, e.g. 2026-05-08. Defaults to data/.market_cache.json latest date."
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stocklist", type=Path, default=DEFAULT_STOCKLIST)
    parser.add_argument("--top-m", type=int, default=RuleParams.top_m)
    parser.add_argument(
        "--limit",
        type=int,
        default=RuleParams.limit,
        help="Maximum output count. 0 means output all qualified candidates.",
    )
    parser.add_argument(
        "--workers", type=int, default=max(4, min(16, (os.cpu_count() or 8)))
    )
    parser.add_argument(
        "--skip-market-gate",
        action="store_true",
        help="Do not apply additional filtering (for compatibility with CLI)."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if int(args.limit) < 0:
        raise ValueError("--limit must be >= 0; use 0 to output all qualified candidates")

    params = RuleParams(
        top_m=args.top_m,
        limit=args.limit,
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
    candidates, counters = build_candidates(rows, names, params)
    elapsed = round(time.perf_counter() - started, 3)
    pick_date_str = pick_date.strftime("%Y-%m-%d")

    payload = {
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "pick_date": pick_date_str,
        "strategy": "new_b1",
        "strategy_description": "超级B1选股公式 - 7 types of B1 buy signals",
        "candidates": candidates,
        "meta": {
            "elapsed_seconds": elapsed,
            "raw_dir": str(args.raw_dir),
            "source_files": len(files),
            "read_errors": errors,
            "params": asdict(params),
            "counters": counters,
            "notes": [
                "Implements 超级B1选股公式 with 7 types of B1 buy signals:",
                "1. 超卖缩量拐头B - Oversold volume contraction with RSI turn",
                "2. 超卖缩量B - Oversold volume contraction",
                "3. 原始B1 - Original B1 pattern",
                "4. 超卖超缩量B - Oversold extreme volume contraction",
                "5. 回踩白线B - Pullback to white line (strong trend)",
                "6. 回踩超级B - Pullback for super bull stocks",
                "7. 回踩黄线B - Pullback to yellow line (medium-term trend)",
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
