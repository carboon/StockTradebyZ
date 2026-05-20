"""
HybridB1Selector: 高质量B1组合选择器
====================================
组合以下4种信号的并集:
1. oldB1 - 原有B1Selector的输出
2. 原始B1 (newB1 Signal 3) - 白线>黄线+接近黄线+超卖
3. 回踩黄线B (newB1 Signal 7) - 中期趋势回踩黄线
4. 回踩超级B (newB1 Signal 6) - 超牛股回踩

Author: HybridB1 System
Date: 2026-05-20
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

import numpy as np
import pandas as pd

# 添加项目路径
ROOT = Path(__file__).parent.parent.parent.parent
if str(ROOT / "pipeline") not in sys.path:
    sys.path.insert(0, str(ROOT / "pipeline"))

from Selector import B1Selector


@dataclass
class HybridB1Config:
    """HybridB1选择器配置参数"""
    # oldB1 配置
    j_threshold: float = 15.0
    j_q_threshold: float = 0.10
    zx_m1: int = 14
    zx_m2: int = 28
    zx_m3: int = 57
    zx_m4: int = 114

    # newB1 配置
    trend_ema_span: int = 10
    yellow_ma1: int = 14
    yellow_ma2: int = 28
    yellow_ma3: int = 57
    yellow_ma4: int = 114
    kdj_n: int = 9
    rsi_n: int = 3
    short_term_n: int = 3
    long_term_n: int = 21
    bbi_ma1: int = 3
    bbi_ma2: int = 6
    bbi_ma3: int = 12
    bbi_ma4: int = 24
    n_volatility: int = 20
    m_volatility: int = 50
    max_vol_lookback: int = 40


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(out):
        return default
    return out


def _safe_bool(value: Any, default: bool = False) -> bool:
    try:
        return bool(value)
    except (TypeError, ValueError):
        return default


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

    rsi_ma = temp1.ewm(alpha=1.0/n, adjust=False).mean()
    abs_ma = temp2.ewm(alpha=1.0/n, adjust=False).mean()

    rsi = rsi_ma / (abs_ma + 1e-9) * 100.0
    return rsi


def compute_newb1_indicators(df: pd.DataFrame, cfg: HybridB1Config) -> pd.DataFrame:
    """计算newB1所需的所有指标"""
    df = df.copy()

    # 趋势白线 = EMA(EMA(C,10),10)
    trend_white = df["close"].ewm(
        span=cfg.trend_ema_span, adjust=False
    ).mean().ewm(span=cfg.trend_ema_span, adjust=False).mean()

    # 大哥黄线 = (MA(C,14)+MA(C,28)+MA(C,57)+MA(C,114))/4
    yellow = (
        df["close"].rolling(cfg.yellow_ma1, min_periods=1).mean()
        + df["close"].rolling(cfg.yellow_ma2, min_periods=1).mean()
        + df["close"].rolling(cfg.yellow_ma3, min_periods=1).mean()
        + df["close"].rolling(cfg.yellow_ma4, min_periods=1).mean()
    ) / 4.0

    # 短期 = 100*(C-LLV(L,3))/(HHV(C,3)-LLV(L,3))
    llv_l_short = df["low"].rolling(cfg.short_term_n, min_periods=1).min()
    hhv_c_short = df["close"].rolling(cfg.short_term_n, min_periods=1).max()
    short_term = 100 * (df["close"] - llv_l_short) / (hhv_c_short - llv_l_short + 1e-9)

    # 长期 = 100*(C-LLV(L,21))/(HHV(C,21)-LLV(L,21))
    llv_l_long = df["low"].rolling(cfg.long_term_n, min_periods=1).min()
    hhv_c_long = df["close"].rolling(cfg.long_term_n, min_periods=1).max()
    long_term = 100 * (df["close"] - llv_l_long) / (hhv_c_long - llv_l_long + 1e-9)

    # BBI = (MA(C,3)+MA(C,6)+MA(C,12)+MA(C,24))/4
    bbi = (
        df["close"].rolling(cfg.bbi_ma1, min_periods=1).mean()
        + df["close"].rolling(cfg.bbi_ma2, min_periods=1).mean()
        + df["close"].rolling(cfg.bbi_ma3, min_periods=1).mean()
        + df["close"].rolling(cfg.bbi_ma4, min_periods=1).mean()
    ) / 4.0

    # KDJ
    kdj = compute_kdj(df, cfg.kdj_n)

    # RSI(3)
    rsi = compute_rsi(df, cfg.rsi_n)

    # 赋值
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


def check_volume_conditions(df: pd.DataFrame, cfg: HybridB1Config) -> dict[str, bool]:
    """检查成交量条件"""
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

    # VDAY = distance to day with highest volume in 40 days
    vol_40 = vol.tail(cfg.max_vol_lookback)
    if len(vol_40) > 0:
        vday_idx = vol_40.idxmax() if hasattr(vol_40, 'idxmax') else len(df) - cfg.max_vol_lookback + vol_40.to_numpy().argmax()
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


def check_volatility_conditions(df: pd.DataFrame, cfg: HybridB1Config) -> dict[str, Any]:
    """检查波动条件"""
    if len(df) < max(cfg.n_volatility, cfg.m_volatility):
        return {
            "recent_move": False,
            "far_move": False,
            "super_move": False,
            "wash_move": False,
            "recent_amp_pct": None,
            "far_amp_pct": None,
        }

    high_n = df["high"].rolling(cfg.n_volatility, min_periods=1).max()
    low_n = df["low"].rolling(cfg.n_volatility, min_periods=1).min()
    recent_amp = (high_n - low_n) / (low_n + 1e-9) * 100

    high_m = df["high"].rolling(cfg.m_volatility, min_periods=1).max()
    low_m = df["low"].rolling(cfg.m_volatility, min_periods=1).min()
    far_amp = (high_m - low_m) / (low_m + 1e-9) * 100

    # 近期异动
    high_12 = df["high"].rolling(12, min_periods=1).max()
    low_14 = df["low"].rolling(14, min_periods=1).min()
    special_move = (high_12 - low_14) / (low_14 + 1e-9) * 100
    recent_move = (recent_amp.iloc[-1] >= 15) or (special_move.iloc[-1] >= 11)

    far_move = far_amp.iloc[-1] >= 30
    super_move = recent_amp.iloc[-1] >= 60
    wash_move = False  # 简化版，暂不实现复杂形态

    return {
        "recent_move": bool(recent_move),
        "far_move": bool(far_move),
        "super_move": bool(super_move),
        "wash_move": bool(wash_move),
        "recent_amp_pct": _safe_float(recent_amp.iloc[-1]),
        "far_amp_pct": _safe_float(far_amp.iloc[-1]),
    }


def check_trend_conditions(df: pd.DataFrame) -> dict[str, bool]:
    """检查趋势条件"""
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

    # 红肥绿瘦
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

    # 超牛股
    bbi_rising = (bbi >= bbi.shift(1) * 0.999).rolling(20, min_periods=1).sum()
    bbi_rising_count = (bbi >= bbi.shift(1)).rolling(25, min_periods=1).sum()
    bbi_condition = (bbi_rising.iloc[-1] >= 20) or (bbi_rising_count.iloc[-1] >= 23)

    # 检查是否穿越黄线
    cross_condition = False
    bars_since = 0
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

    vol = check_volatility_conditions(df, HybridB1Config())
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


def check_pullback_conditions(df: pd.DataFrame) -> dict[str, Any]:
    """检查回踩条件"""
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


class HybridB1Selector:
    """
    高质量B1组合选择器

    组合以下4种信号的并集:
    1. oldB1 - 原有B1Selector的输出
    2. 原始B1 (newB1 Signal 3)
    3. 回踩黄线B (newB1 Signal 7)
    4. 回踩超级B (newB1 Signal 6)
    """

    ENABLED_SIGNALS = {
        3: "原始B1",
        6: "回踩超级B",
        7: "回踩黄线B",
    }

    def __init__(self, config: HybridB1Config | None = None):
        """
        Args:
            config: HybridB1配置参数
        """
        self.cfg = config or HybridB1Config()

        # oldB1选择器
        self.old_b1_selector = B1Selector(
            j_threshold=self.cfg.j_threshold,
            j_q_threshold=self.cfg.j_q_threshold,
            zx_m1=self.cfg.zx_m1,
            zx_m2=self.cfg.zx_m2,
            zx_m3=self.cfg.zx_m3,
            zx_m4=self.cfg.zx_m4,
        )

    def prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        预计算所有指标（兼容B1Selector接口）

        Returns:
            包含oldB1和newB1所有指标的DataFrame
        """
        # 先用oldB1的prepare_df计算其需要的指标
        df = self.old_b1_selector.prepare_df(df)

        # 计算newB1需要的额外指标
        df = compute_newb1_indicators(df, self.cfg)

        return df

    def vec_picks_from_prepared(
        self,
        df: pd.DataFrame,
        start: Optional[pd.Timestamp] = None,
        end: Optional[pd.Timestamp] = None,
    ) -> list[pd.Timestamp]:
        """兼容 PipelineSelector 批量接口，返回 Hybrid B1 通过日期。"""
        if df is None or df.empty:
            return []

        picked_dates: list[pd.Timestamp] = []
        for trade_date in df.index:
            ts = pd.Timestamp(trade_date)
            if start is not None and ts < start:
                continue
            if end is not None and ts > end:
                continue

            hist = df.loc[:trade_date]
            try:
                result = self.check_b1(hist, str(df.at[trade_date, "code"]) if "code" in df.columns else "")
            except Exception:
                continue
            if result.get("b1_passed") is True:
                picked_dates.append(ts)

        return picked_dates

    def check_b1(self, df: pd.DataFrame, code: str) -> dict[str, Any]:
        """
        检查是否满足高质量B1组合条件

        Args:
            df: 预处理后的股票数据（通过prepare_df处理）
            code: 股票代码

        Returns:
            {
                "b1_passed": bool,
                "b1_signal_type": str | None,  # old_b1 / 原始B1 / 回踩黄线B / 回踩超级B
                "j": float | None,
                "rsi": float | None,
                ...
            }
        """
        if df.empty:
            return {
                "b1_passed": False,
                "b1_signal_type": None,
                "j": None,
                "rsi": None,
            }

        last_row = df.iloc[-1]

        # 1. 先检查 oldB1
        old_b1_passed = bool(last_row.get("_vec_pick", False))
        if old_b1_passed:
            return {
                "b1_passed": True,
                "b1_signal_type": "old_b1",
                "j": _safe_float(last_row.get("J")),
                "rsi": _safe_float(last_row.get("RSI")),
            }

        # 2. 检查 newB1 的3个目标信号
        newb1_result = self._check_newb1_signals(df, code)
        return newb1_result

    def _check_newb1_signals(self, df: pd.DataFrame, code: str) -> dict[str, Any]:
        """检查newB1的3个目标信号（原始B1、回踩黄线B、回踩超级B）"""
        if len(df) < 30:
            return {
                "b1_passed": False,
                "b1_signal_type": None,
                "j": None,
                "rsi": None,
            }

        result = {
            "b1_passed": False,
            "b1_signal_type": None,
            "j": _safe_float(df["J"].iloc[-1]),
            "rsi": _safe_float(df["RSI"].iloc[-1]),
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

        # Determine 振幅区间
        is_growth_stock = (
            code.startswith(("68", "30", "4", "8", "9")) or
            (df["close"].pct_change().rolling(200, min_periods=1).max().iloc[-1] > 0.15)
        )
        amp_range = 8 if is_growth_stock else 5
        relax_coef = 0.9 if is_growth_stock else 1.0
        daily_change_adj = daily_change * relax_coef

        # Get all conditions
        vol_cond = check_volume_conditions(df, self.cfg)
        vol_cond2 = check_volatility_conditions(df, self.cfg)
        trend_cond = check_trend_conditions(df)
        pullback_cond = check_pullback_conditions(df)

        any_move = vol_cond2["recent_move"] or vol_cond2["far_move"] or vol_cond2["wash_move"]

        j = df["J"].iloc[-1]
        rsi = df["RSI"].iloc[-1]
        j_llv = df["J"].rolling(20, min_periods=1).min().iloc[-1]
        rsi_llv = df["RSI"].rolling(14, min_periods=1).min().iloc[-1]

        not_big_green_ok = vol_cond["not_big_green"] or vol_cond["big_green_far"]

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
             (vol_cond["moderate_shrink"] and (pullback_cond.get("dist_white") or 0) < 1.8)) and
            any_move
        )

        if signal3:
            return {
                "b1_passed": True,
                "b1_signal_type": "原始B1",
                "j": _safe_float(j),
                "rsi": _safe_float(rsi),
            }

        # Signal 6: 回踩超级B
        rsi_j_llv_25 = (df["RSI"] + df["J"]).rolling(25, min_periods=1).min().iloc[-1]
        signal6 = (
            trend_cond["super_bull"] and
            (j < 35 or rsi < 45 or vol_cond2["wash_move"]) and
            (rsi + j < 80) and
            abs((rsi + j) - rsi_j_llv_25) < 0.01 and
            daily_amp < amp_range + 1 and
            (daily_change_adj < 2.5 or (pullback_cond.get("dist_white") or 999) < 2) and
            pullback_cond["strong_pullback_hold"] and
            not_big_green_ok and
            any_move and
            vol_cond["moderate_shrink"]
        )

        if signal6:
            return {
                "b1_passed": True,
                "b1_signal_type": "回踩超级B",
                "j": _safe_float(j),
                "rsi": _safe_float(rsi),
            }

        # Signal 7: 回踩黄线B
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
            (vol_cond2.get("recent_amp_pct") or 0) >= 11.9 and
            (vol_cond2.get("far_amp_pct") or 0) >= 19.5
        )

        if signal7:
            return {
                "b1_passed": True,
                "b1_signal_type": "回踩黄线B",
                "j": _safe_float(j),
                "rsi": _safe_float(rsi),
            }

        # 都不通过
        return result
