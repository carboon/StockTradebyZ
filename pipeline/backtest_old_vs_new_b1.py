"""
backtest_old_vs_new_b1.py
~~~~~~~~~~~~~~~~~~~~~~~~~~

Comparison backtest between oldB1 (B1Selector) and newB1 (7-type B1 signals).

Usage:
    python -m pipeline.backtest_old_vs_new_b1
    python -m pipeline.backtest_old_vs_new_b1 --start-date 2024-01-01 --end-date 2025-12-31
    python -m pipeline.backtest_old_vs_new_b1 --trade-days 120

Outputs:
    data/backtest/old_vs_new_b1_events_<dates>.csv
    data/backtest/old_vs_new_b1_summary_<dates>.json
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "newB1"))

from Selector import B1Selector  # noqa: E402
from pipeline_core import TopTurnoverPoolBuilder  # noqa: E402
from select_stock import load_config as load_preselect_config, load_raw_data  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("backtest_old_vs_new_b1")


# ============================================================================
# newB1 Core Logic (adapted from newB1/generate_new_b1.py)
# ============================================================================

@dataclass(frozen=True)
class NewB1Params:
    """Parameters for new B1 selection rules."""
    history_bars: int = 360
    trend_ema_span: int = 10
    yellow_ma1: int = 14
    yellow_ma2: int = 28
    yellow_ma3: int = 57
    yellow_ma4: int = 114
    short_term_n: int = 3
    long_term_n: int = 21
    bbi_ma1: int = 3
    bbi_ma2: int = 6
    bbi_ma3: int = 12
    bbi_ma4: int = 24
    kdj_n: int = 9
    rsi_n: int = 3
    n_volatility: int = 20
    m_volatility: int = 50
    max_vol_lookback: int = 40
    # Weekly MA parameters for classic B1
    wma_short: int = 10
    wma_mid: int = 20
    wma_long: int = 30


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


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

    rsi_ma = temp1.ewm(alpha=1.0 / n, adjust=False).mean()
    abs_ma = temp2.ewm(alpha=1.0 / n, adjust=False).mean()

    rsi = rsi_ma / (abs_ma + 1e-9) * 100.0
    return rsi


def compute_newb1_indicators(df: pd.DataFrame, params: NewB1Params) -> pd.DataFrame:
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

    # 周线多头排列 (for classic B1)
    wma_short = df["close"].rolling(params.wma_short * 5, min_periods=1).mean()
    wma_mid = df["close"].rolling(params.wma_mid * 5, min_periods=1).mean()
    wma_long = df["close"].rolling(params.wma_long * 5, min_periods=1).mean()
    wma_bull = (wma_short > wma_mid) & (wma_mid > wma_long)

    df["trend_white"] = trend_white
    df["yellow"] = yellow
    df["short_term"] = short_term
    df["long_term"] = long_term
    df["bbi"] = bbi
    df["K"] = kdj["K"]
    df["D"] = kdj["D"]
    df["J"] = kdj["J"]
    df["RSI"] = rsi
    df["wma_bull"] = wma_bull

    return df


def check_volume_conditions(df: pd.DataFrame, max_lookback: int = 40) -> dict[str, bool]:
    """Check volume conditions."""
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

    hhv_vol_20 = vol.rolling(20, min_periods=1).max()
    hhv_vol_30 = vol.rolling(30, min_periods=1).max()
    hhv_vol_50 = vol.rolling(50, min_periods=1).max()

    vol_40 = vol.tail(40)
    if len(vol_40) > 0:
        vday_idx = vol_40.idxmax() if hasattr(vol_40, 'idxmax') else len(df) - 40 + vol_40.to_numpy().argmax()
    else:
        vday_idx = df.index[-1]

    if vday_idx in df.index:
        vday_loc = df.index.get_loc(vday_idx)
        vday_close = close.iloc[vday_loc]
        vday_close_prev = close.iloc[vday_loc - 1] if vday_loc > 0 else vday_close
        vday_open = open_price.iloc[vday_loc]

        not_big_green = (vday_close >= vday_close_prev) or (vday_close >= vday_open)
        big_green_far = not_big_green and (len(df) - vday_loc >= 15)
    else:
        not_big_green = True
        big_green_far = False

    vol_today = vol.iloc[-1]

    volume_shrink = (vol_today < hhv_vol_20.iloc[-1] * 0.416) or (vol_today < hhv_vol_50.iloc[-1] / 3)
    pullback_shrink = (vol_today < hhv_vol_20.iloc[-1] * 0.45) or (vol_today < hhv_vol_50.iloc[-1] / 3)
    moderate_shrink = (vol_today < hhv_vol_20.iloc[-1] * 0.618) or (vol_today < hhv_vol_50.iloc[-1] / 3)
    extreme_shrink = (vol_today < hhv_vol_30.iloc[-1] / 4) or (vol_today < hhv_vol_50.iloc[-1] / 6)

    return {
        "not_big_green": bool(not_big_green),
        "big_green_far": bool(big_green_far),
        "volume_shrink": bool(volume_shrink),
        "pullback_shrink": bool(pullback_shrink),
        "moderate_shrink": bool(moderate_shrink),
        "extreme_shrink": bool(extreme_shrink),
    }


def check_volatility_conditions(df: pd.DataFrame, n: int = 20, m: int = 50) -> dict[str, Any]:
    """Check volatility conditions."""
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

    high_12 = df["high"].rolling(12, min_periods=1).max()
    low_14 = df["low"].rolling(14, min_periods=1).min()
    special_move = (high_12 - low_14) / (low_14 + 1e-9) * 100
    recent_move = (recent_amp.iloc[-1] >= 15) or (special_move.iloc[-1] >= 11)

    far_move = far_amp.iloc[-1] >= 30
    super_move = recent_amp.iloc[-1] >= 60

    # Simplified wash move check
    short = df["short_term"] if "short_term" in df.columns else pd.Series([0] * len(df))
    long_term = df["long_term"] if "long_term" in df.columns else pd.Series([0] * len(df))
    single_needle = (short.iloc[-1] <= 20 and long_term.iloc[-1] >= 75) or ((long_term.iloc[-1] - short.iloc[-1]) >= 70)
    wash_move = bool(single_needle)

    return {
        "recent_move": bool(recent_move),
        "far_move": bool(far_move),
        "super_move": bool(super_move),
        "wash_move": bool(wash_move),
        "recent_amp_pct": _safe_float(recent_amp.iloc[-1]),
        "far_amp_pct": _safe_float(far_amp.iloc[-1]),
    }


def check_trend_conditions(df: pd.DataFrame) -> dict[str, bool]:
    """Check trend conditions."""
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

    # 强趋势股 (simplified)
    yellow_rising = (yellow >= yellow.shift(1) * 0.999).rolling(13, min_periods=1).sum()
    white_rising = (trend_white >= trend_white.shift(1))
    white_above_yellow = (trend_white > yellow)
    white_always_above = white_above_yellow.rolling(20, min_periods=1).sum()
    white_always_rising = white_rising.rolling(11, min_periods=1).sum()

    c_ge_o = (df["close"] >= df["open"]).rolling(15, min_periods=1).sum()
    c_gt_prev = (df["close"] > df["close"].shift(1)).rolling(11, min_periods=1).sum()
    red_fat_green_thin = (c_ge_o.iloc[-1] > 7) or (c_gt_prev.iloc[-1] > 5)

    strong_trend = (
        (yellow_rising.iloc[-1] >= 13) and
        white_rising.iloc[-1] and
        (white_always_above.iloc[-1] >= 20) and
        (white_always_rising.iloc[-1] >= 11) and
        red_fat_green_thin
    )

    # 超牛股 (simplified)
    bbi_rising = (bbi >= bbi.shift(1) * 0.999).rolling(20, min_periods=1).sum()
    bbi_rising_count = (bbi >= bbi.shift(1)).rolling(25, min_periods=1).sum()
    bbi_condition = (bbi_rising.iloc[-1] >= 20) or (bbi_rising_count.iloc[-1] >= 23)

    vol = check_volatility_conditions(df)
    super_bull = (
        bbi_condition and
        ((vol["recent_amp_pct"] or 0) >= 30 or (vol["far_amp_pct"] or 0) > 80)
    )

    return {
        "uptrend": bool(uptrend),
        "strong_trend": bool(strong_trend),
        "super_bull": bool(super_bull),
    }


def check_pullback_conditions(df: pd.DataFrame, code: str) -> dict[str, Any]:
    """Check pullback conditions."""
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
    trend_white = df["trend_white"].iloc[-1]
    bbi = df["bbi"].iloc[-1]
    yellow = df["yellow"].iloc[-1]

    prev_close = df["close"].iloc[-2] if len(df) >= 2 else close
    daily_change = abs(close - prev_close) / prev_close * 100 if prev_close > 0 else 0

    dist_white = abs(close - trend_white) / (close + 1e-9) * 100
    l_dist_white = abs(low - trend_white) / (trend_white + 1e-9) * 100
    dist_bbi = abs(close - bbi) / (close + 1e-9) * 100
    l_dist_bbi = abs(low - bbi) / (bbi + 1e-9) * 100
    dist_yellow = abs(close - yellow) / (yellow + 1e-9) * 100

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


def check_newb1_signals(df: pd.DataFrame, code: str, params: NewB1Params) -> dict[str, Any]:
    """Check all 7 types of new B1 buy signals."""
    if len(df) < 30:
        return {
            "signal_type": None,
            "b1_passed": False,
            "j": None,
            "rsi": None,
            "trend_white": None,
            "yellow": None,
        }

    result = {
        "signal_type": None,
        "b1_passed": False,
        "j": _safe_float(df["J"].iloc[-1]),
        "rsi": _safe_float(df["RSI"].iloc[-1]),
        "trend_white": _safe_float(df["trend_white"].iloc[-1]),
        "yellow": _safe_float(df["yellow"].iloc[-1]),
    }

    close = df["close"].iloc[-1]
    low = df["low"].iloc[-1]
    high = df["high"].iloc[-1]
    open_price = df["open"].iloc[-1]
    prev_close = df["close"].iloc[-2] if len(df) >= 2 else close

    daily_amp = (high - low) / (low + 1e-9) * 100
    daily_change = abs(close - prev_close) / (prev_close + 1e-9) * 100
    doji_up = (close > prev_close) and (abs(close - open_price) / (open_price + 1e-9) * 100 < 1.8)

    is_growth_stock = code.startswith(("68", "30", "4", "8", "9"))
    amp_range = 8 if is_growth_stock else 5
    relax_coef = 0.9 if is_growth_stock else 1.0
    daily_change_adj = daily_change * relax_coef

    vol_cond = check_volume_conditions(df, params.max_vol_lookback)
    vol_cond2 = check_volatility_conditions(df, params.n_volatility, params.m_volatility)
    trend_cond = check_trend_conditions(df)
    pullback_cond = check_pullback_conditions(df, code)

    any_move = vol_cond2["recent_move"] or vol_cond2["far_move"] or vol_cond2["wash_move"]

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

    # Signal 8: 经典B1 (oldB1 - 周线多头 + KDJ分位 + ZX条件)
    j_q_threshold = 0.10  # 10th percentile
    j_q = df["J"].rolling(100, min_periods=20).quantile(j_q_threshold).iloc[-1]
    j_low = j < 15 or j <= j_q

    # ZX condition: zxdq (trend_white) > zxdkx (yellow), close > zxdkx
    zx_condition = (df["trend_white"].iloc[-1] > df["yellow"].iloc[-1]) and (close >= df["yellow"].iloc[-1])

    # 周线多头排列
    wma_bull = df["wma_bull"].iloc[-1] if "wma_bull" in df.columns else False

    # 量价条件：适度缩量即可
    volume_ok = vol_cond["moderate_shrink"] or vol_cond["volume_shrink"]

    signal8 = (
        j_low and                    # KDJ低位
        zx_condition and             # ZX条件
        wma_bull and                 # 周线多头排列
        volume_ok and                # 缩量
        not_big_green_ok and         # 不是大绿棒
        any_move                     # 有异动
    )

    signals = {
        1: signal1,
        2: signal2,
        3: signal3,
        4: signal4,
        5: signal5,
        6: signal6,
        7: signal7,
        8: signal8,
    }

    signal_names = {
        1: "超卖缩量拐头B",
        2: "超卖缩量B",
        3: "原始B1",
        4: "超卖超缩量B",
        5: "回踩白线B",
        6: "回踩超级B",
        7: "回踩黄线B",
        8: "经典B1",
    }

    for sig_id, sig_value in signals.items():
        if sig_value:
            result["signal_type"] = signal_names[sig_id]
            result["b1_passed"] = True
            break

    result["signals"] = {signal_names[i]: bool(v) for i, v in signals.items()}

    return result


# ============================================================================
# Data Preparation
# ============================================================================

def _calc_backtest_warmup(cfg: dict[str, Any]) -> int:
    warmup = 120
    global_cfg = cfg.get("global", {})
    min_bars_buffer = int(global_cfg.get("min_bars_buffer", 10))
    b1_cfg = cfg.get("b1", {})
    if b1_cfg.get("enabled", True):
        warmup = max(warmup, int(b1_cfg.get("zx_m4", 114)) + min_bars_buffer)
    warmup = max(warmup, 360)  # newB1 needs 360 bars
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


# ============================================================================
# Statistics
# ============================================================================

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


def _summarize_events(events: pd.DataFrame, horizons: list[int]) -> dict[str, Any]:
    if events.empty:
        return {
            "total_events": 0,
            "by_strategy": {},
            "overlap": {},
            "horizons": {},
        }

    summary = {
        "total_events": int(len(events)),
        "by_strategy": {},
        "overlap": {},
        "horizons": {},
    }

    # By strategy
    for strategy in ("old_b1", "new_b1"):
        strategy_events = events[events["strategy"] == strategy]
        summary["by_strategy"][strategy] = {
            "count": int(len(strategy_events)),
            "unique_dates": int(strategy_events["pick_date"].nunique()),
        }

    # Overlap
    old_picks = set(events[events["strategy"] == "old_b1"].apply(lambda x: f"{x['pick_date']}_{x['code']}", axis=1))
    new_picks = set(events[events["strategy"] == "new_b1"].apply(lambda x: f"{x['pick_date']}_{x['code']}", axis=1))
    overlap = old_picks & new_picks
    summary["overlap"] = {
        "old_only": len(old_picks - new_picks),
        "new_only": len(new_picks - old_picks),
        "both": len(overlap),
        "overlap_rate": round(len(overlap) / len(old_picks | new_picks), 6) if (old_picks | new_picks) else 0,
    }

    # By signal type for newB1
    new_events = events[events["strategy"] == "new_b1"]
    if not new_events.empty and "signal_type" in new_events.columns:
        signal_counts = new_events["signal_type"].value_counts()
        summary["by_strategy"]["new_b1"]["signals"] = {
            str(k): int(v) for k, v in signal_counts.items()
        }

    # By horizon
    for horizon in horizons:
        ret_col = f"ret_{horizon}d"
        by_strategy = {}
        for strategy in ("old_b1", "new_b1"):
            strategy_events = events[events["strategy"] == strategy]
            by_strategy[strategy] = _stats(strategy_events[ret_col])

        # Also calculate for overlapping picks
        overlap_events = events[
            events.apply(lambda x: f"{x['pick_date']}_{x['code']}", axis=1).isin(overlap)
        ]
        by_strategy["overlap"] = _stats(overlap_events[ret_col])

        summary["horizons"][f"{horizon}d"] = by_strategy

    return summary


# ============================================================================
# Trade Simulation with Complex Exit Strategy
# ============================================================================

def simulate_trade(
    df: pd.DataFrame,
    pick_date: pd.Timestamp,
    *,
    stop_loss_pct: float = 0.05,
    hold_days_threshold: int = 3,
    profit_target_pct: float = 0.03,
    trailing_drop_pct: float = 0.05,
    max_hold_days: int = 60,
) -> dict[str, Any] | None:
    """
    模拟交易退出逻辑：
    1. 止损：累计亏损达到 stop_loss_pct (5%)，立即退出
    2. 持有 hold_days_threshold (3) 天后：
       - 涨幅 < profit_target_pct (3%)，平仓退出
       - 涨幅 >= profit_target_pct，继续持有
    3. 继续持有期间，单日跌幅 >= trailing_drop_pct (5%)，以收盘价退出
    4. 最大持有 max_hold_days 天
    """
    # 找到 pick_date 在 df 中的位置
    if pick_date not in df.index:
        return None

    pick_loc = df.index.get_loc(pick_date)
    entry_idx = pick_loc + 1  # 次日入场

    if entry_idx >= len(df):
        return None

    entry_price = df.iloc[entry_idx]["open"]
    if pd.isna(entry_price) or entry_price <= 0:
        return None

    stop_loss_price = entry_price * (1 - stop_loss_pct)
    target_price = entry_price * (1 + profit_target_pct)
    highest_close_since_target = entry_price  # 达到目标价后的最高收盘价

    for i in range(entry_idx, min(len(df), entry_idx + max_hold_days)):
        row = df.iloc[i]
        current_date = df.index[i]
        hold_days = i - entry_idx + 1

        open_price = row["open"]
        high = row["high"]
        low = row["low"]
        close = row["close"]

        # 检查止损（开盘价或最低价触及止损）
        if low <= stop_loss_price:
            # 触及止损，以止损价或开盘价退出
            exit_price = max(stop_loss_price, min(open_price, close))
            if exit_price > close:  # 止损价高于收盘价，以开盘价退出
                exit_price = open_price
            return {
                "entry_date": df.index[entry_idx],
                "entry_price": float(entry_price),
                "exit_date": current_date,
                "exit_price": float(exit_price),
                "hold_days": hold_days,
                "ret": (exit_price - entry_price) / entry_price,
                "exit_reason": "stop_loss",
            }

        # 计算当前收益
        current_ret = (close - entry_price) / entry_price

        # 如果还没到3天，继续持有
        if hold_days < hold_days_threshold:
            continue

        # 已持有 >= 3天
        # 检查是否已达到目标价（涨幅>=3%）
        reached_target = highest_close_since_target >= target_price

        if not reached_target:
            # 还没达到目标价，检查当前涨幅
            if current_ret < profit_target_pct:
                # 3天后涨幅仍不足3%，平仓退出
                return {
                    "entry_date": df.index[entry_idx],
                    "entry_price": float(entry_price),
                    "exit_date": current_date,
                    "exit_price": float(close),
                    "hold_days": hold_days,
                    "ret": current_ret,
                    "exit_reason": "below_target_3d",
                }
            else:
                # 达到目标价
                reached_target = True
                highest_close_since_target = close

        if reached_target:
            # 已达到目标价，更新最高收盘价
            if close > highest_close_since_target:
                highest_close_since_target = close

            # 检查单日跌幅 >= 5%（相对开盘价）
            intraday_drop = (open_price - low) / open_price if open_price > 0 else 0
            if intraday_drop >= trailing_drop_pct:
                # 单日跌幅过大，以收盘价退出
                return {
                    "entry_date": df.index[entry_idx],
                    "entry_price": float(entry_price),
                    "exit_date": current_date,
                    "exit_price": float(close),
                    "hold_days": hold_days,
                    "ret": current_ret,
                    "exit_reason": "trailing_stop",
                }

            # 检查是否跌破最高价一定比例（可选）
            drop_from_high = (highest_close_since_target - close) / highest_close_since_target
            if drop_from_high >= trailing_drop_pct:
                return {
                    "entry_date": df.index[entry_idx],
                    "entry_price": float(entry_price),
                    "exit_date": current_date,
                    "exit_price": float(close),
                    "hold_days": hold_days,
                    "ret": current_ret,
                    "exit_reason": "trailing_stop_high",
                }

    # 达到最大持有天数
    final_idx = min(len(df) - 1, entry_idx + max_hold_days - 1)
    final_close = df.iloc[final_idx]["close"]
    final_ret = (final_close - entry_price) / entry_price
    final_date = df.index[final_idx]
    final_hold_days = final_idx - entry_idx + 1

    return {
        "entry_date": df.index[entry_idx],
        "entry_price": float(entry_price),
        "exit_date": final_date,
        "exit_price": float(final_close),
        "hold_days": final_hold_days,
        "ret": final_ret,
        "exit_reason": "max_hold_days",
    }


def _summarize_trade_events(events: pd.DataFrame) -> dict[str, Any]:
    """汇总交易事件统计。"""
    if events.empty:
        return {
            "total_trades": 0,
            "completed_trades": 0,
            "avg_return": None,
            "median_return": None,
            "win_rate": None,
            "avg_hold_days": None,
            "exit_reasons": {},
        }

    completed = events[events["exit_reason"].notna()].copy()
    if completed.empty:
        return {
            "total_trades": int(len(events)),
            "completed_trades": 0,
            "avg_return": None,
            "median_return": None,
            "win_rate": None,
            "avg_hold_days": None,
            "exit_reasons": {},
        }

    # 收益统计
    returns = completed["ret"]
    win_rate = (returns > 0).mean()

    # 退出原因统计
    exit_counts = completed["exit_reason"].value_counts().to_dict()

    # 按退出原因分组统计
    by_exit_reason = {}
    for reason in completed["exit_reason"].unique():
        reason_trades = completed[completed["exit_reason"] == reason]
        by_exit_reason[reason] = {
            "count": int(len(reason_trades)),
            "avg_ret": round(float(reason_trades["ret"].mean()), 6),
            "win_rate": round(float((reason_trades["ret"] > 0).mean()), 6),
            "avg_hold_days": round(float(reason_trades["hold_days"].mean()), 2),
        }

    return {
        "total_trades": int(len(events)),
        "completed_trades": int(len(completed)),
        "avg_return": round(float(returns.mean()), 6),
        "median_return": round(float(returns.median()), 6),
        "win_rate": round(float(win_rate), 6),
        "avg_hold_days": round(float(completed["hold_days"].mean()), 2),
        "exit_reasons": exit_counts,
        "by_exit_reason": by_exit_reason,
    }


# ============================================================================
# Main Backtest Logic
# ============================================================================

def run_backtest(
    *,
    preselect_config_path: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trade_days: int | None = None,
    horizons: list[int] = [1, 3, 5, 10],
    use_trade_exit: bool = False,
    stop_loss_pct: float = 0.05,
    hold_days_threshold: int = 3,
    profit_target_pct: float = 0.03,
    trailing_drop_pct: float = 0.05,
    max_hold_days: int = 60,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    preselect_cfg = load_preselect_config(preselect_config_path)
    global_cfg = preselect_cfg.get("global", {})
    raw_dir = ROOT / global_cfg.get("data_dir", "./data/raw")
    warmup_bars = _calc_backtest_warmup(preselect_cfg)

    # Determine date range
    if trade_days:
        # Get last N trade days
        ref_path = raw_dir / "000001.csv"
        if not ref_path.exists():
            matches = sorted(raw_dir.glob("*.csv"))
            if matches:
                ref_path = matches[0]
        if ref_path.exists():
            dates = pd.read_csv(ref_path, usecols=["date"])["date"]
            dates = pd.to_datetime(dates, errors="coerce").dropna().sort_values().drop_duplicates()
            if not dates.empty:
                target_dates = list(pd.DatetimeIndex(dates).to_pydatetime())[-trade_days:]
                start_date = target_dates[0].strftime("%Y-%m-%d")
                end_date = target_dates[-1].strftime("%Y-%m-%d")

    raw_data = load_raw_data(
        str(raw_dir),
        end_date=end_date,
        start_date=start_date,
        warmup_bars=warmup_bars,
    )

    n_turnover_days = int(global_cfg.get("n_turnover_days", 43))
    top_m = int(global_cfg.get("top_m", 2000))

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
    newb1_params = NewB1Params()

    start_ts = pd.to_datetime(start_date) if start_date else None
    end_ts = pd.to_datetime(end_date) if end_date else None
    events: list[dict[str, Any]] = []

    if use_trade_exit:
        logger.info("使用复杂退出策略: 止损-%.0f%%, %d天后涨幅<%.0f%%退出, 达标后追踪止损-%.0f%%",
                    stop_loss_pct * 100, hold_days_threshold, profit_target_pct * 100, trailing_drop_pct * 100)

    for code, base_df in tqdm(base_frames.items(), desc="滚动回测", ncols=90):
        # oldB1 picks
        b1_frame = b1_selector.prepare_df(base_df)
        old_picked: set[pd.Timestamp] = set()
        for dt in b1_selector.vec_picks_from_prepared(b1_frame, start=start_ts, end=end_ts):
            codes_today = pool_sets.get(dt)
            if codes_today and code in codes_today:
                old_picked.add(dt)

        # newB1 picks
        newb1_frame = compute_newb1_indicators(base_df, newb1_params)
        new_picked: dict[pd.Timestamp, str] = {}
        for dt in newb1_frame.index:
            if start_ts and dt < start_ts:
                continue
            if end_ts and dt > end_ts:
                continue
            codes_today = pool_sets.get(dt)
            if not codes_today or code not in codes_today:
                continue

            # Check if we have enough data before this date
            loc = newb1_frame.index.get_loc(dt)
            if loc < 30:
                continue

            slice_df = newb1_frame.iloc[:loc + 1].copy()
            result = check_newb1_signals(slice_df, code, newb1_params)
            if result.get("b1_passed"):
                new_picked[dt] = result.get("signal_type", "Unknown")

        # Combine picks
        all_dates = sorted(set(old_picked) | set(new_picked.keys()))
        if not all_dates:
            continue

        for dt in all_dates:
            is_old = dt in old_picked
            is_new = dt in new_picked

            strategies = []
            if is_old:
                strategies.append("old_b1")
            if is_new:
                strategies.append("new_b1")

            for strategy in strategies:
                if use_trade_exit:
                    # 使用复杂的交易退出逻辑
                    trade_result = simulate_trade(
                        base_df,
                        dt,
                        stop_loss_pct=stop_loss_pct,
                        hold_days_threshold=hold_days_threshold,
                        profit_target_pct=profit_target_pct,
                        trailing_drop_pct=trailing_drop_pct,
                        max_hold_days=max_hold_days,
                    )

                    if trade_result is None:
                        continue

                    event: dict[str, Any] = {
                        "pick_date": dt.strftime("%Y-%m-%d"),
                        "code": code,
                        "strategy": strategy,
                        "close": round(float(base_df.at[dt, "close"]), 6) if dt in base_df.index else None,
                        "turnover_n": round(float(base_df.at[dt, "turnover_n"]), 6) if dt in base_df.index else None,
                        "signal_type": new_picked[dt] if strategy == "new_b1" else "B1",
                        "entry_date": trade_result["entry_date"].strftime("%Y-%m-%d"),
                        "entry_price": trade_result["entry_price"],
                        "exit_date": trade_result["exit_date"].strftime("%Y-%m-%d"),
                        "exit_price": trade_result["exit_price"],
                        "hold_days": trade_result["hold_days"],
                        "ret": trade_result["ret"],
                        "exit_reason": trade_result["exit_reason"],
                    }
                else:
                    # 使用固定持有期逻辑
                    entry_open = base_df["open"].shift(-1)
                    entry_date = base_df["date"].shift(-1)
                    exit_dates = {h: base_df["date"].shift(-h) for h in horizons}
                    returns = {h: base_df["close"].shift(-h) / entry_open - 1.0 for h in horizons}

                    event = {
                        "pick_date": dt.strftime("%Y-%m-%d"),
                        "code": code,
                        "strategy": strategy,
                        "close": round(float(base_df.at[dt, "close"]), 6) if dt in base_df.index else None,
                        "turnover_n": round(float(base_df.at[dt, "turnover_n"]), 6) if dt in base_df.index else None,
                        "signal_type": new_picked[dt] if strategy == "new_b1" else "B1",
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
        events_df = events_df.sort_values(["pick_date", "code", "strategy"]).reset_index(drop=True)

    # 根据是否使用交易退出逻辑，选择不同的汇总函数
    if use_trade_exit:
        summary = _summarize_trade_events_by_strategy(events_df)
    else:
        summary = _summarize_events(events_df, horizons=horizons)

    if not events_df.empty:
        summary["date_range"] = {
            "start": str(events_df["pick_date"].min()),
            "end": str(events_df["pick_date"].max()),
        }
    else:
        summary["date_range"] = {"start": start_date, "end": end_date}
    return events_df, summary


def _summarize_trade_events_by_strategy(events: pd.DataFrame) -> dict[str, Any]:
    """按策略汇总交易事件（用于复杂退出策略）。"""
    if events.empty:
        return {
            "total_events": 0,
            "by_strategy": {},
            "overlap": {},
        }

    summary = {
        "total_events": int(len(events)),
        "by_strategy": {},
        "overlap": {},
    }

    # 计算重叠
    old_picks = set(events[events["strategy"] == "old_b1"].apply(lambda x: f"{x['pick_date']}_{x['code']}", axis=1))
    new_picks = set(events[events["strategy"] == "new_b1"].apply(lambda x: f"{x['pick_date']}_{x['code']}", axis=1))
    overlap = old_picks & new_picks
    summary["overlap"] = {
        "old_only": len(old_picks - new_picks),
        "new_only": len(new_picks - old_picks),
        "both": len(overlap),
        "overlap_rate": round(len(overlap) / len(old_picks | new_picks), 6) if (old_picks | new_picks) else 0,
    }

    # 按策略汇总
    for strategy in ("old_b1", "new_b1"):
        strategy_events = events[events["strategy"] == strategy]
        strategy_summary = _summarize_trade_events(strategy_events)
        summary["by_strategy"][strategy] = strategy_summary

        # 按信号类型汇总（仅newB1）
        if strategy == "new_b1" and "signal_type" in strategy_events.columns:
            by_signal = {}
            for signal in strategy_events["signal_type"].unique():
                signal_events = strategy_events[strategy_events["signal_type"] == signal]
                by_signal[str(signal)] = {
                    "count": int(len(signal_events)),
                    **_summarize_trade_events(signal_events),
                }
            summary["by_strategy"][strategy]["by_signal"] = by_signal

    # 重叠事件汇总
    overlap_events = events[
        events.apply(lambda x: f"{x['pick_date']}_{x['code']}", axis=1).isin(overlap)
    ]
    summary["overlap"]["trade_summary"] = _summarize_trade_events(overlap_events)

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="oldB1 vs newB1 comparison backtest")
    parser.add_argument("--preselect-config", default=None, help="初选配置文件路径")
    parser.add_argument("--start-date", default=None, help="回测起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="回测结束日期 YYYY-MM-DD")
    parser.add_argument("--trade-days", type=int, default=None, help="回测最近N个交易日")
    parser.add_argument("--horizons", default="1,3,5,10", help="持有周期（天）[仅固定持有期模式]")
    parser.add_argument("--use-trade-exit", action="store_true", help="使用复杂的交易退出策略")
    parser.add_argument("--stop-loss", type=float, default=5.0, help="止损百分比（默认5%%）")
    parser.add_argument("--hold-threshold", type=int, default=3, help="持仓天数阈值（默认3天）")
    parser.add_argument("--profit-target", type=float, default=3.0, help="盈利目标百分比（默认3%%）")
    parser.add_argument("--trailing-stop", type=float, default=5.0, help="追踪止损百分比（默认5%%）")
    parser.add_argument("--max-hold", type=int, default=60, help="最大持有天数（默认60）")
    args = parser.parse_args()

    use_trade_exit = args.use_trade_exit

    if use_trade_exit:
        stop_loss_pct = args.stop_loss / 100.0
        hold_days_threshold = args.hold_threshold
        profit_target_pct = args.profit_target / 100.0
        trailing_drop_pct = args.trailing_stop / 100.0
        max_hold_days = args.max_hold
        horizons = []  # 交易退出模式不需要固定持有期
    else:
        stop_loss_pct = 0.05
        hold_days_threshold = 3
        profit_target_pct = 0.03
        trailing_drop_pct = 0.05
        max_hold_days = 60
        horizons = [int(h.strip()) for h in str(args.horizons).split(",") if h.strip()]

    events_df, summary = run_backtest(
        preselect_config_path=args.preselect_config,
        start_date=args.start_date,
        end_date=args.end_date,
        trade_days=args.trade_days,
        horizons=horizons,
        use_trade_exit=use_trade_exit,
        stop_loss_pct=stop_loss_pct,
        hold_days_threshold=hold_days_threshold,
        profit_target_pct=profit_target_pct,
        trailing_drop_pct=trailing_drop_pct,
        max_hold_days=max_hold_days,
    )

    out_dir = ROOT / "data" / "backtest"
    out_dir.mkdir(parents=True, exist_ok=True)

    date_range = summary["date_range"]
    start_label = (date_range.get("start") or "auto").replace("-", "")
    end_label = (date_range.get("end") or "auto").replace("-", "")

    suffix = "_trade_exit" if use_trade_exit else ""
    events_path = out_dir / f"old_vs_new_b1_events_{start_label}_{end_label}{suffix}.csv"
    summary_path = out_dir / f"old_vs_new_b1_summary_{start_label}_{end_label}{suffix}.json"

    events_df.to_csv(events_path, index=False, encoding="utf-8")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    logger.info("事件文件: %s", events_path)
    logger.info("汇总文件: %s", summary_path)
    logger.info("总事件数: %d", len(events_df))

    if use_trade_exit:
        logger.info("=== 交易退出策略回测结果 ===")
        for strategy in ("old_b1", "new_b1"):
            s = summary.get("by_strategy", {}).get(strategy, {})
            logger.info("%s: 交易数=%d, 平均收益=%.2f%%, 胜率=%.2f%%, 平均持仓=%.1f天",
                       strategy,
                       s.get("completed_trades", 0),
                       (s.get("avg_return", 0) * 100) if s.get("avg_return") else 0,
                       (s.get("win_rate", 0) * 100) if s.get("win_rate") else 0,
                       s.get("avg_hold_days", 0))
        logger.info("重叠事件数: %d", summary.get("overlap", {}).get("both", 0))
    else:
        logger.info("oldB1事件数: %d", summary.get("by_strategy", {}).get("old_b1", {}).get("count", 0))
        logger.info("newB1事件数: %d", summary.get("by_strategy", {}).get("new_b1", {}).get("count", 0))
        logger.info("重叠事件数: %d", summary.get("overlap", {}).get("both", 0))


if __name__ == "__main__":
    main()
