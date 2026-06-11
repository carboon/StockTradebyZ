#!/usr/bin/env python3
"""尾盘筛选历史回测脚本。

口径：
- 使用 stock_daily 当日收盘价代替尾盘价。
- 涨幅、量比、换手率、流通市值均使用当日 stock_daily 数据；缺失则跳过，不回退。
- 历史日线没有分时数据，因此分时强势条件不参与历史回测评分。
- “连续三天收益率高于 3%”按持仓满 3 个交易日且累计收益率 >= 3% 处理。
- A 股按 100 股一手买卖，单票买入金额不超过 30000 元。

用法：
    PYTHONPATH=backend .venv/bin/python backend/scripts/late_session_backtest.py
    PYTHONPATH=backend .venv/bin/python backend/scripts/late_session_backtest.py --days 180 --end-date 2026-06-08
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
for path in (ROOT, BACKEND):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from app.database import SessionLocal  # noqa: E402
from app.models import Stock, StockDaily  # noqa: E402


CHANGE_MIN = 3.0
CHANGE_MAX = 5.0
VOLUME_RATIO_MIN = 1.0
TURNOVER_MIN = 5.0
TURNOVER_MAX = 10.0
CIRC_MV_MIN_YUAN = 5_000_000_000.0
CIRC_MV_MAX_YUAN = 20_000_000_000.0
DEFAULT_OUTPUT_DIR = ROOT / "data" / "backtest" / "late_session"


@dataclass(frozen=True)
class DailyBar:
    code: str
    name: str | None
    industry: str | None
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover_rate: float | None
    volume_ratio: float | None
    circ_mv: float | None


@dataclass
class Candidate:
    code: str
    name: str | None
    industry: str | None
    trade_date: date
    close: float
    change_pct: float
    volume_ratio: float
    turnover_rate: float
    circ_mv_yuan: float
    volume_pattern: str
    ma_pattern: str
    final_score: float


@dataclass
class Position:
    code: str
    name: str | None
    entry_date: date
    entry_price: float
    shares: int
    cost: float
    profit_tier_count: int = 0
    last_price: float | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按尾盘筛选逻辑做历史回测")
    parser.add_argument("--days", type=int, default=180, help="回测最近多少个交易日，默认 180")
    parser.add_argument("--end-date", default="", help="回测截止交易日 YYYY-MM-DD，默认数据库最新交易日")
    parser.add_argument("--capital", type=float, default=200_000.0, help="初始本金，默认 200000 元")
    parser.add_argument("--per-stock", type=float, default=30_000.0, help="单票买入上限，默认 30000 元")
    parser.add_argument("--top-n", type=int, default=2, help="每日最多买入候选数量，默认 2")
    parser.add_argument("--max-holdings", type=int, default=8, help="最大同时持仓股票数，默认 8")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    return parser.parse_args()


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def normalize_circ_mv_to_yuan(value: float | None) -> float | None:
    """兼容 Tushare daily_basic 的 circ_mv 万元单位和实时行情的元单位。"""
    if value is None or value <= 0:
        return None
    return value * 10_000.0 if value < 100_000_000.0 else value


def round2(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def get_trade_dates(db, *, days: int, end_date: date | None) -> tuple[list[date], list[date]]:
    latest_date = end_date or db.query(func.max(StockDaily.trade_date)).scalar()
    if latest_date is None:
        raise RuntimeError("stock_daily 中没有交易日数据")
    if isinstance(latest_date, datetime):
        latest_date = latest_date.date()

    rows = (
        db.query(StockDaily.trade_date)
        .filter(StockDaily.trade_date <= latest_date)
        .distinct()
        .order_by(StockDaily.trade_date.desc())
        .limit(days + 90)
        .all()
    )
    full_dates = sorted(row[0] for row in rows)
    if len(full_dates) < min(days, 1) + 60:
        raise RuntimeError(f"交易日数据不足：需要至少 {min(days, 1) + 60} 个，实际 {len(full_dates)} 个")
    backtest_dates = full_dates[-days:]
    return full_dates, backtest_dates


def load_bars(db, trade_dates: list[date]) -> tuple[dict[date, dict[str, DailyBar]], dict[str, list[DailyBar]]]:
    rows = (
        db.query(StockDaily, Stock)
        .join(Stock, Stock.code == StockDaily.code)
        .filter(StockDaily.trade_date.in_(trade_dates))
        .order_by(StockDaily.code.asc(), StockDaily.trade_date.asc())
        .all()
    )
    bars_by_date: dict[date, dict[str, DailyBar]] = defaultdict(dict)
    history_by_code: dict[str, list[DailyBar]] = defaultdict(list)
    for daily, stock in rows:
        code = str(daily.code).zfill(6)
        bar = DailyBar(
            code=code,
            name=stock.name,
            industry=stock.industry,
            trade_date=daily.trade_date,
            open=float(daily.open),
            high=float(daily.high),
            low=float(daily.low),
            close=float(daily.close),
            volume=float(daily.volume),
            turnover_rate=to_float(daily.turnover_rate),
            volume_ratio=to_float(daily.volume_ratio),
            circ_mv=to_float(daily.circ_mv),
        )
        bars_by_date[bar.trade_date][code] = bar
        history_by_code[code].append(bar)
    return dict(bars_by_date), dict(history_by_code)


def score_volume_pattern(history: list[DailyBar]) -> tuple[str, float]:
    if len(history) < 6:
        return "unknown", 0.0
    volumes = [bar.volume for bar in history[-6:] if bar.volume is not None]
    if len(volumes) < 6:
        return "unknown", 0.0
    prev3 = volumes[:3]
    last3 = volumes[-3:]
    if last3[0] <= last3[1] <= last3[2] and sum(last3) / 3 > sum(prev3) / 3:
        return "step_up", 15.0
    if sum(last3) / 3 > sum(prev3) / 3 * 1.15 and max(last3) / max(min(last3), 1.0) <= 1.8:
        return "expanding", 12.0
    return "unstable", 3.0


def score_ma_pattern(history: list[DailyBar], latest_price: float) -> tuple[str, float]:
    if len(history) < 60 or latest_price <= 0:
        return "unknown", 0.0
    closes = [float(bar.close) for bar in history]
    if len(closes) < 60:
        return "unknown", 0.0
    closes[-1] = latest_price
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    ma60_prev = sum(closes[-61:-1]) / 60 if len(closes) >= 61 else ma60
    if latest_price >= max(ma5, ma10, ma20, ma60) and ma5 >= ma10 >= ma20 and ma60 >= ma60_prev:
        return "bullish_alignment", 20.0
    if latest_price >= ma5 and latest_price >= ma10 and ma5 >= ma20:
        return "short_bullish", 14.0
    if latest_price < ma20 or latest_price < ma60:
        return "below_key_ma", 0.0
    return "neutral", 8.0


def generate_candidates_for_date(
    trade_date: date,
    *,
    bars_by_date: dict[date, dict[str, DailyBar]],
    history_by_code: dict[str, list[DailyBar]],
) -> list[Candidate]:
    today_bars = bars_by_date.get(trade_date, {})
    candidates: list[Candidate] = []
    for code, bar in today_bars.items():
        full_history = history_by_code.get(code, [])
        index = next((i for i, item in enumerate(full_history) if item.trade_date == trade_date), None)
        if index is None or index < 1:
            continue
        history = full_history[: index + 1]
        prev_close = full_history[index - 1].close
        if prev_close <= 0 or bar.close <= 0:
            continue
        change_pct = (bar.close / prev_close - 1.0) * 100.0
        volume_ratio = bar.volume_ratio
        turnover_rate = bar.turnover_rate
        circ_mv_yuan = normalize_circ_mv_to_yuan(bar.circ_mv)
        if volume_ratio is None or turnover_rate is None or circ_mv_yuan is None:
            continue
        if not (CHANGE_MIN <= change_pct <= CHANGE_MAX):
            continue
        if volume_ratio < VOLUME_RATIO_MIN:
            continue
        if not (TURNOVER_MIN <= turnover_rate <= TURNOVER_MAX):
            continue
        if not (CIRC_MV_MIN_YUAN <= circ_mv_yuan <= CIRC_MV_MAX_YUAN):
            continue

        volume_pattern, volume_score = score_volume_pattern(history)
        ma_pattern, ma_score = score_ma_pattern(history, bar.close)
        final_score = 50.0 + volume_score + ma_score
        if final_score < 70.0 or volume_score < 8.0 or ma_score < 8.0:
            continue
        candidates.append(
            Candidate(
                code=code,
                name=bar.name,
                industry=bar.industry,
                trade_date=trade_date,
                close=bar.close,
                change_pct=change_pct,
                volume_ratio=volume_ratio,
                turnover_rate=turnover_rate,
                circ_mv_yuan=circ_mv_yuan,
                volume_pattern=volume_pattern,
                ma_pattern=ma_pattern,
                final_score=final_score,
            )
        )
    return sorted(
        candidates,
        key=lambda item: (-item.final_score, -item.change_pct, -item.volume_ratio, item.code),
    )


def holding_days(position: Position, trade_date: date, backtest_dates: list[date]) -> int:
    try:
        entry_index = backtest_dates.index(position.entry_date)
        current_index = backtest_dates.index(trade_date)
    except ValueError:
        return 0
    return max(0, current_index - entry_index)


def position_return(position: Position, price: float) -> float:
    return price / position.entry_price - 1.0


def sell_shares(
    *,
    position: Position,
    shares: int,
    price: float,
    trade_date: date,
    reason: str,
    cash: float,
    trades: list[dict[str, Any]],
) -> float:
    shares = min(shares, position.shares)
    if shares <= 0:
        return cash
    amount = shares * price
    cost_part = position.cost * shares / position.shares
    pnl = amount - cost_part
    position.shares -= shares
    position.cost -= cost_part
    position.last_price = price
    trades.append(
        {
            "trade_date": trade_date.isoformat(),
            "side": "SELL",
            "code": position.code,
            "name": position.name,
            "price": round2(price),
            "shares": shares,
            "amount": round2(amount),
            "pnl": round2(pnl),
            "return_pct": round2(position_return(position, price) * 100.0),
            "reason": reason,
        }
    )
    return cash + amount


def choose_forced_liquidation(
    positions: dict[str, Position],
    price_map: dict[str, DailyBar],
) -> tuple[str, float] | None:
    choices: list[tuple[float, str, float]] = []
    for code, position in positions.items():
        bar = price_map.get(code)
        price = bar.close if bar is not None else position.last_price
        if price is None or price <= 0:
            continue
        choices.append((position_return(position, price), code, price))
    if not choices:
        return None
    _, code, price = min(choices, key=lambda item: (item[0], item[1]))
    return code, price


def run_backtest(
    *,
    bars_by_date: dict[date, dict[str, DailyBar]],
    history_by_code: dict[str, list[DailyBar]],
    backtest_dates: list[date],
    initial_capital: float,
    per_stock: float,
    top_n: int,
    max_holdings: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cash = initial_capital
    positions: dict[str, Position] = {}
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []

    for trade_date in backtest_dates:
        price_map = bars_by_date.get(trade_date, {})

        for code in list(positions.keys()):
            position = positions[code]
            bar = price_map.get(code)
            price = bar.close if bar is not None else None
            if price is None or price <= 0:
                continue
            position.last_price = price
            ret = position_return(position, price)
            days_held = holding_days(position, trade_date, backtest_dates)
            reason = ""
            sell_all = False
            partial_shares = 0

            if days_held == 1 and ret <= -0.03:
                reason = "next_day_stop_-3"
                sell_all = True
            elif ret <= -0.05:
                reason = "stop_loss_-5"
                sell_all = True
            elif ret >= (position.profit_tier_count + 1) * 0.10:
                if position.profit_tier_count >= 2:
                    reason = "third_profit_tier_+30"
                    sell_all = True
                else:
                    reason = f"profit_tier_{position.profit_tier_count + 1}"
                    partial_shares = (position.shares // 2 // 100) * 100
                    if partial_shares < 100:
                        sell_all = True
            elif days_held >= 3 and ret >= 0.03:
                reason = "three_day_take_profit_+3"
                sell_all = True

            if sell_all:
                cash = sell_shares(
                    position=position,
                    shares=position.shares,
                    price=price,
                    trade_date=trade_date,
                    reason=reason,
                    cash=cash,
                    trades=trades,
                )
                positions.pop(code, None)
            elif partial_shares > 0:
                cash = sell_shares(
                    position=position,
                    shares=partial_shares,
                    price=price,
                    trade_date=trade_date,
                    reason=reason,
                    cash=cash,
                    trades=trades,
                )
                position.profit_tier_count += 1

        daily_candidates = generate_candidates_for_date(
            trade_date,
            bars_by_date=bars_by_date,
            history_by_code=history_by_code,
        )
        for rank, candidate in enumerate(daily_candidates, start=1):
            candidate_rows.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "rank": rank,
                    "code": candidate.code,
                    "name": candidate.name,
                    "industry": candidate.industry,
                    "close": round2(candidate.close),
                    "change_pct": round2(candidate.change_pct),
                    "volume_ratio": round2(candidate.volume_ratio),
                    "turnover_rate": round2(candidate.turnover_rate),
                    "circ_mv_yi": round2(candidate.circ_mv_yuan / 100_000_000.0),
                    "volume_pattern": candidate.volume_pattern,
                    "ma_pattern": candidate.ma_pattern,
                    "final_score": round2(candidate.final_score),
                }
            )

        for candidate in daily_candidates[:top_n]:
            if candidate.code in positions:
                continue
            while (len(positions) >= max_holdings or cash < per_stock) and positions:
                liquidation = choose_forced_liquidation(positions, price_map)
                if liquidation is None:
                    break
                liquidate_code, price = liquidation
                position = positions[liquidate_code]
                cash = sell_shares(
                    position=position,
                    shares=position.shares,
                    price=price,
                    trade_date=trade_date,
                    reason="forced_liquidation_for_new_buy",
                    cash=cash,
                    trades=trades,
                )
                positions.pop(liquidate_code, None)

            buy_budget = min(per_stock, cash)
            shares = int(buy_budget // candidate.close // 100 * 100)
            if shares <= 0:
                continue
            amount = shares * candidate.close
            cash -= amount
            positions[candidate.code] = Position(
                code=candidate.code,
                name=candidate.name,
                entry_date=trade_date,
                entry_price=candidate.close,
                shares=shares,
                cost=amount,
                last_price=candidate.close,
            )
            trades.append(
                {
                    "trade_date": trade_date.isoformat(),
                    "side": "BUY",
                    "code": candidate.code,
                    "name": candidate.name,
                    "price": round2(candidate.close),
                    "shares": shares,
                    "amount": round2(amount),
                    "pnl": None,
                    "return_pct": None,
                    "reason": "late_session_top_candidate",
                }
            )

        market_value = 0.0
        for code, position in positions.items():
            bar = price_map.get(code)
            price = bar.close if bar is not None else position.last_price
            if price is not None:
                position.last_price = price
                market_value += position.shares * price
        equity = cash + market_value
        equity_curve.append(
            {
                "trade_date": trade_date.isoformat(),
                "cash": round2(cash),
                "market_value": round2(market_value),
                "equity": round2(equity),
                "holding_count": len(positions),
                "candidate_count": len(daily_candidates),
            }
        )

    final_equity = equity_curve[-1]["equity"] if equity_curve else initial_capital
    max_drawdown = calc_max_drawdown([float(row["equity"]) for row in equity_curve])
    sell_events = [row for row in trades if row["side"] == "SELL"]
    wins = [row for row in sell_events if (row.get("pnl") or 0) > 0]
    open_market_value = sum(position.shares * (position.last_price or position.entry_price) for position in positions.values())
    open_cost = sum(position.cost for position in positions.values())
    summary = {
        "start_date": backtest_dates[0].isoformat() if backtest_dates else None,
        "end_date": backtest_dates[-1].isoformat() if backtest_dates else None,
        "initial_capital": round2(initial_capital),
        "final_equity": round2(float(final_equity)),
        "total_return_pct": round2((float(final_equity) / initial_capital - 1.0) * 100.0),
        "max_drawdown_pct": round2(max_drawdown * 100.0),
        "cash": round2(cash),
        "open_market_value": round2(open_market_value),
        "open_unrealized_pnl": round2(open_market_value - open_cost),
        "open_position_count": len(positions),
        "trade_count": len(trades),
        "buy_count": sum(1 for row in trades if row["side"] == "BUY"),
        "sell_count": len(sell_events),
        "sell_win_rate_pct": round2(len(wins) / len(sell_events) * 100.0) if sell_events else None,
        "candidate_days": sum(1 for row in equity_curve if row["candidate_count"] > 0),
        "candidate_count": len(candidate_rows),
    }
    return summary, trades, equity_curve, candidate_rows


def calc_max_drawdown(equities: list[float]) -> float:
    peak = None
    max_dd = 0.0
    for equity in equities:
        if peak is None or equity > peak:
            peak = equity
        if peak and peak > 0:
            max_dd = max(max_dd, 1.0 - equity / peak)
    return max_dd


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        full_dates, backtest_dates = get_trade_dates(db, days=args.days, end_date=parse_date(args.end_date))
        bars_by_date, history_by_code = load_bars(db, full_dates)
        summary, trades, equity_curve, candidate_rows = run_backtest(
            bars_by_date=bars_by_date,
            history_by_code=history_by_code,
            backtest_dates=backtest_dates,
            initial_capital=args.capital,
            per_stock=args.per_stock,
            top_n=args.top_n,
            max_holdings=args.max_holdings,
        )
    finally:
        db.close()

    summary_path = output_dir / "late_session_backtest_summary.json"
    trades_path = output_dir / "late_session_backtest_trades.csv"
    equity_path = output_dir / "late_session_backtest_equity.csv"
    candidates_path = output_dir / "late_session_backtest_candidates.csv"

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(trades_path, trades)
    write_csv(equity_path, equity_curve)
    write_csv(candidates_path, candidate_rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary: {summary_path}")
    print(f"trades: {trades_path}")
    print(f"equity: {equity_path}")
    print(f"candidates: {candidates_path}")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
