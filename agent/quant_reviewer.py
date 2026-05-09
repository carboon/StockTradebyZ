"""
quant_reviewer.py
~~~~~~~~~~~~~~~~~
第 4 步程序化复核器：

1. 保留 prompt.md 的四维评分框架
2. 与第 2 步初选解耦，不复用 KDJ / 知行线 / 砖型图 / 周线多头过滤
3. 所有计算均严格按 pick_date 截断，可用于历史滚动回测

程序化复核维度：
  - trend_structure        趋势结构
  - price_position         价格位置
  - volume_behavior        量价行为
  - previous_abnormal_move 历史建仓异动
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "pipeline"))

from base_reviewer import BaseReviewer
from review_prefilter import Step4Prefilter

_DEFAULT_CONFIG_PATH = _ROOT / "config" / "quant_review.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "candidates": "data/candidates/candidates_latest.json",
    "raw_dir": "data/raw",
    "output_dir": "data/review",
    "skip_existing": False,
    "suggest_min_score": 4.0,
    "disabled_strategies": ["brick"],
    "thresholds": {
        "pass_score": 4.0,
        "watch_score": 3.2,
        "pass_min_position_score": 4,
    },
    "trend": {
        "ema_fast": 20,
        "ema_slow": 60,
        "slope_fast_lookback": 5,
        "slope_slow_lookback": 10,
        "slope_fast_strong": 0.020,
        "slope_fast_positive": 0.008,
        "slope_slow_positive": 0.010,
        "efficiency_lookback": 20,
        "efficiency_strong": 0.45,
        "efficiency_healthy": 0.30,
        "breakout_lookback": 20,
        "breakout_fresh_days": 10,
        "pullback_limit": 0.08,
        "close_above_fast_ratio_lookback": 10,
        "close_above_fast_ratio_min": 0.60,
    },
    "position": {
        "range_lookback": 120,
        "runup_lookback": 60,
        "long_high_lookback": 250,
        "ideal_range_low": 0.35,
        "ideal_range_high": 0.70,
        "breakout_range_high": 0.85,
        "pressure_distance": 0.05,
        "long_high_space_min": 0.10,
        "runup_cool": 0.35,
        "runup_hot": 0.60,
        "runup_exhausted": 1.00,
        "extension_atr_watch": 2.5,
        "extension_atr_fail": 3.5,
    },
    "volume": {
        "window": 20,
        "obv_lookback": 10,
        "up_down_ratio_strong": 1.25,
        "up_down_ratio_healthy": 1.05,
        "up_down_ratio_weak": 0.90,
        "distribution_drop": -0.025,
        "distribution_vol_ratio": 1.50,
        "severe_distribution_drop": -0.040,
        "severe_distribution_vol_ratio": 1.80,
        "pullback_window": 3,
        "thrust_window": 10,
        "pullback_dryup_strong": 0.65,
        "pullback_dryup_healthy": 0.85,
    },
    "abnormal": {
        "window": 60,
        "breakout_lookback": 20,
        "pulse_return_strong": 0.035,
        "pulse_return_mild": 0.020,
        "pulse_body_strong": 0.020,
        "pulse_body_mild": 0.010,
        "pulse_vol_strong": 1.80,
        "pulse_vol_mild": 1.30,
        "pulse_fresh_days": 25,
        "hold_ratio": 0.98,
        "runup_safe": 0.50,
        "runup_danger": 1.00,
    },
    "weekly_context": {
        "ema_fast": 8,
        "ema_slow": 21,
        "slope_lookback": 3,
    },
    "prefilter": {
        "enabled": True,
        "cache_dir": "data/tushare_cache",
        "history_start": "20190101",
        "universe": {
            "exclude_st": True,
            "min_listing_days": 120,
        },
        "unlock": {
            "enabled": True,
            "lookahead_days": 20,
            "max_free_share_ratio": 0.15,
        },
        "size_bucket": {
            "enabled": True,
            "quantiles": [0.333333, 0.666667],
            "allowed": [],
        },
        "industry_strength": {
            "enabled": True,
            "lookback_days": 20,
            "top_pct": 0.30,
            "benchmark_index": "000905.SH",
        },
        "market_regime": {
            "enabled": True,
            "lookback_days": 20,
            "ema_fast": 20,
            "ema_slow": 60,
            "min_pass_count": 1,
            "indexes": [
                {"ts_code": "000905.SH", "name": "CSI500"},
                {"ts_code": "399006.SZ", "name": "CHINEXT"},
            ],
        },
    },
}


def _resolve_cfg_path(path_like: str | Path, base_dir: Path = _ROOT) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else (base_dir / p)


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    cfg_path = config_path or _DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(f"找不到配置文件：{cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = _deep_merge(DEFAULT_CONFIG, raw)
    cfg["candidates"] = _resolve_cfg_path(cfg["candidates"])
    cfg["raw_dir"] = _resolve_cfg_path(cfg["raw_dir"])
    cfg["output_dir"] = _resolve_cfg_path(cfg["output_dir"])
    cfg["disabled_strategies"] = [str(s).lower() for s in cfg.get("disabled_strategies", [])]
    if "backtest" in cfg and "output_dir" in cfg["backtest"]:
        cfg["backtest"]["output_dir"] = _resolve_cfg_path(cfg["backtest"]["output_dir"])
    if "prefilter" in cfg and "cache_dir" in cfg["prefilter"]:
        cfg["prefilter"]["cache_dir"] = _resolve_cfg_path(cfg["prefilter"]["cache_dir"])
    return cfg


def _pct(val: float) -> str:
    return f"{val * 100:.1f}%"


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        num = float(val)
    except (TypeError, ValueError):
        return default
    return num if math.isfinite(num) else default


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index(drop=True)
    out.columns = [c.lower() for c in out.columns]
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError(f"缺少必要列：{sorted(missing)}")

    out["date"] = pd.to_datetime(out["date"])
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = (
        out.dropna(subset=["date", "open", "high", "low", "close", "volume"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    out = out[out["volume"] > 0].copy()
    out = out.set_index("date", drop=False)
    return out


def _rolling_mean_where(values: pd.Series, mask: pd.Series, window: int) -> pd.Series:
    masked_sum = values.where(mask, 0.0).rolling(window, min_periods=1).sum()
    count = mask.astype(float).rolling(window, min_periods=1).sum().replace(0.0, np.nan)
    return masked_sum / count


def _atr_series(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _obv_series(close: pd.Series, volume: pd.Series) -> pd.Series:
    c = close.to_numpy(dtype=np.float64)
    v = volume.to_numpy(dtype=np.float64)
    out = np.zeros(len(close), dtype=np.float64)
    for i in range(1, len(close)):
        if c[i] > c[i - 1]:
            out[i] = out[i - 1] + v[i]
        elif c[i] < c[i - 1]:
            out[i] = out[i - 1] - v[i]
        else:
            out[i] = out[i - 1]
    return pd.Series(out, index=close.index)


def _days_since_true(mask: pd.Series) -> pd.Series:
    arr = mask.fillna(False).to_numpy(dtype=bool)
    out = np.full(len(arr), np.inf, dtype=np.float64)
    last_true = -1
    for i, flag in enumerate(arr):
        if flag:
            last_true = i
            out[i] = 0.0
        elif last_true >= 0:
            out[i] = float(i - last_true)
    return pd.Series(out, index=mask.index)


def _compute_weekly_context(close: pd.Series, cfg: dict[str, Any]) -> pd.DataFrame:
    idx = close.index
    iso = idx.isocalendar()
    year_week = iso.year.astype(str) + "-" + iso.week.astype(str).str.zfill(2)
    weekly_close = close.groupby(year_week).last()
    weekly_dates = close.groupby(year_week).apply(lambda s: s.index[-1])
    weekly_close.index = pd.DatetimeIndex(weekly_dates.to_numpy())

    fast = weekly_close.ewm(span=int(cfg["ema_fast"]), adjust=False).mean()
    slow = weekly_close.ewm(span=int(cfg["ema_slow"]), adjust=False).mean()
    slope = fast.pct_change(int(cfg["slope_lookback"]))

    weekly = pd.DataFrame(
        {
            "weekly_fast": fast,
            "weekly_slow": slow,
            "weekly_slope": slope,
        }
    )
    return weekly.reindex(idx).ffill()


def min_bars_required(config: dict[str, Any]) -> int:
    trend = config["trend"]
    position = config["position"]
    abnormal = config["abnormal"]
    weekly = config["weekly_context"]
    return max(
        int(trend["ema_slow"]) + int(trend["slope_slow_lookback"]),
        int(position["long_high_lookback"]),
        int(position["range_lookback"]),
        int(position["runup_lookback"]),
        int(abnormal["window"]) + int(abnormal["breakout_lookback"]),
        int(weekly["ema_slow"]) * 5,
    )


def _is_strategy_disabled(config: dict[str, Any], strategy: str | None = None) -> bool:
    if not strategy:
        return False
    return str(strategy).lower() in set(config.get("disabled_strategies", []))


def prepare_review_frame(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    frame = _normalize_ohlcv(df)
    close = frame["close"].astype(float)
    open_ = frame["open"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)

    trend_cfg = config["trend"]
    pos_cfg = config["position"]
    vol_cfg = config["volume"]
    abn_cfg = config["abnormal"]
    weekly_cfg = config["weekly_context"]

    atr14 = _atr_series(high, low, close, period=14)
    ema_fast = close.ewm(span=int(trend_cfg["ema_fast"]), adjust=False).mean()
    ema_slow = close.ewm(span=int(trend_cfg["ema_slow"]), adjust=False).mean()

    fast_lb = int(trend_cfg["slope_fast_lookback"])
    slow_lb = int(trend_cfg["slope_slow_lookback"])
    eff_lb = int(trend_cfg["efficiency_lookback"])
    breakout_lb = int(trend_cfg["breakout_lookback"])

    frame["atr14"] = atr14
    frame["ema_fast"] = ema_fast
    frame["ema_slow"] = ema_slow
    frame["fast_slope"] = ema_fast.pct_change(fast_lb)
    frame["slow_slope"] = ema_slow.pct_change(slow_lb)

    direction = (close - close.shift(eff_lb)).abs()
    distance = close.diff().abs().rolling(eff_lb, min_periods=eff_lb).sum().replace(0.0, np.nan)
    frame["efficiency"] = (direction / distance).clip(lower=0.0, upper=1.0)

    trend_breakout_level = high.rolling(breakout_lb, min_periods=breakout_lb).max().shift(1)
    trend_breakout = close > trend_breakout_level
    frame["trend_breakout_level"] = trend_breakout_level
    frame["trend_breakout_days"] = _days_since_true(trend_breakout)
    frame["pullback_from_high"] = 1.0 - close / close.rolling(breakout_lb, min_periods=1).max()

    ratio_lb = int(trend_cfg["close_above_fast_ratio_lookback"])
    frame["close_above_fast_ratio"] = (close > ema_fast).astype(float).rolling(ratio_lb, min_periods=1).mean()

    range_lb = int(pos_cfg["range_lookback"])
    long_high_lb = int(pos_cfg["long_high_lookback"])
    runup_lb = int(pos_cfg["runup_lookback"])
    range_high = high.rolling(range_lb, min_periods=range_lb).max()
    range_low = low.rolling(range_lb, min_periods=range_lb).min()
    range_span = (range_high - range_low).replace(0.0, np.nan)
    long_high = high.rolling(long_high_lb, min_periods=long_high_lb).max()
    runup_low = low.rolling(runup_lb, min_periods=runup_lb).min()

    frame["range_position"] = (close - range_low) / range_span
    frame["dist_range_high"] = 1.0 - close / range_high.replace(0.0, np.nan)
    frame["dist_long_high"] = 1.0 - close / long_high.replace(0.0, np.nan)
    frame["runup"] = close / runup_low.replace(0.0, np.nan) - 1.0
    frame["extension_atr"] = (close - ema_fast) / atr14.replace(0.0, np.nan)

    window = int(vol_cfg["window"])
    vol_ma = volume.rolling(window, min_periods=1).mean()
    up_mask = close > open_
    down_mask = close < open_
    up_mean = _rolling_mean_where(volume, up_mask, window)
    down_mean = _rolling_mean_where(volume, down_mask, window)
    frame["vol_ma"] = vol_ma
    frame["up_down_ratio"] = up_mean / down_mean.replace(0.0, np.nan)

    daily_return = close.pct_change().fillna(0.0)
    distribution = (
        (daily_return <= float(vol_cfg["distribution_drop"]))
        & (volume >= vol_ma * float(vol_cfg["distribution_vol_ratio"]))
    )
    severe_distribution = (
        (daily_return <= float(vol_cfg["severe_distribution_drop"]))
        & (volume >= vol_ma * float(vol_cfg["severe_distribution_vol_ratio"]))
    )
    frame["distribution_count"] = distribution.astype(float).rolling(window, min_periods=1).sum()
    frame["severe_distribution_count"] = severe_distribution.astype(float).rolling(window, min_periods=1).sum()

    pullback_window = int(vol_cfg["pullback_window"])
    thrust_window = int(vol_cfg["thrust_window"])
    frame["pullback_dryup"] = (
        volume.rolling(pullback_window, min_periods=1).mean()
        / volume.rolling(thrust_window, min_periods=1).max().replace(0.0, np.nan)
    )
    obv = _obv_series(close, volume)
    frame["obv_slope"] = obv.diff(int(vol_cfg["obv_lookback"]))

    body_pct = ((close - open_) / open_.replace(0.0, np.nan)).fillna(0.0)
    abn_breakout = high.rolling(int(abn_cfg["breakout_lookback"]), min_periods=int(abn_cfg["breakout_lookback"])).max().shift(1)
    strong_pulse = (
        (daily_return >= float(abn_cfg["pulse_return_strong"]))
        & (body_pct >= float(abn_cfg["pulse_body_strong"]))
        & (volume >= vol_ma * float(abn_cfg["pulse_vol_strong"]))
        & (close >= abn_breakout)
    )
    mild_pulse = (
        (daily_return >= float(abn_cfg["pulse_return_mild"]))
        & (body_pct >= float(abn_cfg["pulse_body_mild"]))
        & (volume >= vol_ma * float(abn_cfg["pulse_vol_mild"]))
    )

    abn_window = int(abn_cfg["window"])
    frame["strong_pulse_count"] = strong_pulse.astype(float).rolling(abn_window, min_periods=1).sum()
    frame["mild_pulse_count"] = mild_pulse.astype(float).rolling(abn_window, min_periods=1).sum()
    frame["days_since_pulse"] = _days_since_true(strong_pulse)
    frame["last_pulse_breakout"] = abn_breakout.where(strong_pulse).ffill()
    frame["holds_pulse"] = frame["last_pulse_breakout"].notna() & (
        close >= frame["last_pulse_breakout"] * float(abn_cfg["hold_ratio"])
    )
    frame["pulse_failed"] = frame["last_pulse_breakout"].notna() & (
        close < frame["last_pulse_breakout"] * float(abn_cfg["hold_ratio"])
    ) & (frame["distribution_count"] >= 1)

    weekly = _compute_weekly_context(close, weekly_cfg)
    frame["weekly_fast"] = weekly["weekly_fast"]
    frame["weekly_slow"] = weekly["weekly_slow"]
    frame["weekly_slope"] = weekly["weekly_slope"]

    min_bars = min_bars_required(config)
    frame["_ready"] = np.arange(1, len(frame) + 1) >= min_bars
    return frame


def _row_asof(frame: pd.DataFrame, asof_date: str | None = None) -> pd.Series | None:
    if frame.empty:
        return None
    if asof_date is None:
        return frame.iloc[-1]
    target = pd.to_datetime(asof_date)
    subset = frame.loc[:target]
    if subset.empty:
        return None
    return subset.iloc[-1]


def _weekly_text(row: pd.Series) -> str:
    fast = _safe_float(row.get("weekly_fast"), default=np.nan)
    slow = _safe_float(row.get("weekly_slow"), default=np.nan)
    slope = _safe_float(row.get("weekly_slope"), default=np.nan)
    if not math.isfinite(fast) or not math.isfinite(slow):
        return "周线信息不足"
    if fast > slow and slope > 0:
        return "周线偏多"
    if fast < slow and slope < 0:
        return "周线承压"
    return "周线走平"


def _score_trend(row: pd.Series, cfg: dict[str, Any]) -> tuple[int, str]:
    breakout_days = _safe_float(row.get("trend_breakout_days"), default=np.inf)
    fast_slope = _safe_float(row.get("fast_slope"))
    slow_slope = _safe_float(row.get("slow_slope"))
    efficiency = _safe_float(row.get("efficiency"))
    pullback = _safe_float(row.get("pullback_from_high"))
    above_fast = _safe_float(row.get("close_above_fast_ratio"))
    close_ = _safe_float(row.get("close"))
    ema_fast = _safe_float(row.get("ema_fast"))
    ema_slow = _safe_float(row.get("ema_slow"))

    breakout_fresh = breakout_days <= float(cfg["breakout_fresh_days"])
    strong = (
        breakout_fresh
        and close_ >= ema_fast >= ema_slow
        and fast_slope >= float(cfg["slope_fast_strong"])
        and slow_slope >= float(cfg["slope_slow_positive"])
        and efficiency >= float(cfg["efficiency_strong"])
        and pullback <= float(cfg["pullback_limit"])
    )
    healthy = (
        close_ >= ema_fast >= ema_slow
        and fast_slope >= float(cfg["slope_fast_positive"])
        and slow_slope >= float(cfg["slope_slow_positive"])
        and efficiency >= float(cfg["efficiency_healthy"])
        and above_fast >= float(cfg["close_above_fast_ratio_min"])
    )

    if strong:
        return 5, (
            f"近{int(breakout_days)}日内刚突破前高，EMA20/EMA60 同步抬升，"
            f"趋势效率 {efficiency:.2f}，回撤仅 {_pct(pullback)}，趋势刚进入强势段"
        )
    if healthy:
        return 4, (
            f"价格稳定运行在 EMA20/EMA60 之上，EMA20 近{int(cfg['slope_fast_lookback'])}日抬升 {_pct(fast_slope)}，"
            f"趋势效率 {efficiency:.2f}，结构健康"
        )
    if fast_slope > 0 and close_ >= ema_slow:
        return 3, (
            f"短期均线继续上拐（{_pct(fast_slope)}），但趋势效率 {efficiency:.2f} 一般，"
            "更像偏多修复而非流畅主升"
        )
    if fast_slope > -0.005 or slow_slope > 0:
        return 2, (
            f"短中期斜率分化，EMA20/EMA60 缺少同步推进，趋势效率 {efficiency:.2f}，"
            "结构偏乱"
        )
    return 1, (
        f"EMA20 斜率 {_pct(fast_slope)}、EMA60 斜率 {_pct(slow_slope)}，"
        "趋势明显偏弱，更像反弹而非启动"
    )


def _score_position(row: pd.Series, cfg: dict[str, Any]) -> tuple[int, str]:
    pos = _safe_float(row.get("range_position"), default=np.nan)
    dist_high = _safe_float(row.get("dist_range_high"), default=np.nan)
    dist_long = _safe_float(row.get("dist_long_high"), default=np.nan)
    runup = _safe_float(row.get("runup"))
    extension = _safe_float(row.get("extension_atr"))

    if runup >= float(cfg["runup_exhausted"]) or extension >= float(cfg["extension_atr_fail"]):
        return 1, (
            f"近{int(cfg['runup_lookback'])}日累计涨幅 {_pct(runup)}，偏离 EMA20 达 {extension:.1f}ATR，"
            "已经进入明显过热区"
        )
    if dist_high <= float(cfg["pressure_distance"]) and (
        runup >= float(cfg["runup_hot"]) or extension >= float(cfg["extension_atr_watch"])
    ):
        return 2, (
            f"距离 {int(cfg['range_lookback'])}日高点仅 {_pct(dist_high)}，"
            f"近段涨幅 {_pct(runup)}，上方压力明显"
        )
    if (
        float(cfg["ideal_range_low"]) <= pos <= float(cfg["ideal_range_high"])
        and dist_long >= float(cfg["long_high_space_min"])
        and runup < float(cfg["runup_cool"])
        and extension < float(cfg["extension_atr_watch"])
    ):
        return 5, (
            f"处于 {int(cfg['range_lookback'])}日区间 {_pct(pos)} 位置，"
            f"距离长周期高点仍有 {_pct(dist_long)} 空间，近段涨幅 {_pct(runup)}，性价比较高"
        )
    if (
        pos <= float(cfg["breakout_range_high"])
        and dist_high > float(cfg["pressure_distance"])
        and runup < float(cfg["runup_hot"])
        and extension < float(cfg["extension_atr_watch"])
    ):
        return 4, (
            f"已脱离整理区，位于区间 {_pct(pos)}，距离近期高点 {_pct(dist_high)}，"
            f"涨幅 {_pct(runup)}，仍属可推进区"
        )
    if dist_high <= float(cfg["pressure_distance"]) or dist_long <= float(cfg["long_high_space_min"]) or runup >= float(cfg["runup_hot"]):
        return 3, (
            f"处于区间 {_pct(pos)} 位置，距离近期高点 {_pct(dist_high)}，"
            f"涨幅 {_pct(runup)}，已接近压力区"
        )
    return 3, f"位置中性，区间位置 {_pct(pos)}，近段涨幅 {_pct(runup)}，继续上行仍需验证"


def _score_volume(row: pd.Series, cfg: dict[str, Any]) -> tuple[int, str]:
    ratio = _safe_float(row.get("up_down_ratio"))
    dist_count = int(round(_safe_float(row.get("distribution_count"))))
    severe_count = int(round(_safe_float(row.get("severe_distribution_count"))))
    dryup = _safe_float(row.get("pullback_dryup"))
    obv_slope = _safe_float(row.get("obv_slope"))

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


def _score_abnormal(row: pd.Series, cfg: dict[str, Any]) -> tuple[int, str]:
    strong_count = int(round(_safe_float(row.get("strong_pulse_count"))))
    mild_count = int(round(_safe_float(row.get("mild_pulse_count"))))
    days_since = _safe_float(row.get("days_since_pulse"), default=np.inf)
    holds = bool(row.get("holds_pulse", False))
    failed = bool(row.get("pulse_failed", False))
    runup = _safe_float(row.get("runup"))

    if runup >= float(cfg["runup_danger"]) or failed:
        reason = f"近段涨幅 {_pct(runup)} 已过大" if runup >= float(cfg["runup_danger"]) else "异动后的突破位已失守"
        return 1, reason + "，主升段更可能接近尾声"
    if strong_count >= 1 and days_since <= float(cfg["pulse_fresh_days"]) and holds and runup < float(cfg["runup_safe"]):
        return 5, (
            f"近 {int(cfg['window'])} 日出现 {strong_count} 次强放量突破，"
            f"最近一次距今 {int(days_since)} 日且仍守在突破位上方，建仓痕迹明确"
        )
    if strong_count >= 1 and holds and runup < float(cfg["runup_safe"]):
        return 4, (
            f"近 {int(cfg['window'])} 日出现 {strong_count} 次强放量阳线，"
            "目前仍守住异动突破位，存在较明显建仓信号"
        )
    if mild_count >= 1 and runup < float(cfg["runup_safe"]):
        return 3, (
            f"近 {int(cfg['window'])} 日出现 {mild_count} 次中等放量推进，"
            "有异动但强度尚不足以确认主力建仓"
        )
    if runup >= float(cfg["runup_safe"]):
        return 2, f"近段涨幅已达 {_pct(runup)}，但缺少明确的强异动建仓证据"
    return 2, "最近一段缺少明确强放量突破，建仓异动证据不足"


def _determine_signal(
    scores: dict[str, int],
    total_score: float,
    thresholds: dict[str, float],
) -> tuple[str, str]:
    if (
        scores["price_position"] <= 2
        or scores["volume_behavior"] <= 2
        or scores["previous_abnormal_move"] == 1
    ):
        return "distribution_risk", "位置偏高或量价转差或主升段过长，当前更偏向风险释放"

    if (
        total_score >= float(thresholds["pass_score"])
        and scores["trend_structure"] >= 4
        and scores["price_position"] >= int(thresholds.get("pass_min_position_score", 3))
        and scores["volume_behavior"] >= 4
        and scores["previous_abnormal_move"] >= 4
    ):
        return "trend_start", "趋势、量价与异动三项同时共振，更接近主升启动而非普通反弹"

    return "rebound", "结构偏多但尚未形成全面共振，暂按反弹延续看待"


def _determine_verdict(
    scores: dict[str, int],
    total_score: float,
    signal_type: str,
    thresholds: dict[str, float],
) -> str:
    if scores["volume_behavior"] == 1 or signal_type == "distribution_risk":
        return "FAIL"
    if signal_type == "trend_start" and total_score >= float(thresholds["pass_score"]):
        return "PASS"
    if total_score >= float(thresholds["watch_score"]):
        return "WATCH"
    return "FAIL"


def _generate_comment(
    row: pd.Series,
    scores: dict[str, int],
    signal_type: str,
) -> str:
    weekly = _weekly_text(row)
    vol_desc = {
        5: "量价配合极佳",
        4: "量价整体健康",
        3: "量价中性",
        2: "量价偏弱",
        1: "量价已破坏",
    }[scores["volume_behavior"]]
    abnormal_desc = {
        5: "历史异动显示强建仓痕迹",
        4: "历史异动较明显",
        3: "历史异动一般",
        2: "历史异动不足",
        1: "主升段可能接近尾声",
    }[scores["previous_abnormal_move"]]
    risk_desc = {
        "trend_start": "当前更像主升启动区",
        "rebound": "当前更偏反弹验证阶段",
        "distribution_risk": "当前以控制追高风险为先",
    }[signal_type]
    return f"{weekly}，{vol_desc}，{abnormal_desc}，{risk_desc}。"


def review_prepared_frame(
    frame: pd.DataFrame,
    config: dict[str, Any],
    code: str,
    asof_date: str | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    row = _row_asof(frame, asof_date)
    return review_prepared_row(row, config=config, code=code, strategy=strategy)


def review_prepared_row(
    row: pd.Series | None,
    config: dict[str, Any],
    code: str,
    strategy: str | None = None,
) -> dict[str, Any]:
    if _is_strategy_disabled(config, strategy):
        return {
            "trend_reasoning": f"策略来源 {strategy} 已在第 4 步被禁用",
            "position_reasoning": "已禁用策略来源",
            "volume_reasoning": "已禁用策略来源",
            "abnormal_move_reasoning": "已禁用策略来源",
            "signal_reasoning": "该初选来源不再参与程序化复核与推荐",
            "scores": {
                "trend_structure": 1,
                "price_position": 1,
                "volume_behavior": 1,
                "previous_abnormal_move": 1,
            },
            "total_score": 1.0,
            "signal_type": "strategy_disabled",
            "verdict": "FAIL",
            "comment": f"{strategy} 来源已禁用，不纳入第 4 步推荐。",
            "code": code,
            "strategy": strategy,
        }

    if row is None or not bool(row.get("_ready", False)):
        return {
            "trend_reasoning": "数据不足，无法计算程序化复核指标",
            "position_reasoning": "数据不足",
            "volume_reasoning": "数据不足",
            "abnormal_move_reasoning": "数据不足",
            "signal_reasoning": "数据不足，无法判定",
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
            "code": code,
            "strategy": strategy,
        }

    trend_score, trend_reasoning = _score_trend(row, config["trend"])
    pos_score, position_reasoning = _score_position(row, config["position"])
    vol_score, volume_reasoning = _score_volume(row, config["volume"])
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
        "code": code,
        "strategy": strategy,
    }


class QuantReviewer(BaseReviewer):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.raw_dir = Path(config["raw_dir"])
        self.prefilter = Step4Prefilter(config)

    def _load_csv(self, code: str) -> pd.DataFrame:
        csv_path = self.raw_dir / f"{code}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"找不到股票数据：{csv_path}")
        return pd.read_csv(csv_path)

    def review_stock_df(
        self,
        code: str,
        df: pd.DataFrame,
        asof_date: str | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        prefilter = self.prefilter.evaluate(code=code, pick_date=asof_date, price_df=df)
        frame = prepare_review_frame(df, self.config)
        result = review_prepared_frame(frame, self.config, code=code, asof_date=asof_date, strategy=strategy)
        result["prefilter"] = prefilter
        return result

    def review_stock(
        self,
        code: str,
        day_chart=None,
        prompt: str = "",
        asof_date: str | None = None,
        strategy: str | None = None,
    ) -> dict[str, Any]:
        df = self._load_csv(code)
        return self.review_stock_df(code, df, asof_date=asof_date, strategy=strategy)

    def run(self) -> None:
        candidates_data = self.load_candidates(Path(self.config["candidates"]))
        pick_date: str = candidates_data["pick_date"]
        candidates = candidates_data["candidates"]
        disabled_strategies = set(self.config.get("disabled_strategies", []))
        active_candidates = [
            c for c in candidates if str(c.get("strategy", "")).lower() not in disabled_strategies
        ]
        disabled_candidates = [
            c for c in candidates if str(c.get("strategy", "")).lower() in disabled_strategies
        ]
        disabled_count = len(candidates) - len(active_candidates)
        print(
            f"[INFO] pick_date={pick_date}，候选股票数={len(candidates)}，"
            f"启用后={len(active_candidates)}，禁用来源跳过={disabled_count}"
        )
        if self.prefilter.enabled:
            print("[INFO] 第 4 步前置过滤已启用：ST/次新/解禁/行业强度/市场环境")

        out_dir = self.output_dir / pick_date
        out_dir.mkdir(parents=True, exist_ok=True)

        removed_disabled_outputs = 0
        for candidate in disabled_candidates:
            out_file = out_dir / f"{candidate['code']}.json"
            if out_file.exists():
                out_file.unlink()
                removed_disabled_outputs += 1
        if removed_disabled_outputs:
            print(f"[INFO] 已清理禁用来源旧输出: {removed_disabled_outputs} 个")

        all_results: list[dict[str, Any]] = []
        failed_codes: list[str] = []

        for i, candidate in enumerate(active_candidates, 1):
            code = candidate["code"]
            strategy = candidate.get("strategy")
            out_file = out_dir / f"{code}.json"

            if self.config.get("skip_existing", False) and out_file.exists():
                print(f"[{i}/{len(active_candidates)}] {code} — 已存在，跳过。")
                with open(out_file, encoding="utf-8") as f:
                    all_results.append(json.load(f))
                continue

            print(f"[{i}/{len(active_candidates)}] {code} — 正在程序化复核 ...", end=" ", flush=True)
            try:
                df = self._load_csv(code)
                result = self.review_stock_df(code, df, asof_date=pick_date, strategy=strategy)
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                all_results.append(result)
                score = result.get("total_score")
                score_text = "blocked" if score is None else score
                print(f"完成 — verdict={result.get('verdict')}, score={score_text}")
            except Exception as exc:
                print(f"失败 — {exc}")
                failed_codes.append(code)

        print(f"\n[INFO] 评分完成：成功 {len(all_results)} 支，失败/跳过 {len(failed_codes)} 支")
        if failed_codes:
            print(f"[WARN] 未处理股票：{failed_codes}")

        if not all_results:
            print("[ERROR] 没有可用的评分结果，跳过汇总。")
            return

        min_score = float(self.config.get("suggest_min_score", 4.0))
        suggestion = self.generate_suggestion(
            pick_date=pick_date,
            all_results=all_results,
            min_score=min_score,
        )
        if self.prefilter.enabled:
            blocked_by_counts: dict[str, int] = {}
            prefilter_passed = 0
            for result in all_results:
                pf = result.get("prefilter") or {}
                if pf.get("passed", True):
                    prefilter_passed += 1
                for key in pf.get("blocked_by", []):
                    blocked_by_counts[key] = blocked_by_counts.get(key, 0) + 1
            suggestion["prefilter_summary"] = {
                "passed": prefilter_passed,
                "blocked": len(all_results) - prefilter_passed,
                "blocked_by": blocked_by_counts,
            }
        suggestion_file = out_dir / "suggestion.json"
        with open(suggestion_file, "w", encoding="utf-8") as f:
            json.dump(suggestion, f, ensure_ascii=False, indent=2)
        print(f"[INFO] 汇总推荐已写入: {suggestion_file}")
        print(f"       推荐股票数（PASS 且 score≥{min_score}）: {len(suggestion['recommendations'])}")
        print("\n全部完成。")
        print(f"   输出目录: {out_dir}")


def _print_single_result(result: dict[str, Any]) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {result.get('code', 'N/A')} 程序化复核结果")
    print(f"{'=' * 60}")

    scores = result.get("scores", {})
    print("\n【评分明细】")
    print(f"  趋势结构:     {scores.get('trend_structure', 'N/A')}/5")
    print(f"  价格位置:     {scores.get('price_position', 'N/A')}/5")
    print(f"  量价行为:     {scores.get('volume_behavior', 'N/A')}/5")
    print(f"  前期异动:     {scores.get('previous_abnormal_move', 'N/A')}/5")
    print("  ─────────────────────────")
    print(f"  总分:         {result.get('total_score', 'N/A')}/5")

    print("\n【研判结果】")
    print(f"  信号类型:     {result.get('signal_type', 'N/A')}")
    print(f"  判定:         {result.get('verdict', 'N/A')}")

    prefilter = result.get("prefilter")
    if prefilter and prefilter.get("enabled"):
        status = "通过" if prefilter.get("passed") else "拦截"
        print(f"\n【预过滤】{status}：{prefilter.get('summary', '')}")

    for key in [
        "trend_reasoning",
        "position_reasoning",
        "volume_reasoning",
        "abnormal_move_reasoning",
        "signal_reasoning",
    ]:
        value = result.get(key, "")
        if value:
            label = key.replace("_reasoning", "")
            print(f"\n【{label}】{value}")

    comment = result.get("comment", "")
    if comment:
        print(f"\n【点评】{comment}")
    print(f"\n{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="第 4 步程序化复核器（替代视觉模型）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python agent/quant_reviewer.py
  python agent/quant_reviewer.py --code 600519
  python agent/quant_reviewer.py --code 600519 --date 2026-04-16
        """,
    )
    parser.add_argument("--config", default=str(_DEFAULT_CONFIG_PATH), help="配置文件路径")
    parser.add_argument("--code", help="指定单只股票代码进行分析")
    parser.add_argument("--date", help="指定分析日期（YYYY-MM-DD，默认最新可用交易日）")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    reviewer = QuantReviewer(config)

    if args.code:
        result = reviewer.review_stock(args.code, asof_date=args.date)
        _print_single_result(result)
        return

    reviewer.run()


if __name__ == "__main__":
    main()
