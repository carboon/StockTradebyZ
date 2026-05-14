#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date as date_class, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"

if (
    os.environ.get("STOCKTRADE_INTRADAY_BOOTSTRAPPED") != "1"
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
):
    env = dict(os.environ)
    env["STOCKTRADE_INTRADAY_BOOTSTRAPPED"] = "1"
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
from app.services.current_hot_intraday_service import CurrentHotIntradayAnalysisService
from app.services.intraday_analysis_service import IntradayAnalysisService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成中盘快照（默认按 11:30 截止）")
    parser.add_argument("--target-date", default=None, help="交易日 YYYY-MM-DD，默认今天")
    parser.add_argument("--cutoff-time", default="11:30:00", help="分时截止时间，默认 11:30:00")
    parser.add_argument("--skip-tomorrow-star", action="store_true", help="跳过明日之星中盘快照")
    parser.add_argument("--skip-current-hot", action="store_true", help="跳过当前热盘中盘快照")
    parser.add_argument("--force", action="store_true", help="忽略 11:30 后才能执行的限制")
    return parser.parse_args()


def _normalize_target_date(value: str | None, service: IntradayAnalysisService) -> date_class:
    if not value:
        return service.get_trade_date()
    return date_class.fromisoformat(str(value).strip())


def _cutoff_as_time(value: str) -> time:
    parsed = datetime.strptime(str(value).strip(), "%H:%M:%S")
    return parsed.time()


def main() -> int:
    args = parse_args()

    with SessionLocal() as db:
        intraday_service = IntradayAnalysisService(db)
        hot_service = CurrentHotIntradayAnalysisService(db)
        target_date = _normalize_target_date(args.target_date, intraday_service)
        now = intraday_service.now_shanghai()
        cutoff = _cutoff_as_time(args.cutoff_time)

        if not args.force and target_date == now.date() and now.timetz().replace(tzinfo=None) < cutoff:
            payload = {
                "success": False,
                "message": f"当前未到 {args.cutoff_time}，不生成中盘快照",
                "target_date": target_date.isoformat(),
                "cutoff_time": args.cutoff_time,
                "now": now.isoformat(),
            }
            print(json.dumps(payload, ensure_ascii=False, default=str))
            return 1

        result: dict[str, object] = {
            "success": True,
            "target_date": target_date.isoformat(),
            "cutoff_time": args.cutoff_time,
        }

        if not args.skip_tomorrow_star:
            result["tomorrow_star"] = intraday_service.generate_snapshot(
                trade_date=target_date,
                cutoff_time_text=args.cutoff_time,
            )
        if not args.skip_current_hot:
            result["current_hot"] = hot_service.generate_snapshot(
                trade_date=target_date,
                cutoff_time_text=args.cutoff_time,
            )

        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
