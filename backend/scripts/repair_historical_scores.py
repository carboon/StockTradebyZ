#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

if (
    os.environ.get("STOCKTRADE_REPAIR_BOOTSTRAPPED") != "1"
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
):
    env = dict(os.environ)
    env["STOCKTRADE_REPAIR_BOOTSTRAPPED"] = "1"
    os.execve(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]], env)

pythonpath_entries = [entry for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep) if entry]
for required_path in (str(ROOT), str(BACKEND)):
    if required_path not in pythonpath_entries:
        pythonpath_entries.append(required_path)
    if required_path not in sys.path:
        sys.path.insert(0, required_path)
if pythonpath_entries:
    os.environ["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

from app.database import SessionLocal
from app.models import (
    AnalysisResult,
    Candidate,
    CurrentHotAnalysisResult,
    CurrentHotCandidate,
    CurrentHotRun,
    StockDaily,
    TomorrowStarRun,
)
from app.services.current_hot_service import CurrentHotService
from app.services.tomorrow_star_window_service import TomorrowStarWindowService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="修复历史评分/结果数据")
    parser.add_argument(
        "--scope",
        choices=("tomorrow-star", "current-hot", "both"),
        default="both",
        help="修复范围，默认 both",
    )
    parser.add_argument("--start-date", default=None, help="起始日期 YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--dates",
        nargs="*",
        default=None,
        help="直接指定日期列表，空格分隔；若提供则优先于区间。若不提供任何日期参数，则自动扫描最近窗口内的不合规数据。",
    )
    parser.add_argument("--reviewer", default="quant", help="reviewer，默认 quant")
    parser.add_argument(
        "--window-size",
        type=int,
        default=180,
        help="自动扫描最近交易日窗口，同时作为明日之星重建窗口大小，默认 180",
    )
    return parser.parse_args()


def normalize_dates(raw_dates: Iterable[str]) -> list[str]:
    normalized = sorted({date.fromisoformat(str(value).strip()).isoformat() for value in raw_dates if str(value).strip()})
    if not normalized:
        raise ValueError("未提供有效日期")
    return normalized


def get_recent_trade_dates(window_size: int) -> list[str]:
    with SessionLocal() as db:
        rows = (
            db.query(StockDaily.trade_date)
            .distinct()
            .order_by(StockDaily.trade_date.desc())
            .limit(window_size)
            .all()
        )
    return sorted([trade_date.isoformat() for trade_date, in rows if trade_date])


def resolve_manual_trade_dates(args: argparse.Namespace) -> list[str] | None:
    if args.dates:
        return normalize_dates(args.dates)
    if not args.start_date and not args.end_date:
        return None
    if not args.start_date or not args.end_date:
        raise ValueError("未提供 --dates 时，必须同时提供 --start-date 和 --end-date")

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if start > end:
        raise ValueError("start-date 不能晚于 end-date")

    with SessionLocal() as db:
        rows = (
            db.query(StockDaily.trade_date)
            .distinct()
            .filter(StockDaily.trade_date >= start, StockDaily.trade_date <= end)
            .order_by(StockDaily.trade_date.asc())
            .all()
        )
    dates = [trade_date.isoformat() for trade_date, in rows if trade_date]
    if not dates:
        raise ValueError(f"区间 {start.isoformat()} ~ {end.isoformat()} 内未找到交易日")
    return dates


def selected_scopes(scope: str) -> list[str]:
    if scope == "both":
        return ["tomorrow-star", "current-hot"]
    return [scope]


