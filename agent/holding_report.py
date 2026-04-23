"""
holding_report.py
~~~~~~~~~~~~~~~~~
按持仓视角输出单票 Markdown 报告。

功能：
1. 根据股票代码读取 data/raw/{code}.csv
2. 假设在 start_date 对应交易日收盘买入，分析到 end_date 对应交易日
3. 复用 quant 程序化复核口径，比较起点/终点评分变化
4. 输出持仓表现、关键指标变化、当前形态，以及明日观察点

示例：
    python agent/holding_report.py --code 601975 --start-date 2026-04-17 --end-date 2026-04-21
    python agent/holding_report.py --code 601083 --start-date 2026-04-17 --end-date 2026-04-21 --output /tmp/601083.md
"""
from __future__ import annotations

import argparse
import math
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL 1.1.1+")

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "agent"))

from quant_reviewer import load_config, prepare_review_frame, review_prepared_frame

_DEFAULT_QUANT_CONFIG = _ROOT / "config" / "quant_review.yaml"
_DEFAULT_PRESELECT_CONFIG = _ROOT / "config" / "rules_preselect.yaml"


def _fmt_price(value: Any) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(num):
        return "-"
    return f"{num:.2f}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(num):
        return "-"
    return f"{num * 100:.1f}%"


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(num):
        return "-"
    return f"{num:.{digits}f}"


def _fmt_int(value: Any) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "-"
    if not math.isfinite(num):
        return "-"
    return str(int(round(num)))


def _fmt_bool(value: bool) -> str:
    return "是" if bool(value) else "否"


def _markdown_escape(text: Any) -> str:
    return str(text).replace("|", "\\|")


def _load_stock_df(code: str, raw_dir: Path) -> pd.DataFrame:
    csv_path = raw_dir / f"{code}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"找不到股票数据：{csv_path}")
    return pd.read_csv(csv_path)


def _resolve_asof_row(frame: pd.DataFrame, target_date: str) -> pd.Series:
    target = pd.to_datetime(target_date)
    subset = frame.loc[:target]
    if subset.empty:
        raise ValueError(f"日期 {target_date} 早于可用数据起点")
    return subset.iloc[-1]


