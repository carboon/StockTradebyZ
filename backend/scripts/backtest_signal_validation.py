"""回测验证脚本。

验证以下场景在信号日后的收益表现：

1. 单股诊断历史：B1=是，且 signal_type != trend_start
2. 单股诊断历史：B1=否，且 signal_type == trend_start
3. 单股诊断历史：B1=是，且 signal_type == trend_start，且 tomorrow_star_pass=True
4. 当前热盘：当日全部股票（通常 78 只）按相同口径统计

统一口径：
- 触发条件发生在 trade_date / check_date / pick_date 当天
- 买入点：下一个交易日开盘价
- 卖出点：买入后的第 5 / 10 个交易日收盘价
- 收益率：sell_close / next_open - 1

输出：
- data/backtest/signal_validation/summary_*.json
- data/backtest/signal_validation/details_*.csv

用法：
    .venv/bin/python backend/scripts/backtest_signal_validation.py
    .venv/bin/python backend/scripts/backtest_signal_validation.py --start-date 2025-01-01 --end-date 2025-12-31
    .venv/bin/python backend/scripts/backtest_signal_validation.py --reviewer quant
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"

import sys

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal
from app.models import (  # noqa: E402
    CurrentHotAnalysisResult,
    CurrentHotCandidate,
    DailyB1Check,
    DailyB1CheckDetail,
    StockDaily,
)


OUTPUT_DIR = ROOT / "data" / "backtest" / "signal_validation"
HORIZONS = (5, 10)
DEFAULT_REVIEWER = "quant"
TREND_START = "trend_start"


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    source: str


@dataclass(frozen=True)
class PriceBar:
    trade_date: date
    open: float
    close: float


SCENARIOS = (
    Scenario(
        key="history_b1_yes_non_trend_start",
        label='单股诊断：B1=是，且信号类型!=趋势启动',
        source="daily_b1_history",
    ),
    Scenario(
        key="history_b1_no_trend_start",
        label='单股诊断：B1=否，且信号类型=趋势启动',
        source="daily_b1_history",
    ),
    Scenario(
        key="history_b1_yes_trend_start_tomorrow_star",
        label='单股诊断：B1=是，且信号类型=趋势启动，且为明日之星',
        source="daily_b1_history",
    ),
    Scenario(
        key="current_hot_all",
        label="当前热盘：当日全部股票",
        source="current_hot",
    ),
    Scenario(
        key="current_hot_b1_yes_non_trend_start",
        label='当前热盘：B1=是，且信号类型!=趋势启动',
        source="current_hot",
    ),
    Scenario(
        key="current_hot_b1_no_trend_start",
        label='当前热盘：B1=否，且信号类型=趋势启动',
        source="current_hot",
    ),
    Scenario(
        key="current_hot_b1_yes_trend_start",
        label='当前热盘：B1=是，且信号类型=趋势启动',
        source="current_hot",
    ),
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _normalize_signal_type(value: Any) -> str:
    text = str(value or "").strip()
    return text if text else "unknown"


def _extract_detail_flag(detail: DailyB1CheckDetail | None, key: str) -> bool | None:
    if detail is None or not isinstance(detail.rules_json, dict):
        return None
    return _as_bool(detail.rules_json.get(key))


def _extract_detail_signal_type(detail: DailyB1CheckDetail | None) -> str:
    if detail is None or not isinstance(detail.score_details_json, dict):
        return "unknown"
    return _normalize_signal_type(detail.score_details_json.get("signal_type"))


def _extract_return_rows(
    *,
    code_to_rows: dict[str, list[PriceBar]],
    code: str,
    trade_date: date,
) -> dict[str, Any] | None:
    rows = code_to_rows.get(code)
    if not rows:
        return None

    index = None
    for i, row in enumerate(rows):
        if row.trade_date == trade_date:
            index = i
            break
    if index is None:
        return None

    entry_index = index + 1
    if entry_index >= len(rows):
        return None

    entry_row = rows[entry_index]
    entry_open = float(entry_row.open)
    if entry_open <= 0:
        return None

    result: dict[str, Any] = {
        "entry_date": entry_row.trade_date.isoformat(),
        "entry_open": entry_open,
    }
    for horizon in HORIZONS:
        sell_index = index + horizon
        if sell_index >= len(rows):
            result[f"ret_{horizon}d"] = None
            result[f"sell_date_{horizon}d"] = None
            result[f"sell_close_{horizon}d"] = None
            result[f"complete_{horizon}d"] = False
            continue
        sell_row = rows[sell_index]
        sell_close = float(sell_row.close)
        result[f"ret_{horizon}d"] = sell_close / entry_open - 1.0
        result[f"sell_date_{horizon}d"] = sell_row.trade_date.isoformat()
        result[f"sell_close_{horizon}d"] = sell_close
        result[f"complete_{horizon}d"] = True
    return result


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _summarize_metric(values: list[float | None]) -> dict[str, Any]:
    valid = [float(v) for v in values if v is not None]
    if not valid:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "win_rate": None,
            "min": None,
            "max": None,
        }

    ordered = sorted(valid)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 == 1 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0
    return {
        "count": n,
        "mean": _round_or_none(sum(ordered) / n),
        "median": _round_or_none(median),
        "win_rate": _round_or_none(sum(1 for v in ordered if v > 0) / n),
        "min": _round_or_none(ordered[0]),
        "max": _round_or_none(ordered[-1]),
    }


def _load_price_rows_from_csv(code: str, *, min_date: date | None) -> list[PriceBar]:
    csv_path = ROOT / "data" / "raw" / f"{code}.csv"
    if not csv_path.exists():
        return []
    frame = pd.read_csv(csv_path)
    frame.columns = [str(col).lower() for col in frame.columns]
    required = {"date", "open", "close"}
    if not required.issubset(frame.columns):
        return []
    frame = frame[["date", "open", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.date
    frame["open"] = pd.to_numeric(frame["open"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "open", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    if min_date is not None:
        frame = frame[frame["date"] >= min_date]
    return [
        PriceBar(
            trade_date=row["date"],
            open=float(row["open"]),
            close=float(row["close"]),
        )
        for _, row in frame.iterrows()
    ]


def load_price_rows(codes: set[str], min_date: date | None, max_date: date | None) -> dict[str, list[PriceBar]]:
    if not codes:
        return {}

    with SessionLocal() as db:
        query = db.query(StockDaily).filter(StockDaily.code.in_(sorted(codes)))
        if min_date is not None:
            query = query.filter(StockDaily.trade_date >= min_date)
        if max_date is not None:
            query = query.filter(StockDaily.trade_date <= max_date)
        rows = query.order_by(StockDaily.code.asc(), StockDaily.trade_date.asc(), StockDaily.id.asc()).all()

    grouped: dict[str, list[PriceBar]] = {}
    for row in rows:
        grouped.setdefault(row.code, []).append(
            PriceBar(
                trade_date=row.trade_date,
                open=float(row.open),
                close=float(row.close),
            )
        )
    for code in codes:
        if code not in grouped:
            fallback = _load_price_rows_from_csv(code, min_date=min_date)
            if fallback:
                grouped[code] = fallback
    return grouped


def load_history_events(
    *,
    start_date: date | None,
    end_date: date | None,
) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = (
            db.query(DailyB1Check, DailyB1CheckDetail)
            .outerjoin(
                DailyB1CheckDetail,
                and_(
                    DailyB1CheckDetail.code == DailyB1Check.code,
                    DailyB1CheckDetail.check_date == DailyB1Check.check_date,
                ),
            )
        )
        if start_date is not None:
            query = query.filter(DailyB1Check.check_date >= start_date)
        if end_date is not None:
            query = query.filter(DailyB1Check.check_date <= end_date)
        rows = query.order_by(DailyB1Check.check_date.asc(), DailyB1Check.code.asc()).all()

    events: list[dict[str, Any]] = []
    for check, detail in rows:
        signal_type = _extract_detail_signal_type(detail)
        tomorrow_star_pass = _extract_detail_flag(detail, "tomorrow_star_pass")
        events.append(
            {
                "source": "daily_b1_history",
                "trade_date": check.check_date,
                "code": check.code,
                "b1_passed": _as_bool(check.b1_passed),
                "signal_type": signal_type,
                "tomorrow_star_pass": tomorrow_star_pass,
                "scenario_keys": _match_history_scenarios(
                    b1_passed=_as_bool(check.b1_passed),
                    signal_type=signal_type,
                    tomorrow_star_pass=tomorrow_star_pass,
                ),
            }
        )
    return events


def _match_history_scenarios(
    *,
    b1_passed: bool | None,
    signal_type: str,
    tomorrow_star_pass: bool | None,
) -> list[str]:
    matches: list[str] = []
    if b1_passed is True and signal_type != TREND_START:
        matches.append("history_b1_yes_non_trend_start")
    if b1_passed is False and signal_type == TREND_START:
        matches.append("history_b1_no_trend_start")
    if b1_passed is True and signal_type == TREND_START and tomorrow_star_pass is True:
        matches.append("history_b1_yes_trend_start_tomorrow_star")
    return matches


def load_current_hot_events(
    *,
    start_date: date | None,
    end_date: date | None,
    reviewer: str,
) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        query = (
            db.query(CurrentHotCandidate, CurrentHotAnalysisResult)
            .outerjoin(
                CurrentHotAnalysisResult,
                and_(
                    CurrentHotAnalysisResult.pick_date == CurrentHotCandidate.pick_date,
                    CurrentHotAnalysisResult.code == CurrentHotCandidate.code,
                    CurrentHotAnalysisResult.reviewer == reviewer,
                ),
            )
        )
        if start_date is not None:
            query = query.filter(CurrentHotCandidate.pick_date >= start_date)
        if end_date is not None:
            query = query.filter(CurrentHotCandidate.pick_date <= end_date)
        rows = query.order_by(CurrentHotCandidate.pick_date.asc(), CurrentHotCandidate.code.asc()).all()

    events: list[dict[str, Any]] = []
    for candidate, analysis in rows:
        signal_type = _normalize_signal_type(analysis.signal_type if analysis else None)
        events.append(
            {
                "source": "current_hot",
                "trade_date": candidate.pick_date,
                "code": candidate.code,
                "b1_passed": _as_bool(candidate.b1_passed),
                "signal_type": signal_type,
                "tomorrow_star_pass": None,
                "scenario_keys": _match_current_hot_scenarios(
                    b1_passed=_as_bool(candidate.b1_passed),
                    signal_type=signal_type,
                ),
            }
        )
    return events


def _match_current_hot_scenarios(
    *,
    b1_passed: bool | None,
    signal_type: str,
) -> list[str]:
    matches = ["current_hot_all"]
    if b1_passed is True and signal_type != TREND_START:
        matches.append("current_hot_b1_yes_non_trend_start")
    if b1_passed is False and signal_type == TREND_START:
        matches.append("current_hot_b1_no_trend_start")
    if b1_passed is True and signal_type == TREND_START:
        matches.append("current_hot_b1_yes_trend_start")
    return matches


def enrich_events_with_returns(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not events:
        return []

    codes = {str(event["code"]) for event in events}
    min_date = min(event["trade_date"] for event in events)
    max_date = max(event["trade_date"] for event in events)
    price_rows = load_price_rows(codes, min_date=min_date, max_date=None if max_date is None else max_date)

    enriched: list[dict[str, Any]] = []
    for event in events:
        metrics = _extract_return_rows(
            code_to_rows=price_rows,
            code=str(event["code"]),
            trade_date=event["trade_date"],
        )
        if metrics is None:
            continue
        enriched.append(
            {
                **event,
                "trade_date": event["trade_date"].isoformat(),
                **metrics,
            }
        )
    return enriched


def build_summary(detail_rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scenarios": {},
    }
    for scenario in SCENARIOS:
        scenario_rows = [row for row in detail_rows if scenario.key in row["scenario_keys"]]
        scenario_summary: dict[str, Any] = {
            "label": scenario.label,
            "source": scenario.source,
            "sample_count": len(scenario_rows),
            "horizons": {},
            "daily_equal_weight": {},
        }
        for horizon in HORIZONS:
            values = [row.get(f"ret_{horizon}d") for row in scenario_rows if row.get(f"complete_{horizon}d") is True]
            scenario_summary["horizons"][f"{horizon}d"] = _summarize_metric(values)
            daily_bucket: dict[str, list[float]] = {}
            for row in scenario_rows:
                if row.get(f"complete_{horizon}d") is not True:
                    continue
                value = row.get(f"ret_{horizon}d")
                if value is None:
                    continue
                daily_bucket.setdefault(str(row["trade_date"]), []).append(float(value))
            daily_means = [
                sum(day_values) / len(day_values)
                for day_values in daily_bucket.values()
                if day_values
            ]
            scenario_summary["daily_equal_weight"][f"{horizon}d"] = _summarize_metric(daily_means)
        summary["scenarios"][scenario.key] = scenario_summary
    return summary


def write_detail_csv(path: Path, detail_rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "source",
        "trade_date",
        "code",
        "b1_passed",
        "signal_type",
        "tomorrow_star_pass",
        "scenario_keys",
        "entry_date",
        "entry_open",
        "ret_5d",
        "sell_date_5d",
        "sell_close_5d",
        "complete_5d",
        "ret_10d",
        "sell_date_10d",
        "sell_close_10d",
        "complete_10d",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in detail_rows:
            payload = {key: row.get(key) for key in fieldnames}
            payload["scenario_keys"] = "|".join(row.get("scenario_keys", []))
            writer.writerow(payload)


def write_summary_json(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def print_summary(summary: dict[str, Any]) -> None:
    print("")
    print("回测验证结果")
    print("=" * 80)
    for scenario in SCENARIOS:
        item = summary["scenarios"][scenario.key]
        print(f"{scenario.label}")
        print(f"  样本数: {item['sample_count']}")
        for horizon in HORIZONS:
            metric = item["horizons"][f"{horizon}d"]
            mean = metric["mean"]
            median = metric["median"]
            win_rate = metric["win_rate"]
            basket = item["daily_equal_weight"][f"{horizon}d"]
            print(
                f"  {horizon}日: count={metric['count']} "
                f"mean={mean} median={median} win_rate={win_rate}"
            )
            print(
                f"  {horizon}日等权按日篮子: count={basket['count']} "
                f"mean={basket['mean']} median={basket['median']} win_rate={basket['win_rate']}"
            )
        print("-" * 80)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 B1 / 趋势启动 / 明日之星 / 当前热盘的后续收益率")
    parser.add_argument("--start-date", help="起始日期，格式 YYYY-MM-DD")
    parser.add_argument("--end-date", help="结束日期，格式 YYYY-MM-DD")
    parser.add_argument("--reviewer", default=DEFAULT_REVIEWER, help="当前热盘分析使用的 reviewer，默认 quant")
    parser.add_argument(
        "--output-prefix",
        default=datetime.now().strftime("%Y%m%d_%H%M%S"),
        help="输出文件前缀，默认当前时间戳",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_date = _parse_date(args.start_date)
    end_date = _parse_date(args.end_date)

    history_events = load_history_events(start_date=start_date, end_date=end_date)
    current_hot_events = load_current_hot_events(
        start_date=start_date,
        end_date=end_date,
        reviewer=args.reviewer,
    )

    all_events = history_events + current_hot_events
    detail_rows = enrich_events_with_returns(all_events)
    summary = build_summary(detail_rows)

    prefix = args.output_prefix
    summary_path = OUTPUT_DIR / f"summary_{prefix}.json"
    detail_path = OUTPUT_DIR / f"details_{prefix}.csv"
    write_summary_json(summary_path, summary)
    write_detail_csv(detail_path, detail_rows)

    print_summary(summary)
    print(f"summary: {summary_path}")
    print(f"details: {detail_path}")


if __name__ == "__main__":
    main()