def build_tomorrow_star_issues(snapshot: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    candidate_count = int(snapshot.get("candidate_count", 0) or 0)
    analysis_count = int(snapshot.get("analysis_count", 0) or 0)
    run = snapshot.get("run")

    if run is None:
        issues.append("缺少运行记录")
    else:
        status = str(run.status or "").strip().lower()
        if status != "success" and not (candidate_count > 0 and analysis_count > 0):
            issues.append(f"运行状态为 {status or 'unknown'}")
        if (
            status == "success"
            and str(getattr(run, "source", "") or "").strip().lower() == "manual_rebuild"
            and candidate_count == 0
            and analysis_count == 0
        ):
            issues.append("旧版 manual_rebuild 空结果")

    if candidate_count != analysis_count:
        issues.append(f"候选数 {candidate_count} 与分析数 {analysis_count} 不一致")

    null_score_count = int(snapshot.get("null_score_count", 0) or 0)
    if null_score_count > 0:
        issues.append(f"存在 {null_score_count} 条空评分记录")

    prefilter_blocked_signal_count = int(snapshot.get("prefilter_blocked_signal_count", 0) or 0)
    if prefilter_blocked_signal_count > 0:
        issues.append(f"存在 {prefilter_blocked_signal_count} 条旧版 prefilter_blocked 信号")

    missing_prefilter_count = int(snapshot.get("missing_prefilter_count", 0) or 0)
    if missing_prefilter_count > 0:
        issues.append(f"存在 {missing_prefilter_count} 条记录缺少 prefilter 明细")

    return issues


def build_current_hot_issues(snapshot: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    candidate_count = int(snapshot.get("candidate_count", 0) or 0)
    analysis_count = int(snapshot.get("analysis_count", 0) or 0)
    run = snapshot.get("run")

    if run is None:
        issues.append("缺少运行记录")
    else:
        status = str(run.status or "").strip().lower()
        if status != "success" and not (candidate_count > 0 and analysis_count > 0):
            issues.append(f"运行状态为 {status or 'unknown'}")
        if status == "success" and candidate_count == 0 and analysis_count == 0:
            issues.append("成功状态下缺少热盘数据")

    if candidate_count != analysis_count:
        issues.append(f"候选数 {candidate_count} 与分析数 {analysis_count} 不一致")

    missing_details_count = int(snapshot.get("missing_details_count", 0) or 0)
    if missing_details_count > 0:
        issues.append(f"存在 {missing_details_count} 条记录缺少 details_json")

    return issues


def detect_noncompliant_tomorrow_star_dates(window_size: int) -> tuple[list[str], dict[str, list[str]], list[str]]:
    recent_dates = get_recent_trade_dates(window_size)
    if not recent_dates:
        return [], {}, []

    pick_dates = [date.fromisoformat(item) for item in recent_dates]
    with SessionLocal() as db:
        run_map = {
            row.pick_date.isoformat(): row
            for row in db.query(TomorrowStarRun).filter(TomorrowStarRun.pick_date.in_(pick_dates)).all()
        }
        candidate_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(Candidate.pick_date, func.count(Candidate.id))
            .filter(Candidate.pick_date.in_(pick_dates))
            .group_by(Candidate.pick_date)
            .all()
        }
        analysis_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(AnalysisResult.pick_date, func.count(AnalysisResult.id))
            .filter(AnalysisResult.pick_date.in_(pick_dates))
            .group_by(AnalysisResult.pick_date)
            .all()
        }
        trend_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(AnalysisResult.pick_date, func.count(AnalysisResult.id))
            .filter(
                AnalysisResult.pick_date.in_(pick_dates),
                AnalysisResult.signal_type == "trend_start",
            )
            .group_by(AnalysisResult.pick_date)
            .all()
        }
        consecutive_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(Candidate.pick_date, func.count(Candidate.id))
            .filter(
                Candidate.pick_date.in_(pick_dates),
                Candidate.consecutive_days >= 2,
            )
            .group_by(Candidate.pick_date)
            .all()
        }

        null_score_counts: dict[str, int] = defaultdict(int)
        prefilter_blocked_signal_counts: dict[str, int] = defaultdict(int)
        missing_prefilter_counts: dict[str, int] = defaultdict(int)
        rows = (
            db.query(AnalysisResult.pick_date, AnalysisResult.total_score, AnalysisResult.signal_type, AnalysisResult.details_json)
            .filter(AnalysisResult.pick_date.in_(pick_dates))
            .all()
        )
        for pick_date, total_score, signal_type, details_json in rows:
            key = pick_date.isoformat()
            if total_score is None:
                null_score_counts[key] += 1
            if signal_type == "prefilter_blocked":
                prefilter_blocked_signal_counts[key] += 1
            prefilter = details_json.get("prefilter") if isinstance(details_json, dict) else None
            if not isinstance(prefilter, dict):
                missing_prefilter_counts[key] += 1

    issue_map: dict[str, list[str]] = {}
    repair_dates: list[str] = []
    for trade_date in recent_dates:
        snapshot = {
            "run": run_map.get(trade_date),
            "candidate_count": candidate_count_map.get(trade_date, 0),
            "analysis_count": analysis_count_map.get(trade_date, 0),
            "trend_start_count": trend_count_map.get(trade_date, 0),
            "consecutive_candidate_count": consecutive_count_map.get(trade_date, 0),
            "null_score_count": null_score_counts.get(trade_date, 0),
            "prefilter_blocked_signal_count": prefilter_blocked_signal_counts.get(trade_date, 0),
            "missing_prefilter_count": missing_prefilter_counts.get(trade_date, 0),
        }
        issues = build_tomorrow_star_issues(snapshot)
        if issues:
            repair_dates.append(trade_date)
            issue_map[trade_date] = issues

    return repair_dates, issue_map, recent_dates