def _safe_float(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _load_b1_config(config_path: Path) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("b1", {})


def _compute_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()
    rsv = ((df["close"] - low_n) / (high_n - low_n + 1e-9) * 100.0).to_numpy(dtype=float)

    k = np.empty(len(rsv), dtype=np.float64)
    d = np.empty(len(rsv), dtype=np.float64)
    k[0] = d[0] = 50.0
    for i in range(1, len(rsv)):
        k[i] = 2.0 / 3.0 * k[i - 1] + 1.0 / 3.0 * rsv[i]
        d[i] = 2.0 / 3.0 * d[i - 1] + 1.0 / 3.0 * k[i]
    j = 3.0 * k - 2.0 * d
    out = df.copy()
    out["K"] = k
    out["D"] = d
    out["J"] = j
    return out


def _compute_zx_lines(
    close: pd.Series,
    *,
    zx_m1: int,
    zx_m2: int,
    zx_m3: int,
    zx_m4: int,
    zxdq_span: int = 10,
) -> tuple[pd.Series, pd.Series]:
    zxdq = close.ewm(span=zxdq_span, adjust=False).mean().ewm(span=zxdq_span, adjust=False).mean()
    zxdkx = (
        close.rolling(zx_m1, min_periods=zx_m1).mean()
        + close.rolling(zx_m2, min_periods=zx_m2).mean()
        + close.rolling(zx_m3, min_periods=zx_m3).mean()
        + close.rolling(zx_m4, min_periods=zx_m4).mean()
    ) / 4.0
    return zxdq, zxdkx


def _compute_weekly_ma_bull(
    close: pd.Series,
    *,
    wma_short: int = 10,
    wma_mid: int = 20,
    wma_long: int = 30,
) -> pd.Series:
    idx = close.index
    iso = idx.isocalendar()
    year_week = iso.year.astype(str) + "-" + iso.week.astype(str).str.zfill(2)
    weekly_close = close.groupby(year_week).last()
    weekly_dates = close.groupby(year_week).apply(lambda s: s.index[-1])
    weekly_close.index = pd.DatetimeIndex(weekly_dates.to_numpy())

    ma_s = weekly_close.rolling(wma_short, min_periods=wma_short).mean()
    ma_m = weekly_close.rolling(wma_mid, min_periods=wma_mid).mean()
    ma_l = weekly_close.rolling(wma_long, min_periods=wma_long).mean()
    bull = (ma_s > ma_m) & (ma_m > ma_l)
    return bull.astype(float).reindex(idx).ffill().fillna(0.0).astype(bool)


def _compute_b1_snapshot(frame: pd.DataFrame, asof_ts: pd.Timestamp, b1_cfg: dict[str, Any]) -> dict[str, Any]:
    subset = frame.loc[:asof_ts].copy()
    subset = _compute_kdj(subset, n=9)
    close = subset["close"].astype(float)
    zxdq, zxdkx = _compute_zx_lines(
        close,
        zx_m1=int(b1_cfg.get("zx_m1", 14)),
        zx_m2=int(b1_cfg.get("zx_m2", 28)),
        zx_m3=int(b1_cfg.get("zx_m3", 57)),
        zx_m4=int(b1_cfg.get("zx_m4", 114)),
        zxdq_span=10,
    )
    weekly_bull = _compute_weekly_ma_bull(close, wma_short=10, wma_mid=20, wma_long=30)
    subset["zxdq"] = zxdq
    subset["zxdkx"] = zxdkx
    subset["weekly_bull"] = weekly_bull

    row = subset.loc[asof_ts]
    j_today = float(row["J"])
    j_q = float(subset["J"].expanding(min_periods=1).quantile(float(b1_cfg.get("j_q_threshold", 0.10))).iloc[-1])
    j_threshold = float(b1_cfg.get("j_threshold", 15.0))
    kdj_ok = (j_today < j_threshold) or (j_today <= j_q)

    zxdq_v = _safe_float(row["zxdq"])
    zxdkx_v = _safe_float(row["zxdkx"])
    close_v = float(row["close"])
    zx_ok = bool(
        zxdq_v is not None
        and zxdkx_v is not None
        and close_v > zxdkx_v
        and zxdq_v > zxdkx_v
    )

    weekly_ok = bool(row["weekly_bull"])

    window = subset.tail(20)
    max_idx = window["volume"].idxmax()
    max_row = window.loc[max_idx]
    max_vol_ok = float(max_row["close"]) >= float(max_row["open"])

    return {
        "j_today": j_today,
        "j_q10": j_q,
        "kdj_ok": kdj_ok,
        "close": close_v,
        "zxdq": zxdq_v,
        "zxdkx": zxdkx_v,
        "zx_ok": zx_ok,
        "weekly_bull": weekly_ok,
        "max_vol_ok": max_vol_ok,
        "max_vol_date": pd.Timestamp(max_idx).strftime("%Y-%m-%d"),
        "max_vol_open": float(max_row["open"]),
        "max_vol_close": float(max_row["close"]),
        "picked": bool(kdj_ok and zx_ok and weekly_ok and max_vol_ok),
    }


def _build_holding_stats(window: pd.DataFrame, buy_price: float) -> dict[str, Any]:
    close = window["close"].astype(float)
    low = window["low"].astype(float)
    high = window["high"].astype(float)
    volume = window["volume"].astype(float)

    total_return = float(close.iloc[-1] / buy_price - 1.0)
    max_close_idx = close.idxmax()
    min_low_idx = low.idxmin()

    peak_close = close.cummax()
    drawdown = close / peak_close - 1.0
    max_dd_idx = drawdown.idxmin()

    day_return = close.pct_change().fillna(0.0)
    best_day_idx = day_return.idxmax()
    worst_day_idx = day_return.idxmin()

    return {
        "bars": len(window),
        "trading_days": max(len(window) - 1, 0),
        "buy_price": buy_price,
        "end_price": float(close.iloc[-1]),
        "total_return": total_return,
        "max_close_return": float(close.loc[max_close_idx] / buy_price - 1.0),
        "max_close_return_date": pd.Timestamp(max_close_idx).strftime("%Y-%m-%d"),
        "worst_intraday_return": float(low.loc[min_low_idx] / buy_price - 1.0),
        "worst_intraday_return_date": pd.Timestamp(min_low_idx).strftime("%Y-%m-%d"),
        "max_drawdown": float(drawdown.loc[max_dd_idx]),
        "max_drawdown_date": pd.Timestamp(max_dd_idx).strftime("%Y-%m-%d"),
        "best_day_return": float(day_return.loc[best_day_idx]),
        "best_day_return_date": pd.Timestamp(best_day_idx).strftime("%Y-%m-%d"),
        "worst_day_return": float(day_return.loc[worst_day_idx]),
        "worst_day_return_date": pd.Timestamp(worst_day_idx).strftime("%Y-%m-%d"),
        "avg_volume": float(volume.mean()),
        "avg_amplitude": float((high / low.replace(0.0, np.nan) - 1.0).mean()),
    }


def _metric_rows(start_row: pd.Series, end_row: pd.Series) -> list[tuple[str, str, str, str]]:
    items: list[tuple[str, Any, Any, str]] = [
        ("收盘价", start_row.get("close"), end_row.get("close"), "price"),
        ("成交量", start_row.get("volume"), end_row.get("volume"), "num0"),
        ("EMA20", start_row.get("ema_fast"), end_row.get("ema_fast"), "price"),
        ("EMA60", start_row.get("ema_slow"), end_row.get("ema_slow"), "price"),
        ("收盘价相对 EMA20", _ratio(start_row.get("close"), start_row.get("ema_fast")), _ratio(end_row.get("close"), end_row.get("ema_fast")), "pct"),
        ("收盘价相对 EMA60", _ratio(start_row.get("close"), start_row.get("ema_slow")), _ratio(end_row.get("close"), end_row.get("ema_slow")), "pct"),
        ("EMA20 斜率", start_row.get("fast_slope"), end_row.get("fast_slope"), "pct"),
        ("EMA60 斜率", start_row.get("slow_slope"), end_row.get("slow_slope"), "pct"),
        ("趋势效率", start_row.get("efficiency"), end_row.get("efficiency"), "num2"),
        ("120 日区间位置", start_row.get("range_position"), end_row.get("range_position"), "pct"),
        ("距 120 日高点", start_row.get("dist_range_high"), end_row.get("dist_range_high"), "pct"),
        ("近 60 日涨幅", start_row.get("runup"), end_row.get("runup"), "pct"),
        ("上涨/下跌量比", start_row.get("up_down_ratio"), end_row.get("up_down_ratio"), "num2"),
        ("分歧阴量次数", start_row.get("distribution_count"), end_row.get("distribution_count"), "int"),
        ("强异动次数", start_row.get("strong_pulse_count"), end_row.get("strong_pulse_count"), "int"),
        ("距最近强异动天数", start_row.get("days_since_pulse"), end_row.get("days_since_pulse"), "int"),
        ("周线斜率", start_row.get("weekly_slope"), end_row.get("weekly_slope"), "pct"),
    ]
    rows: list[tuple[str, str, str, str]] = []
    for label, start_value, end_value, style in items:
        rows.append((label, _format_by_style(start_value, style), _format_by_style(end_value, style), _format_delta(start_value, end_value, style)))
    return rows


def _score_rows(start_result: dict[str, Any], end_result: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    start_scores = start_result.get("scores", {})
    end_scores = end_result.get("scores", {})
    pairs = [
        ("趋势结构", start_scores.get("trend_structure"), end_scores.get("trend_structure"), "score"),
        ("价格位置", start_scores.get("price_position"), end_scores.get("price_position"), "score"),
        ("量价行为", start_scores.get("volume_behavior"), end_scores.get("volume_behavior"), "score"),
        ("历史异动", start_scores.get("previous_abnormal_move"), end_scores.get("previous_abnormal_move"), "score"),
        ("总分", start_result.get("total_score"), end_result.get("total_score"), "num1"),
    ]
    rows: list[tuple[str, str, str, str]] = []
    for label, start_value, end_value, style in pairs:
        rows.append((label, _format_by_style(start_value, style), _format_by_style(end_value, style), _format_delta(start_value, end_value, style)))
    rows.append(("信号类型", str(start_result.get("signal_type", "-")), str(end_result.get("signal_type", "-")), "-"))
    rows.append(("判定", str(start_result.get("verdict", "-")), str(end_result.get("verdict", "-")), "-"))
    return rows


def _ratio(a: Any, b: Any) -> float | None:
    av = _safe_float(a)
    bv = _safe_float(b)
    if av is None or bv is None or bv == 0.0:
        return None
    return av / bv - 1.0


def _format_by_style(value: Any, style: str) -> str:
    if style == "price":
        return _fmt_price(value)
    if style == "pct":
        return _fmt_pct(value)
    if style == "num0":
        return _fmt_num(value, digits=0)
    if style == "num1":
        return _fmt_num(value, digits=1)
    if style == "num2":
        return _fmt_num(value, digits=2)
    if style == "int":
        return _fmt_int(value)
    if style == "score":
        return "-" if value is None else f"{value}/5"
    return _markdown_escape(value)


def _format_delta(start_value: Any, end_value: Any, style: str) -> str:
    sv = _safe_float(start_value)
    ev = _safe_float(end_value)
    if sv is None or ev is None:
        return "-"
    delta = ev - sv
    sign = "+" if delta >= 0 else ""
    if style == "pct":
        return f"{sign}{delta * 100:.1f}pct"
    if style in {"price", "num0", "num1", "num2", "score", "int"}:
        digits = 2
        if style == "num0":
            digits = 0
        elif style == "num1":
            digits = 1
        elif style == "int":
            digits = 0
        elif style == "score":
            digits = 1
        return f"{sign}{delta:.{digits}f}"
    return "-"


def _render_table(headers: list[str], rows: list[tuple[str, ...]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_escape(col) for col in row) + " |")
    return "\n".join(lines)


def _support_resistance(frame: pd.DataFrame, end_ts: pd.Timestamp) -> dict[str, Any]:
    hist = frame.loc[:end_ts]
    tail5 = hist.tail(5)
    tail20 = hist.tail(20)
    close = float(hist.iloc[-1]["close"])
    ema20 = _safe_float(hist.iloc[-1].get("ema_fast"))
    pulse = _safe_float(hist.iloc[-1].get("last_pulse_breakout"))

    candidate_levels = [
        ("今日低点", float(hist.iloc[-1]["low"])),
        ("5日低点", float(tail5["low"].min())),
        ("今日高点", float(hist.iloc[-1]["high"])),
        ("5日高点", float(tail5["high"].max())),
        ("20日高点", float(tail20["high"].max())),
    ]
    if ema20 is not None:
        candidate_levels.append(("EMA20", ema20))
    if pulse is not None:
        candidate_levels.append(("异动保护位", pulse))

    deduped = {label: value for label, value in candidate_levels}
    support_levels = sorted(
        ((label, value) for label, value in deduped.items() if value <= close),
        key=lambda item: item[1],
        reverse=True,
    )
    resistance_levels = sorted(
        ((label, value) for label, value in deduped.items() if value > close),
        key=lambda item: item[1],
    )
    return {
        "vol_5d_avg": float(tail5["volume"].mean()),
        "vol_20d_avg": float(tail20["volume"].mean()),
        "today_return": float(hist.iloc[-1]["close"] / hist.iloc[-2]["close"] - 1.0) if len(hist) >= 2 else 0.0,
        "supports": support_levels,
        "resistances": resistance_levels,
    }


def _shape_summary(end_result: dict[str, Any]) -> str:
    scores = end_result.get("scores", {})
    trend = int(scores.get("trend_structure") or 0)
    position = int(scores.get("price_position") or 0)
    volume = int(scores.get("volume_behavior") or 0)
    abnormal = int(scores.get("previous_abnormal_move") or 0)
    verdict = end_result.get("verdict", "")
    signal = end_result.get("signal_type", "")

    if verdict == "PASS":
        return "当前更接近主升启动结构，可继续按趋势持有。"
    if trend >= 4 and position <= 3:
        return "当前更像趋势延续，但位置已经贴近短线压力位，继续持有更看重是否能有效突破。"
    if trend <= 2 and volume >= 4:
        return "当前更像反弹修复，量价并未破坏，但趋势底子仍偏弱，持仓应以防守支撑位为主。"
    if trend == 3 and volume >= 4 and abnormal >= 4:
        return "当前偏多结构尚在，但仍属于反弹验证阶段，还没有进入完全共振的主升形态。"
    if signal == "distribution_risk":
        return "当前已经偏向风险释放结构，不适合继续重仓持有。"
    if position >= 4:
        return "当前位置性价比尚可，但趋势确认度一般，持仓更适合边走边观察。"
    return "当前结构中性偏多，适合把明日价格行为作为是否继续持有的关键判断。"


def _build_watch_points(
    end_row: pd.Series,
    end_result: dict[str, Any],
    levels: dict[str, Any],
) -> tuple[list[str], list[str]]:
    supports = levels["supports"]
    resistances = levels["resistances"]
    vol_5d_avg = float(levels["vol_5d_avg"])
    vol_20d_avg = float(levels["vol_20d_avg"])
    today_return = float(levels["today_return"])

    close = float(end_row["close"])
    today_low = float(end_row["low"])
    today_high = float(end_row["high"])
    today_volume = float(end_row["volume"])
    ema20 = _safe_float(end_row.get("ema_fast"))

    primary_support_label, primary_support = supports[0] if supports else ("今日低点", today_low)
    secondary_support_label, secondary_support = supports[1] if len(supports) > 1 else (primary_support_label, primary_support)
    primary_resistance_label, primary_resistance = resistances[0] if resistances else ("今日高点", today_high)
    final_resistance_label, final_resistance = resistances[-1] if resistances else (primary_resistance_label, primary_resistance)

    hold_points = [
        (
            f"若明日回踩后仍能收在 `{primary_support_label} {_fmt_price(primary_support)}` 之上，"
            f"且成交量不显著高于 5 日均量 `{_fmt_num(vol_5d_avg, 0)}`，可继续持有。"
        ),
        (
            f"若明日有效站上 `{primary_resistance_label} {_fmt_price(primary_resistance)}`，"
            f"并且成交量至少接近或高于 5 日均量，可视为结构继续推进，继续持有。"
        ),
    ]
    if final_resistance > primary_resistance + 1e-6:
        hold_points.append(
            f"若盘中突破 `{final_resistance_label} {_fmt_price(final_resistance)}` 后收盘仍能站稳，"
            "说明短线压力被消化，持仓可以更偏趋势思路。"
        )
    else:
        hold_points.append(
            f"若明日收盘继续贴近当日高点，并维持强于 `{primary_support_label}` 的结构，可继续观察趋势延续。"
        )

    trim_points = [
        (
            f"若明日收盘跌破 `{primary_support_label} {_fmt_price(primary_support)}`，"
            "且量能明显放大，说明短线承接转弱，建议先减仓。"
        ),
        (
            f"若盘中冲高但始终站不上 `{primary_resistance_label} {_fmt_price(primary_resistance)}`，"
            "并回落收在今日收盘价下方，说明上方抛压偏重，也应考虑减仓。"
        ),
        (
            f"若出现单日大跌超过 `-2.5%` 且成交量高于 20 日均量 `{_fmt_num(vol_20d_avg, 0)}` 的放量阴线，"
            "更接近分歧释放，建议主动收缩仓位。"
        ),
    ]

    scores = end_result.get("scores", {})
    if int(scores.get("price_position") or 0) <= 3:
        trim_points[1] = (
            f"由于当前已接近压力区，若明日冲高后仍无法站稳 `{final_resistance_label} {_fmt_price(final_resistance)}`，"
            "并收出上影偏长的回落 K 线，建议先减仓。"
        )
    if int(scores.get("trend_structure") or 0) <= 2:
        hold_points[0] = (
            f"当前更偏反弹修复，若明日仍能守住 `{primary_support_label} {_fmt_price(primary_support)}`，"
            f"并且不跌破 `{secondary_support_label} {_fmt_price(secondary_support)}`，可继续持有观察。"
        )
        if ema20 is not None:
            trim_points.insert(
                1,
                f"若明日收盘重新跌回 `EMA20 {_fmt_price(ema20)}` 下方，同时量能放大，说明反弹延续失败，建议减仓。",
            )
    if today_return >= 0.03 and today_volume >= vol_5d_avg * 1.2:
        hold_points.append("今天属于偏强推进日，明日若只是缩量整理而不是放量转弱，通常仍可继续持有。")

    return hold_points, trim_points


def _render_markdown(
    *,
    code: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    holding_stats: dict[str, Any],
    start_result: dict[str, Any],
    end_result: dict[str, Any],
    start_row: pd.Series,
    end_row: pd.Series,
    b1_snapshot: dict[str, Any],
    levels: dict[str, Any],
) -> str:
    metric_table = _render_table(
        ["指标", "买入日", "结束日", "变化"],
        _metric_rows(start_row, end_row),
    )
    score_table = _render_table(
        ["评分项", "买入日", "结束日", "变化"],
        _score_rows(start_result, end_result),
    )
    b1_table = _render_table(
        ["项目", "结束日状态"],
        [
            ("J 值", _fmt_num(b1_snapshot["j_today"], 2)),
            ("历史 10% 分位", _fmt_num(b1_snapshot["j_q10"], 2)),
            ("KDJ 低位条件", _fmt_bool(b1_snapshot["kdj_ok"])),
            ("收盘价 > zxdkx", _fmt_bool(b1_snapshot["zx_ok"] and b1_snapshot["close"] > (b1_snapshot["zxdkx"] or float("inf")))),
            ("zxdq > zxdkx", _fmt_bool(b1_snapshot["zx_ok"] and (b1_snapshot["zxdq"] or 0.0) > (b1_snapshot["zxdkx"] or float("inf")))),
            ("周线多头排列", _fmt_bool(b1_snapshot["weekly_bull"])),
            ("20 日最大量非阴线", _fmt_bool(b1_snapshot["max_vol_ok"])),
            ("B1 当日是否触发", _fmt_bool(b1_snapshot["picked"])),
        ],
    )

    support_lines = [f"- `{label}`：`{_fmt_price(value)}`" for label, value in levels["supports"]]
    resistance_lines = [f"- `{label}`：`{_fmt_price(value)}`" for label, value in levels["resistances"]]
    hold_points, trim_points = _build_watch_points(end_row, end_result, levels)

    lines = [
        f"# {code} 持仓跟踪报告",
        "",
        f"- 买入日期：`{start_ts.strftime('%Y-%m-%d')}`",
        f"- 分析截止：`{end_ts.strftime('%Y-%m-%d')}`",
        f"- 买入价格：`{_fmt_price(holding_stats['buy_price'])}`",
        f"- 截止收盘：`{_fmt_price(holding_stats['end_price'])}`",
        f"- 持仓收益：`{_fmt_pct(holding_stats['total_return'])}`",
        f"- 持仓交易日：`{holding_stats['trading_days']}`",
        "",
        "## 持仓表现",
        "",
        f"- 持仓区间最高收盘收益：`{_fmt_pct(holding_stats['max_close_return'])}`（`{holding_stats['max_close_return_date']}`）",
        f"- 持仓区间最差盘中收益：`{_fmt_pct(holding_stats['worst_intraday_return'])}`（`{holding_stats['worst_intraday_return_date']}`）",
        f"- 持仓区间最大回撤：`{_fmt_pct(holding_stats['max_drawdown'])}`（`{holding_stats['max_drawdown_date']}`）",
        f"- 单日最佳涨幅：`{_fmt_pct(holding_stats['best_day_return'])}`（`{holding_stats['best_day_return_date']}`）",
        f"- 单日最差涨幅：`{_fmt_pct(holding_stats['worst_day_return'])}`（`{holding_stats['worst_day_return_date']}`）",
        f"- 区间平均成交量：`{_fmt_num(holding_stats['avg_volume'], 0)}`",
        f"- 区间平均振幅：`{_fmt_pct(holding_stats['avg_amplitude'])}`",
        "",
        "## 当前形态",
        "",
        f"- 当前总分：`{_fmt_num(end_result.get('total_score'), 1)}`，判定：`{end_result.get('verdict', '-')}`，信号：`{end_result.get('signal_type', '-')}`",
        f"- 形态判断：{_shape_summary(end_result)}",
        f"- 程序化解释：{end_result.get('comment', '-')}",
        f"- 趋势说明：{end_result.get('trend_reasoning', '-')}",
        f"- 位置说明：{end_result.get('position_reasoning', '-')}",
        f"- 量价说明：{end_result.get('volume_reasoning', '-')}",
        f"- 异动说明：{end_result.get('abnormal_move_reasoning', '-')}",
        "",
        "## 评分变化",
        "",
        score_table,
        "",
        "## 指标变化",
        "",
        metric_table,
        "",
        "## B1 触发快照",
        "",
        b1_table,
        "",
        "## 关键价位",
        "",
        "### 支撑位",
        *support_lines,
        "",
        "### 压力位",
        *resistance_lines,
        "",
        "## 明日观察点",
        "",
        "### 什么走势继续持有",
        *[f"- {item}" for item in hold_points],
        "",
        "### 什么走势该减仓",
        *[f"- {item}" for item in trim_points],
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def generate_report(
    *,
    code: str,
    start_date: str,
    end_date: str,
    quant_config_path: Path,
    preselect_config_path: Path,
) -> tuple[str, Path]:
    cfg = load_config(quant_config_path)
    cfg["prefilter"]["enabled"] = False
    raw_dir = Path(cfg["raw_dir"])
    df = _load_stock_df(code, raw_dir)
    frame = prepare_review_frame(df, cfg)

    start_row = _resolve_asof_row(frame, start_date)
    end_row = _resolve_asof_row(frame, end_date)
    start_ts = pd.Timestamp(start_row["date"])
    end_ts = pd.Timestamp(end_row["date"])
    if start_ts > end_ts:
        raise ValueError("起始日期晚于结束日期")

    holding_window = frame.loc[start_ts:end_ts].copy()
    buy_price = float(start_row["close"])
    holding_stats = _build_holding_stats(holding_window, buy_price)

    start_result = review_prepared_frame(frame, cfg, code=code, asof_date=start_ts.strftime("%Y-%m-%d"))
    end_result = review_prepared_frame(frame, cfg, code=code, asof_date=end_ts.strftime("%Y-%m-%d"))

    b1_cfg = _load_b1_config(preselect_config_path)
    b1_snapshot = _compute_b1_snapshot(frame[["date", "open", "high", "low", "close", "volume"]], end_ts, b1_cfg)
    levels = _support_resistance(frame, end_ts)

    markdown = _render_markdown(
        code=code,
        start_ts=start_ts,
        end_ts=end_ts,
        holding_stats=holding_stats,
        start_result=start_result,
        end_result=end_result,
        start_row=start_row,
        end_row=end_row,
        b1_snapshot=b1_snapshot,
        levels=levels,
    )

    out_dir = _ROOT / "data" / "review" / "holding_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{code}_{start_ts.strftime('%Y-%m-%d')}_{end_ts.strftime('%Y-%m-%d')}.md"
    return markdown, out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="按持仓视角生成单票 Markdown 报告")
    parser.add_argument("--code", required=True, help="6 位股票代码，例如 601975")
    parser.add_argument("--start-date", required=True, help="买入起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="分析结束日期，格式 YYYY-MM-DD")
    parser.add_argument(
        "--quant-config",
        default=str(_DEFAULT_QUANT_CONFIG),
        help="quant 评分配置文件路径",
    )
    parser.add_argument(
        "--preselect-config",
        default=str(_DEFAULT_PRESELECT_CONFIG),
        help="第 2 步初选配置文件路径",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="输出 Markdown 文件路径；默认写入 data/review/holding_reports/",
    )
    parser.add_argument(
        "--stdout-only",
        action="store_true",
        help="仅打印到标准输出，不写文件",
    )
    args = parser.parse_args()

    code = str(args.code).zfill(6)
    markdown, default_out = generate_report(
        code=code,
        start_date=args.start_date,
        end_date=args.end_date,
        quant_config_path=Path(args.quant_config),
        preselect_config_path=Path(args.preselect_config),
    )

    if not args.stdout_only:
        out_path = Path(args.output) if args.output else default_out
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown, encoding="utf-8")
        print(f"[INFO] 已写入：{out_path}")

    print(markdown)


if __name__ == "__main__":
    main()