def detect_noncompliant_current_hot_dates(window_size: int) -> tuple[list[str], dict[str, list[str]], list[str]]:
    recent_dates = get_recent_trade_dates(window_size)
    if not recent_dates:
        return [], {}, []

    pick_dates = [date.fromisoformat(item) for item in recent_dates]
    with SessionLocal() as db:
        run_map = {
            row.pick_date.isoformat(): row
            for row in db.query(CurrentHotRun).filter(CurrentHotRun.pick_date.in_(pick_dates)).all()
        }
        candidate_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(CurrentHotCandidate.pick_date, func.count(CurrentHotCandidate.id))
            .filter(CurrentHotCandidate.pick_date.in_(pick_dates))
            .group_by(CurrentHotCandidate.pick_date)
            .all()
        }
        analysis_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(CurrentHotAnalysisResult.pick_date, func.count(CurrentHotAnalysisResult.id))
            .filter(CurrentHotAnalysisResult.pick_date.in_(pick_dates))
            .group_by(CurrentHotAnalysisResult.pick_date)
            .all()
        }
        trend_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(CurrentHotAnalysisResult.pick_date, func.count(CurrentHotAnalysisResult.id))
            .filter(
                CurrentHotAnalysisResult.pick_date.in_(pick_dates),
                CurrentHotAnalysisResult.signal_type == "trend_start",
            )
            .group_by(CurrentHotAnalysisResult.pick_date)
            .all()
        }
        consecutive_count_map = {
            pick_date.isoformat(): int(count or 0)
            for pick_date, count in db.query(CurrentHotCandidate.pick_date, func.count(CurrentHotCandidate.id))
            .filter(
                CurrentHotCandidate.pick_date.in_(pick_dates),
                CurrentHotCandidate.consecutive_days >= 2,
            )
            .group_by(CurrentHotCandidate.pick_date)
            .all()
        }

        missing_details_counts: dict[str, int] = defaultdict(int)
        rows = (
            db.query(CurrentHotAnalysisResult.pick_date, CurrentHotAnalysisResult.details_json)
            .filter(CurrentHotAnalysisResult.pick_date.in_(pick_dates))
            .all()
        )
        for pick_date, details_json in rows:
            if not isinstance(details_json, dict):
                missing_details_counts[pick_date.isoformat()] += 1

    issue_map: dict[str, list[str]] = {}
    repair_dates: list[str] = []
    for trade_date in recent_dates:
        snapshot = {
            "run": run_map.get(trade_date),
            "candidate_count": candidate_count_map.get(trade_date, 0),
            "analysis_count": analysis_count_map.get(trade_date, 0),
            "trend_start_count": trend_count_map.get(trade_date, 0),
            "consecutive_candidate_count": consecutive_count_map.get(trade_date, 0),
            "missing_details_count": missing_details_counts.get(trade_date, 0),
        }
        issues = build_current_hot_issues(snapshot)
        if issues:
            repair_dates.append(trade_date)
            issue_map[trade_date] = issues

    return repair_dates, issue_map, recent_dates


def repair_tomorrow_star(trade_dates: list[str], reviewer: str, window_size: int) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with SessionLocal() as db:
        service = TomorrowStarWindowService(db)
        for trade_date in trade_dates:
            result = service.rebuild_trade_date(
                trade_date,
                reviewer=reviewer,
                source="manual_repair",
                window_size=window_size,
            )
            results.append({"scope": "tomorrow-star", **result})
    return results


def repair_current_hot(trade_dates: list[str], reviewer: str) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with SessionLocal() as db:
        service = CurrentHotService(db)
        for trade_date in trade_dates:
            result = service.generate_for_trade_date(trade_date, reviewer=reviewer)
            results.append({"scope": "current-hot", **result})
    return results


def main() -> int:
    args = parse_args()
    manual_trade_dates = resolve_manual_trade_dates(args)
    scopes = selected_scopes(args.scope)

    repair_plan: dict[str, list[str]] = {scope: [] for scope in scopes}
    inspection: dict[str, dict[str, Any]] = {}

    if manual_trade_dates is not None:
        for scope in scopes:
            repair_plan[scope] = manual_trade_dates
            inspection[scope] = {
                "mode": "manual",
                "inspected_trade_dates": manual_trade_dates,
                "repair_trade_dates": manual_trade_dates,
                "issue_map": {},
            }
    else:
        if "tomorrow-star" in scopes:
            repair_dates, issue_map, inspected_dates = detect_noncompliant_tomorrow_star_dates(args.window_size)
            repair_plan["tomorrow-star"] = repair_dates
            inspection["tomorrow-star"] = {
                "mode": "auto",
                "inspected_trade_dates": inspected_dates,
                "repair_trade_dates": repair_dates,
                "issue_map": issue_map,
            }
        if "current-hot" in scopes:
            repair_dates, issue_map, inspected_dates = detect_noncompliant_current_hot_dates(args.window_size)
            repair_plan["current-hot"] = repair_dates
            inspection["current-hot"] = {
                "mode": "auto",
                "inspected_trade_dates": inspected_dates,
                "repair_trade_dates": repair_dates,
                "issue_map": issue_map,
            }

    results: list[dict[str, object]] = []
    if repair_plan.get("tomorrow-star"):
        results.extend(repair_tomorrow_star(repair_plan["tomorrow-star"], reviewer=args.reviewer, window_size=args.window_size))
    if repair_plan.get("current-hot"):
        results.extend(repair_current_hot(repair_plan["current-hot"], reviewer=args.reviewer))

    success_count = sum(1 for item in results if item.get("success") is True or item.get("status") == "ok")
    all_repair_dates = sorted({trade_date for dates in repair_plan.values() for trade_date in dates})
    payload = {
        "scope": args.scope,
        "mode": "manual" if manual_trade_dates is not None else "auto",
        "window_size": args.window_size,
        "trade_dates": all_repair_dates,
        "inspection": inspection,
        "success_count": success_count,
        "total_count": len(results),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
    if not results:
        return 0
    return 0 if success_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
